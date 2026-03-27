#define _GNU_SOURCE
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <stdint.h>
#include <ctype.h>
#include <stdio.h>

typedef struct {
    int fd;
    char *data;
    size_t file_size;
    uint32_t *offsets;
    uint32_t *lengths;
    uint32_t line_count;
    uint32_t _cap;
} LogFile;

typedef struct {
    uint32_t *indices;
    uint32_t count;
    uint32_t _cap;
} Results;

static Results *results_new(void) {
    Results *r = calloc(1, sizeof(Results));
    r->_cap = 4096;
    r->indices = malloc(r->_cap * sizeof(uint32_t));
    return r;
}

static void results_push(Results *r, uint32_t idx) {
    if (r->count >= r->_cap) {
        r->_cap *= 2;
        r->indices = realloc(r->indices, r->_cap * sizeof(uint32_t));
    }
    r->indices[r->count++] = idx;
}

static int wildmatch(const char *pat, const char *str, size_t str_len) {
    const char *s = str, *p = pat;
    const char *s_end = str + str_len;
    const char *star_p = NULL, *star_s = NULL;

    while (s < s_end) {
        if (*p == *s || *p == '?') {
            p++; s++;
        } else if (*p == '*') {
            star_p = p++;
            star_s = s;
        } else if (star_p) {
            p = star_p + 1;
            s = ++star_s;
        } else {
            return 0;
        }
    }
    while (*p == '*') p++;
    return *p == '\0';
}

static int wildmatch_i(const char *pat, const char *str, size_t str_len) {
    const char *s = str, *p = pat;
    const char *s_end = str + str_len;
    const char *star_p = NULL, *star_s = NULL;

    while (s < s_end) {
        if (tolower((unsigned char)*p) == tolower((unsigned char)*s) || *p == '?') {
            p++; s++;
        } else if (*p == '*') {
            star_p = p++;
            star_s = s;
        } else if (star_p) {
            p = star_p + 1;
            s = ++star_s;
        } else {
            return 0;
        }
    }
    while (*p == '*') p++;
    return *p == '\0';
}

static const char *extract_ts(const char *line, size_t len, size_t *ts_len) {
    static const char key[] = "\"timestamp\":\"";
    const char *found = memmem(line, len, key, sizeof(key) - 1);
    if (!found) { *ts_len = 0; return NULL; }
    const char *ts = found + sizeof(key) - 1;
    const char *end = memchr(ts, '"', (line + len) - ts);
    if (!end) { *ts_len = 0; return NULL; }
    *ts_len = end - ts;
    return ts;
}

/* ---- public API ---- */

LogFile *lf_open(const char *path) {
    int fd = open(path, O_RDONLY);
    if (fd < 0) return NULL;

    struct stat st;
    if (fstat(fd, &st) < 0) { close(fd); return NULL; }
    if (st.st_size == 0) { close(fd); return NULL; }

    char *data = mmap(NULL, st.st_size, PROT_READ, MAP_PRIVATE, fd, 0);
    if (data == MAP_FAILED) { close(fd); return NULL; }

    madvise(data, st.st_size, MADV_SEQUENTIAL);

    LogFile *lf = calloc(1, sizeof(LogFile));
    lf->fd = fd;
    lf->data = data;
    lf->file_size = st.st_size;
    lf->_cap = 65536;
    lf->offsets = malloc(lf->_cap * sizeof(uint32_t));
    lf->lengths = malloc(lf->_cap * sizeof(uint32_t));

    size_t start = 0;
    for (size_t i = 0; i < (size_t)st.st_size; i++) {
        if (data[i] == '\n') {
            if (i > start) {
                if (lf->line_count >= lf->_cap) {
                    lf->_cap *= 2;
                    lf->offsets = realloc(lf->offsets, lf->_cap * sizeof(uint32_t));
                    lf->lengths = realloc(lf->lengths, lf->_cap * sizeof(uint32_t));
                }
                lf->offsets[lf->line_count] = (uint32_t)start;
                lf->lengths[lf->line_count] = (uint32_t)(i - start);
                lf->line_count++;
            }
            start = i + 1;
        }
    }
    if (start < (size_t)st.st_size) {
        if (lf->line_count >= lf->_cap) {
            lf->_cap *= 2;
            lf->offsets = realloc(lf->offsets, lf->_cap * sizeof(uint32_t));
            lf->lengths = realloc(lf->lengths, lf->_cap * sizeof(uint32_t));
        }
        lf->offsets[lf->line_count] = (uint32_t)start;
        lf->lengths[lf->line_count] = (uint32_t)((size_t)st.st_size - start);
        lf->line_count++;
    }

    madvise(data, st.st_size, MADV_RANDOM);
    return lf;
}

void lf_close(LogFile *lf) {
    if (!lf) return;
    if (lf->data) munmap(lf->data, lf->file_size);
    if (lf->fd >= 0) close(lf->fd);
    free(lf->offsets);
    free(lf->lengths);
    free(lf);
}

uint32_t lf_line_count(LogFile *lf) {
    return lf ? lf->line_count : 0;
}

const char *lf_get_line(LogFile *lf, uint32_t idx, uint32_t *out_len) {
    if (!lf || idx >= lf->line_count) {
        if (out_len) *out_len = 0;
        return NULL;
    }
    if (out_len) *out_len = lf->lengths[idx];
    return lf->data + lf->offsets[idx];
}

void lf_results_free(Results *r) {
    if (r) {
        free(r->indices);
        free(r);
    }
}

Results *lf_search_substr(LogFile *lf, const char *needle) {
    Results *r = results_new();
    if (!lf || !needle) return r;
    size_t nlen = strlen(needle);
    if (nlen == 0) return r;

    for (uint32_t i = 0; i < lf->line_count; i++) {
        if (memmem(lf->data + lf->offsets[i], lf->lengths[i], needle, nlen))
            results_push(r, i);
    }
    return r;
}

Results *lf_search_substr_i(LogFile *lf, const char *needle) {
    Results *r = results_new();
    if (!lf || !needle) return r;
    size_t nlen = strlen(needle);
    if (nlen == 0) return r;

    char *lower_needle = malloc(nlen);
    for (size_t j = 0; j < nlen; j++)
        lower_needle[j] = tolower((unsigned char)needle[j]);

    for (uint32_t i = 0; i < lf->line_count; i++) {
        const char *line = lf->data + lf->offsets[i];
        uint32_t len = lf->lengths[i];
        int found = 0;
        if (len >= nlen) {
            for (uint32_t p = 0; p <= len - (uint32_t)nlen; p++) {
                int match = 1;
                for (size_t j = 0; j < nlen; j++) {
                    if (tolower((unsigned char)line[p + j]) != lower_needle[j]) {
                        match = 0;
                        break;
                    }
                }
                if (match) { found = 1; break; }
            }
        }
        if (found) results_push(r, i);
    }
    free(lower_needle);
    return r;
}

Results *lf_search_wild(LogFile *lf, const char *pattern, int case_insensitive) {
    Results *r = results_new();
    if (!lf || !pattern) return r;

    for (uint32_t i = 0; i < lf->line_count; i++) {
        int m = case_insensitive
            ? wildmatch_i(pattern, lf->data + lf->offsets[i], lf->lengths[i])
            : wildmatch(pattern, lf->data + lf->offsets[i], lf->lengths[i]);
        if (m) results_push(r, i);
    }
    return r;
}

Results *lf_search_kv(LogFile *lf, const char *key, const char *val_pattern) {
    Results *r = results_new();
    if (!lf || !key) return r;

    char needle[512];
    int nlen = snprintf(needle, sizeof(needle), "\"%s\":", key);
    if (nlen <= 0 || nlen >= (int)sizeof(needle)) return r;

    for (uint32_t i = 0; i < lf->line_count; i++) {
        const char *line = lf->data + lf->offsets[i];
        uint32_t len = lf->lengths[i];

        const char *found = memmem(line, len, needle, nlen);
        if (!found) continue;

        const char *val_start = found + nlen;
        const char *line_end = line + len;

        while (val_start < line_end && *val_start == ' ') val_start++;
        if (val_start >= line_end) continue;

        const char *val_end;
        if (*val_start == '"') {
            val_start++;
            val_end = memchr(val_start, '"', line_end - val_start);
            if (!val_end) continue;
        } else {
            val_end = val_start;
            while (val_end < line_end && *val_end != ',' && *val_end != '}' && *val_end != ' ')
                val_end++;
        }

        size_t val_len = val_end - val_start;
        if (!val_pattern || !val_pattern[0] || wildmatch(val_pattern, val_start, val_len))
            results_push(r, i);
    }
    return r;
}

Results *lf_search_time(LogFile *lf, const char *start_ts, const char *end_ts) {
    Results *r = results_new();
    if (!lf) return r;

    size_t start_len = start_ts ? strlen(start_ts) : 0;
    size_t end_len = end_ts ? strlen(end_ts) : 0;

    uint32_t lo = 0;
    if (start_ts && start_len > 0) {
        uint32_t a = 0, b = lf->line_count;
        while (a < b) {
            uint32_t mid = a + (b - a) / 2;
            size_t ts_len;
            const char *ts = extract_ts(
                lf->data + lf->offsets[mid], lf->lengths[mid], &ts_len);
            size_t cmp_len = ts_len < start_len ? ts_len : start_len;
            if (ts && memcmp(ts, start_ts, cmp_len) < 0)
                a = mid + 1;
            else
                b = mid;
        }
        lo = a;
    }

    for (uint32_t i = lo; i < lf->line_count; i++) {
        if (end_ts && end_len > 0) {
            size_t ts_len;
            const char *ts = extract_ts(
                lf->data + lf->offsets[i], lf->lengths[i], &ts_len);
            size_t cmp_len = ts_len < end_len ? ts_len : end_len;
            if (ts && memcmp(ts, end_ts, cmp_len) > 0) break;
        }
        results_push(r, i);
    }
    return r;
}

Results *lf_search_level(LogFile *lf, const char *level) {
    Results *r = results_new();
    if (!lf || !level) return r;

    char needle[64];
    int nlen = snprintf(needle, sizeof(needle), "\"level\":\"%s\"", level);
    if (nlen <= 0) return r;

    for (uint32_t i = 0; i < lf->line_count; i++) {
        if (memmem(lf->data + lf->offsets[i], lf->lengths[i], needle, nlen))
            results_push(r, i);
    }
    return r;
}

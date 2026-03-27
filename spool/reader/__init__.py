import ctypes
import fnmatch
import mmap
from pathlib import Path


def _load_lib():
    lib_path = Path(__file__).parent / "liblogindex.so"
    if not lib_path.exists():
        return None
    try:
        lib = ctypes.CDLL(str(lib_path))

        lib.lf_open.restype = ctypes.c_void_p
        lib.lf_open.argtypes = [ctypes.c_char_p]

        lib.lf_close.restype = None
        lib.lf_close.argtypes = [ctypes.c_void_p]

        lib.lf_line_count.restype = ctypes.c_uint32
        lib.lf_line_count.argtypes = [ctypes.c_void_p]

        lib.lf_get_line.restype = ctypes.c_char_p
        lib.lf_get_line.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                     ctypes.POINTER(ctypes.c_uint32)]

        class Results(ctypes.Structure):
            _fields_ = [
                ("indices", ctypes.POINTER(ctypes.c_uint32)),
                ("count", ctypes.c_uint32),
                ("_cap", ctypes.c_uint32),
            ]

        for fn_name in ("lf_search_substr", "lf_search_substr_i"):
            fn = getattr(lib, fn_name)
            fn.restype = ctypes.POINTER(Results)
            fn.argtypes = [ctypes.c_void_p, ctypes.c_char_p]

        lib.lf_search_wild.restype = ctypes.POINTER(Results)
        lib.lf_search_wild.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                        ctypes.c_int]

        lib.lf_search_kv.restype = ctypes.POINTER(Results)
        lib.lf_search_kv.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                      ctypes.c_char_p]

        lib.lf_search_time.restype = ctypes.POINTER(Results)
        lib.lf_search_time.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                        ctypes.c_char_p]

        lib.lf_search_level.restype = ctypes.POINTER(Results)
        lib.lf_search_level.argtypes = [ctypes.c_void_p, ctypes.c_char_p]

        lib.lf_results_free.restype = None
        lib.lf_results_free.argtypes = [ctypes.POINTER(Results)]

        lib._Results = Results
        return lib
    except OSError:
        return None


_LIB = _load_lib()


class _PythonIndex:
    def __init__(self, path):
        self._f = open(path, "rb")
        self._mm = mmap.mmap(self._f.fileno(), 0, access=mmap.ACCESS_READ)
        self._lines = []
        start = 0
        data = self._mm
        size = len(data)
        while start < size:
            nl = data.find(b"\n", start)
            if nl == -1:
                if start < size:
                    self._lines.append((start, size - start))
                break
            if nl > start:
                self._lines.append((start, nl - start))
            start = nl + 1

    @property
    def line_count(self):
        return len(self._lines)

    def get_line(self, idx):
        off, length = self._lines[idx]
        return self._mm[off:off + length].decode()

    def get_line_bytes(self, idx):
        off, length = self._lines[idx]
        return self._mm[off:off + length]

    def search_substr(self, pattern):
        needle = pattern.encode()
        results = []
        for i, (off, length) in enumerate(self._lines):
            if self._mm.find(needle, off, off + length) != -1:
                results.append(i)
        return results

    def search_wild(self, pattern):
        results = []
        for i, (off, length) in enumerate(self._lines):
            line = self._mm[off:off + length].decode(errors="replace")
            if fnmatch.fnmatch(line, pattern):
                results.append(i)
        return results

    def search_kv(self, key, val_pattern):
        import orjson
        results = []
        for i, (off, length) in enumerate(self._lines):
            try:
                data = orjson.loads(self._mm[off:off + length])
            except Exception:
                continue
            val = data.get(key)
            if val is None:
                continue
            if not val_pattern:
                results.append(i)
            elif fnmatch.fnmatch(str(val), val_pattern):
                results.append(i)
        return results

    def search_time(self, start_ts, end_ts):
        import orjson
        results = []
        for i, (off, length) in enumerate(self._lines):
            try:
                data = orjson.loads(self._mm[off:off + length])
            except Exception:
                continue
            ts = data.get("timestamp", "")
            if start_ts and ts < start_ts:
                continue
            if end_ts and ts > end_ts:
                break
            results.append(i)
        return results

    def search_level(self, level):
        needle = ('"level":"%s"' % level).encode()
        results = []
        for i, (off, length) in enumerate(self._lines):
            if self._mm.find(needle, off, off + length) != -1:
                results.append(i)
        return results

    def close(self):
        self._mm.close()
        self._f.close()


class LogIndex:
    def __init__(self, path):
        self.path = Path(path)
        self._lib = _LIB
        self._handle = None
        self._py = None

        if self._lib:
            self._handle = self._lib.lf_open(str(path).encode())
            if not self._handle:
                self._lib = None

        if not self._lib:
            self._py = _PythonIndex(path)

    @property
    def using_native(self):
        return self._lib is not None

    @property
    def line_count(self):
        if self._handle:
            return self._lib.lf_line_count(self._handle)
        return self._py.line_count

    def get_line(self, idx):
        if self._handle:
            length = ctypes.c_uint32()
            ptr = self._lib.lf_get_line(self._handle, idx, ctypes.byref(length))
            if not ptr:
                return ""
            return ptr[:length.value].decode(errors="replace")
        return self._py.get_line(idx)

    def _c_results(self, results_ptr):
        if not results_ptr:
            return []
        r = results_ptr.contents
        out = [r.indices[i] for i in range(r.count)]
        self._lib.lf_results_free(results_ptr)
        return out

    def search_substr(self, pattern):
        if self._handle:
            return self._c_results(
                self._lib.lf_search_substr(self._handle, pattern.encode()))
        return self._py.search_substr(pattern)

    def search_wild(self, pattern):
        if self._handle:
            return self._c_results(
                self._lib.lf_search_wild(self._handle, pattern.encode(), 0))
        return self._py.search_wild(pattern)

    def search_kv(self, key, val_pattern):
        if self._handle:
            return self._c_results(
                self._lib.lf_search_kv(
                    self._handle, key.encode(),
                    val_pattern.encode() if val_pattern else b""))
        return self._py.search_kv(key, val_pattern)

    def search_time(self, start_ts, end_ts):
        if self._handle:
            return self._c_results(
                self._lib.lf_search_time(
                    self._handle,
                    start_ts.encode() if start_ts else b"",
                    end_ts.encode() if end_ts else b""))
        return self._py.search_time(start_ts, end_ts)

    def search_level(self, level):
        if self._handle:
            return self._c_results(
                self._lib.lf_search_level(self._handle, level.encode()))
        return self._py.search_level(level)

    def find_line_at_time(self, timestamp):
        import orjson
        lo, hi = 0, self.line_count
        while lo < hi:
            mid = lo + (hi - lo) // 2
            try:
                ts = orjson.loads(self.get_line(mid)).get("timestamp", "")
            except Exception:
                ts = ""
            if ts < timestamp:
                lo = mid + 1
            else:
                hi = mid
        return min(lo, max(0, self.line_count - 1))

    def close(self):
        if self._handle:
            self._lib.lf_close(self._handle)
            self._handle = None
        if self._py:
            self._py.close()
            self._py = None

CC = gcc
CFLAGS = -O3 -shared -fPIC -Wall
TARGET = spool/reader/liblogindex.so

all: $(TARGET)

$(TARGET): spool/reader/logindex.c
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f $(TARGET)

.PHONY: all clean

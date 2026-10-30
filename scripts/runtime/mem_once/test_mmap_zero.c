#define _GNU_SOURCE
#include <sys/mman.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <stdint.h>

int main(void) {
    write(1, "TEST_MMAP_ZERO_START\n", 22);
    size_t sz = 0x70000; // 448 KiB, same size as [0x200ffe000, 0x20106e000)
    void *p = mmap(NULL, sz, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (p == MAP_FAILED) {
        write(2, "MMAP_FAILED\n", 12);
        return 1;
    }

    uint8_t *b = (uint8_t *)p;
    size_t offsets[] = {
        0x0,
        0x1000,
        0x2f440, // exact offset of uaddr
        0x30000,
        0x6ffff
    };
    int n_offsets = sizeof(offsets)/sizeof(offsets[0]);

    for (int i = 0; i < n_offsets; i++) {
        size_t off = offsets[i];
        if (b[off] != 0) {
            char buf[64];
            int len = snprintf(buf, sizeof(buf), "NONZERO_BYTE at 0x%zx: 0x%02x\n", off, b[off]);
            write(2, buf, len);
            return 2;
        }
    }

    // Now write non-zero value at 0x2f440 to confirm writability
    uint32_t *word = (uint32_t *)(b + 0x2f440);
    *word = 0x12345678;
    if (*word != 0x12345678) {
        write(2, "WRITE_VERIFY_FAIL\n", 19);
        return 3;
    }

    munmap(p, sz);
    write(1, "TEST_MMAP_ZERO_OK\n", 19);
    return 0;
}

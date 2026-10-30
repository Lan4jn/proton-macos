#define _GNU_SOURCE
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#define PAGE_SZ 4096
#define FILE_PAGES 4
#define FILE_SZ (PAGE_SZ * FILE_PAGES)

int main(int argc, char **argv) {
    const char *test_path = "/tmp/elfuse_private_cow_test.bin";
    if (argc > 1) {
        test_path = argv[1];
    }

    unlink(test_path);
    int fd = open(test_path, O_RDWR | O_CREAT | O_TRUNC, 0666);
    if (fd < 0) {
        perror("open");
        return 10;
    }

    /* Initialize file with pattern: page i has byte value (0x10 + i) */
    uint8_t init_buf[PAGE_SZ];
    for (int p = 0; p < FILE_PAGES; p++) {
        memset(init_buf, 0x10 + p, PAGE_SZ);
        if (pwrite(fd, init_buf, PAGE_SZ, p * PAGE_SZ) != PAGE_SZ) {
            perror("pwrite init");
            close(fd);
            return 11;
        }
    }

    /* MAP_PRIVATE RW mapping */
    void *map = mmap(NULL, FILE_SZ, PROT_READ | PROT_WRITE, MAP_PRIVATE, fd, 0);
    if (map == MAP_FAILED) {
        perror("mmap");
        close(fd);
        return 12;
    }
    uint8_t *m = (uint8_t *)map;

    int test_failures = 0;

    /* -------------------------------------------------------------------
     * Test (a): Live file modification visible on unwritten page
     * Modify page 0 in file: write 0xAA
     * ------------------------------------------------------------------- */
    printf("[TEST_A] Modifying file page 0 to 0xAA after MAP_PRIVATE...\n");
    memset(init_buf, 0xAA, PAGE_SZ);
    if (pwrite(fd, init_buf, PAGE_SZ, 0) != PAGE_SZ) {
        perror("pwrite page 0");
        return 13;
    }

    /* Read page 0 from mapping */
    uint8_t val_a = m[100];
    if (val_a == 0xAA) {
        printf("[TEST_A_PASS] Live file modification visible: got 0x%02x (expected 0xAA)\n", val_a);
    } else {
        printf("[TEST_A_FAIL] Live file modification INVISIBLE: got 0x%02x (expected 0xAA, stuck at snapshot 0x10)\n", val_a);
        test_failures |= 1;
    }

    /* -------------------------------------------------------------------
     * Test (b): COW isolation after guest write
     * Guest writes 0x55 to page 1 of mapping
     * Then modify file page 1 to 0xBB
     * Guest should still see 0x55, NOT 0xBB
     * ------------------------------------------------------------------- */
    printf("[TEST_B] Guest writes 0x55 to page 1, then file modified to 0xBB...\n");
    m[PAGE_SZ + 100] = 0x55;

    memset(init_buf, 0xBB, PAGE_SZ);
    if (pwrite(fd, init_buf, PAGE_SZ, PAGE_SZ) != PAGE_SZ) {
        perror("pwrite page 1");
        return 14;
    }

    uint8_t val_b = m[PAGE_SZ + 100];
    if (val_b == 0x55) {
        printf("[TEST_B_PASS] COW isolation intact: guest sees 0x%02x (expected 0x55)\n", val_b);
    } else {
        printf("[TEST_B_FAIL] COW isolation broken: guest sees 0x%02x (expected 0x55, leaked 0x%02x)\n", val_b, val_b);
        test_failures |= 2;
    }

    /* -------------------------------------------------------------------
     * Test (c): Guest write never written back to underlying file
     * Guest wrote 0x55 to page 1. Check file page 1 at offset 100
     * Should be 0xBB (what pwrite wrote), NOT 0x55
     * Also write 0x77 to page 2 (which file has 0x12)
     * ------------------------------------------------------------------- */
    printf("[TEST_C] Verifying guest write does not write back to file...\n");
    m[2 * PAGE_SZ + 200] = 0x77;
    msync(map, FILE_SZ, MS_SYNC);

    uint8_t file_val = 0;
    if (pread(fd, &file_val, 1, 2 * PAGE_SZ + 200) != 1) {
        perror("pread page 2");
        return 15;
    }

    if (file_val == 0x12) {
        printf("[TEST_C_PASS] File not modified: pread got 0x%02x (expected 0x12, not 0x77)\n", file_val);
    } else {
        printf("[TEST_C_FAIL] Guest write leaked to file: pread got 0x%02x (expected 0x12, got 0x%02x)\n", file_val, file_val);
        test_failures |= 4;
    }

    munmap(map, FILE_SZ);
    close(fd);
    unlink(test_path);

    if (test_failures == 0) {
        printf("ALL_PRIVATE_COW_TESTS_PASS\n");
        return 0;
    } else {
        printf("PRIVATE_COW_TESTS_FAILED failure_mask=0x%x\n", test_failures);
        return test_failures;
    }
}

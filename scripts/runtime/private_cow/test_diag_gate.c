#define _GNU_SOURCE
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#define TARGET_LEN 0x144000
#define PAGE_SZ 4096

int main(int argc, char **argv) {
    const char *test_path = "/tmp/elfuse_diag_test_unlinked.bin";
    int fd = open(test_path, O_RDWR | O_CREAT | O_TRUNC, 0666);
    if (fd < 0) {
        perror("open");
        return 10;
    }

    /* Fill file with 0x10 */
    uint8_t buf[PAGE_SZ];
    memset(buf, 0x10, PAGE_SZ);
    for (size_t off = 0; off < TARGET_LEN; off += PAGE_SZ) {
        if (pwrite(fd, buf, PAGE_SZ, off) != PAGE_SZ) {
            perror("pwrite init");
            close(fd);
            return 11;
        }
    }

    /* Unlink file so st_nlink == 0 (matching ELFUSE_DIAG_SESSION_SHARED condition!) */
    unlink(test_path);

    /* MAP_PRIVATE RW with length == 0x144000, offset == 0 */
    void *map = mmap(NULL, TARGET_LEN, PROT_READ | PROT_WRITE, MAP_PRIVATE, fd, 0);
    if (map == MAP_FAILED) {
        perror("mmap");
        close(fd);
        return 12;
    }
    uint8_t *m = (uint8_t *)map;

    int test_failures = 0;

    /* Test (a): Live file modification */
    printf("[DIAG_TEST_A] Modifying file page 0 to 0xAA...\n");
    memset(buf, 0xAA, PAGE_SZ);
    pwrite(fd, buf, PAGE_SZ, 0);
    uint8_t val_a = m[100];
    if (val_a == 0xAA) {
        printf("[DIAG_TEST_A_PASS] Live file modification visible: 0x%02x\n", val_a);
    } else {
        printf("[DIAG_TEST_A_FAIL] Live file modification INVISIBLE: 0x%02x\n", val_a);
        test_failures |= 1;
    }

    /* Test (b): COW isolation after guest write */
    printf("[DIAG_TEST_B] Guest writes 0x55 to page 1, file modified to 0xBB...\n");
    m[PAGE_SZ + 100] = 0x55;
    memset(buf, 0xBB, PAGE_SZ);
    pwrite(fd, buf, PAGE_SZ, PAGE_SZ);
    uint8_t val_b = m[PAGE_SZ + 100];
    if (val_b == 0x55) {
        printf("[DIAG_TEST_B_PASS] COW isolation intact: 0x%02x\n", val_b);
    } else {
        printf("[DIAG_TEST_B_FAIL] COW isolation BROKEN (MAP_SHARED leaked): 0x%02x (expected 0x55, got file write)\n", val_b);
        test_failures |= 2;
    }

    /* Test (c): Guest write does not write back to file */
    printf("[DIAG_TEST_C] Verifying guest write does not write back to file...\n");
    m[2 * PAGE_SZ + 200] = 0x77;
    uint8_t file_val = 0;
    pread(fd, &file_val, 1, 2 * PAGE_SZ + 200);
    if (file_val == 0x10) {
        printf("[DIAG_TEST_C_PASS] File not modified: pread got 0x%02x\n", file_val);
    } else {
        printf("[DIAG_TEST_C_FAIL] Guest write LEAKED to file: pread got 0x%02x (expected 0x10, wrote back 0x77)\n", file_val);
        test_failures |= 4;
    }

    munmap(map, TARGET_LEN);
    close(fd);
    return test_failures;
}

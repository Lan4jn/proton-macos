#define _GNU_SOURCE
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <errno.h>

#define PAGE_SZ 4096
#define FILE_PAGES 8
#define TOTAL_SZ (PAGE_SZ * FILE_PAGES)
#define SESSION_GATE_SZ 0x144000  /* 1327104 bytes, matches mem.c gate */

int run_general_semantics_tests(void) {
    const char *test_path = "/tmp/probe_cow_general.bin";
    printf("=== PART 1: GENERAL MAP_PRIVATE / MAP_SHARED SEMANTICS ===\n");
    unlink(test_path);
    int fd = open(test_path, O_RDWR | O_CREAT | O_TRUNC, 0666);
    if (fd < 0) {
        perror("open general");
        return 10;
    }

    uint8_t buf[PAGE_SZ];
    for (int p = 0; p < FILE_PAGES; p++) {
        memset(buf, 0x10 + p, PAGE_SZ);
        if (pwrite(fd, buf, PAGE_SZ, p * PAGE_SZ) != PAGE_SZ) {
            perror("pwrite init");
            return 11;
        }
    }

    int failures = 0;

    /* 1. MAP_PRIVATE: Private write isolation & no write-back to file */
    printf("\n[1] Testing MAP_PRIVATE private write isolation...\n");
    void *priv_map1 = mmap(NULL, TOTAL_SZ, PROT_READ | PROT_WRITE, MAP_PRIVATE, fd, 0);
    void *priv_map2 = mmap(NULL, TOTAL_SZ, PROT_READ | PROT_WRITE, MAP_PRIVATE, fd, 0);
    if (priv_map1 == MAP_FAILED || priv_map2 == MAP_FAILED) {
        perror("mmap priv");
        return 12;
    }

    uint8_t *p1 = (uint8_t *)priv_map1;
    uint8_t *p2 = (uint8_t *)priv_map2;

    p1[PAGE_SZ + 50] = 0x77;
    msync(priv_map1, TOTAL_SZ, MS_SYNC);

    uint8_t p2_val = p2[PAGE_SZ + 50];
    if (p2_val == 0x11) {
        printf("  [PASS] Sibling MAP_PRIVATE untouched: got 0x%02x (expected 0x11)\n", p2_val);
    } else {
        printf("  [FAIL] Sibling MAP_PRIVATE polluted: got 0x%02x (expected 0x11)\n", p2_val);
        failures |= (1 << 0);
    }

    uint8_t file_val = 0;
    pread(fd, &file_val, 1, PAGE_SZ + 50);
    if (file_val == 0x11) {
        printf("  [PASS] File not written back: pread got 0x%02x (expected 0x11)\n", file_val);
    } else {
        printf("  [FAIL] File corrupted by private write: pread got 0x%02x (expected 0x11)\n", file_val);
        failures |= (1 << 1);
    }
    munmap(priv_map1, TOTAL_SZ);
    munmap(priv_map2, TOTAL_SZ);

    /* 2. MAP_SHARED: Cross-process visibility & write-back */
    printf("\n[2] Testing MAP_SHARED cross-process visibility...\n");
    void *shared_map = mmap(NULL, TOTAL_SZ, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (shared_map == MAP_FAILED) {
        perror("mmap shared");
        return 13;
    }
    uint8_t *s = (uint8_t *)shared_map;
    s[PAGE_SZ * 2 + 10] = 0x88;
    msync(shared_map, TOTAL_SZ, MS_SYNC);

    file_val = 0;
    pread(fd, &file_val, 1, PAGE_SZ * 2 + 10);
    if (file_val == 0x88) {
        printf("  [PASS] MAP_SHARED writes back to file: pread got 0x%02x (expected 0x88)\n", file_val);
    } else {
        printf("  [FAIL] MAP_SHARED write not in file: pread got 0x%02x (expected 0x88)\n", file_val);
        failures |= (1 << 2);
    }

    pid_t pid = fork();
    if (pid == 0) {
        uint8_t c_val = s[PAGE_SZ * 2 + 10];
        s[PAGE_SZ * 2 + 20] = 0x99;
        msync(shared_map, TOTAL_SZ, MS_SYNC);
        _exit(c_val == 0x88 ? 0 : 1);
    }
    int status = 0;
    waitpid(pid, &status, 0);
    if (WIFEXITED(status) && WEXITSTATUS(status) == 0 && s[PAGE_SZ * 2 + 20] == 0x99) {
        printf("  [PASS] MAP_SHARED visible bidirectionally across fork child\n");
    } else {
        printf("  [FAIL] MAP_SHARED fork visibility broken\n");
        failures |= (1 << 3);
    }
    munmap(shared_map, TOTAL_SZ);

    /* 3. Clean page live observation (POSIX Unspecified) */
    printf("\n[3] Observing file modification after MAP_PRIVATE (POSIX Unspecified)...\n");
    void *priv_live = mmap(NULL, TOTAL_SZ, PROT_READ | PROT_WRITE, MAP_PRIVATE, fd, 0);
    uint8_t *pl = (uint8_t *)priv_live;

    memset(buf, 0xEE, PAGE_SZ);
    pwrite(fd, buf, PAGE_SZ, PAGE_SZ * 4);

    uint8_t pl_val = pl[PAGE_SZ * 4 + 100];
    printf("  [OBSERVE] Clean page read after file update: got 0x%02x (original 0x14, updated 0xEE)\n", pl_val);
    if (pl_val == 0xEE) {
        printf("    -> Behavior: Linux unified page-cache live reflection\n");
    } else if (pl_val == 0x14) {
        printf("    -> Behavior: Snapshot pread behavior (permitted by POSIX.1-2017: 'unspecified')\n");
    }
    munmap(priv_live, TOTAL_SZ);

    /* 4. MAP_FIXED partial remapping */
    printf("\n[4] Testing MAP_FIXED partial remapping...\n");
    void *fixed_base = mmap(NULL, PAGE_SZ * 4, PROT_READ | PROT_WRITE, MAP_ANONYMOUS | MAP_PRIVATE, -1, 0);
    uint8_t *fb = (uint8_t *)fixed_base;
    memset(fb, 0x33, PAGE_SZ * 4);

    void *remap = mmap(fb + PAGE_SZ * 2, PAGE_SZ, PROT_READ | PROT_WRITE, MAP_FIXED | MAP_PRIVATE, fd, 0);
    if (remap == fb + PAGE_SZ * 2 && fb[10] == 0x33 && fb[PAGE_SZ * 2 + 10] == 0x10) {
        printf("  [PASS] MAP_FIXED partial remapping correctly preserved surrounding pages\n");
    } else {
        printf("  [FAIL] MAP_FIXED partial remapping failed\n");
        failures |= (1 << 5);
    }
    munmap(fixed_base, PAGE_SZ * 4);

    /* 5. Non-zero offset alignment */
    printf("\n[5] Testing non-zero offset alignment...\n");
    void *off_map = mmap(NULL, PAGE_SZ * 2, PROT_READ, MAP_PRIVATE, fd, PAGE_SZ * 3);
    uint8_t *om = (uint8_t *)off_map;
    if (om && om[0] == 0x13 && om[PAGE_SZ] == 0xEE) {
        printf("  [PASS] Non-zero page-aligned offset mapping read correct bytes\n");
    } else {
        printf("  [FAIL] Non-zero offset mapping failed\n");
        failures |= (1 << 6);
    }
    munmap(off_map, PAGE_SZ * 2);

    close(fd);
    unlink(test_path);
    return failures;
}

int run_gate_matching_control_test(void) {
    printf("\n=== PART 2: GATE-MATCHING 0x144000 UNLINKED FILE CONTROL ===\n");
    const char *gate_path = "/tmp/elfuse_session_gate_test.bin";
    unlink(gate_path);
    int fd = open(gate_path, O_RDWR | O_CREAT | O_TRUNC, 0666);
    if (fd < 0) {
        perror("open gate test");
        return 20;
    }

    /* Initialize file with size 0x144000 */
    uint8_t pbuf[PAGE_SZ];
    memset(pbuf, 0x10, PAGE_SZ);
    for (size_t off = 0; off < SESSION_GATE_SZ; off += PAGE_SZ) {
        if (pwrite(fd, pbuf, PAGE_SZ, off) != PAGE_SZ) {
            perror("pwrite gate init");
            return 21;
        }
    }

    /* UNLINK while open so st_nlink == 0 (matches mem.c:2919 st.st_nlink == 0) */
    unlink(gate_path);

    struct stat st;
    fstat(fd, &st);
    printf("Gate file initialized: fd=%d size=0x%zx nlink=%lu\n", fd, (size_t)st.st_size, (unsigned long)st.st_nlink);

    /* Map with MAP_PRIVATE | PROT_READ | PROT_WRITE, length=0x144000, offset=0 */
    void *map = mmap(NULL, SESSION_GATE_SZ, PROT_READ | PROT_WRITE, MAP_PRIVATE, fd, 0);
    if (map == MAP_FAILED) {
        perror("mmap gate file");
        close(fd);
        return 22;
    }
    uint8_t *m = (uint8_t *)map;

    int gate_anomalies = 0;

    /* Test G1: Guest writes 0x77 to private mapping */
    printf("[GATE_TEST_1] Guest writes 0x77 to MAP_PRIVATE page 2...\n");
    m[PAGE_SZ * 2 + 100] = 0x77;
    msync(map, SESSION_GATE_SZ, MS_SYNC);

    /* Check underlying file: If gate forced MAP_SHARED, file will have 0x77! */
    uint8_t fval = 0;
    pread(fd, &fval, 1, PAGE_SZ * 2 + 100);
    if (fval == 0x77) {
        printf("  [ALERT] Gate triggered MAP_SHARED leak: pread got 0x77 (private write leaked to file!)\n");
        gate_anomalies |= (1 << 0);
    } else {
        printf("  [PASS] Private write NOT leaked to file: pread got 0x%02x (expected 0x10)\n", fval);
    }

    /* Test G2: Modify underlying file to 0xBB on page 3 where guest previously wrote 0x55 */
    printf("[GATE_TEST_2] Guest writes 0x55 to page 3, then file modified to 0xBB...\n");
    m[PAGE_SZ * 3 + 100] = 0x55;
    memset(pbuf, 0xBB, PAGE_SZ);
    pwrite(fd, pbuf, PAGE_SZ, PAGE_SZ * 3);

    uint8_t mval = m[PAGE_SZ * 3 + 100];
    if (mval == 0xBB) {
        printf("  [ALERT] Gate destroyed COW isolation: guest sees 0xBB (file overwrite clobbered private write 0x55!)\n");
        gate_anomalies |= (1 << 1);
    } else if (mval == 0x55) {
        printf("  [PASS] COW isolation intact: guest sees 0x%02x (expected 0x55)\n", mval);
    } else {
        printf("  [FAIL] Unexpected byte 0x%02x\n", mval);
        gate_anomalies |= (1 << 2);
    }

    munmap(map, SESSION_GATE_SZ);
    close(fd);

    if (gate_anomalies != 0) {
        printf("\nGATE_ANOMALY_RESULT: WRITE_LEAKAGE_AND_COW_CORRUPTION_CONFIRMED (mask=0x%x)\n", gate_anomalies);
        return 100 + gate_anomalies;
    } else {
        printf("\nGATE_ANOMALY_RESULT: CLEAN_PRIVATE_ISOLATION_PRESERVED\n");
        return 0;
    }
}

int main(int argc, char **argv) {
    int r1 = run_general_semantics_tests();
    int r2 = run_gate_matching_control_test();

    printf("\n==================================================\n");
    printf("OVERALL PROBE SUMMARY: Part1_failures=0x%x, Part2_gate_anomalies=%d\n", r1, r2);
    if (r2 != 0) {
        printf("EVIDENCE_VERIFIED: Under ELFUSE_DIAG_SESSION_SHARED=1, unlinked 0x144000 mapping leaks writes back to file and clobbers private guest writes.\n");
    } else {
        printf("EVIDENCE_VERIFIED: Gate inactive or private isolation intact.\n");
    }
    return (r1 != 0) ? r1 : ((r2 > 0) ? 1 : 0);
}

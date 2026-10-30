#define _GNU_SOURCE
#include <sys/mman.h>
#include <sys/wait.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <stdint.h>

int main(void) {
    write(1, "TEST_FORK_COW_START\n", 21);
    size_t sz = 0x70000;
    void *p = mmap(NULL, sz, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (p == MAP_FAILED) {
        write(2, "MMAP_FAILED\n", 12);
        return 1;
    }

    volatile uint32_t *word_at_target = (volatile uint32_t *)((uint8_t *)p + 0x2f440);
    volatile uint32_t *word_at_other  = (volatile uint32_t *)((uint8_t *)p + 0x1000);

    // Parent initializes both words to 0
    *word_at_target = 0;
    *word_at_other = 0;

    pid_t pid = fork();
    if (pid < 0) {
        write(2, "FORK_FAILED\n", 12);
        return 2;
    }

    if (pid == 0) {
        // Child process: verify child initially sees 0
        if (*word_at_target != 0 || *word_at_other != 0) {
            _exit(10);
        }
        // Child mutates the private memory: sets word_at_target to 1 (like pthread_once initializing)
        // and word_at_other to 0xdeadbeef
        *word_at_target = 1;
        *word_at_other = 0xdeadbeef;
        _exit(0);
    }

    // Parent waits for child to completely exit
    int status = 0;
    pid_t waited = waitpid(pid, &status, 0);
    if (waited != pid || !WIFEXITED(status) || WEXITSTATUS(status) != 0) {
        char buf[64];
        int len = snprintf(buf, sizeof(buf), "CHILD_FAIL_OR_CRASH: status=%d\n", status);
        write(2, buf, len);
        return 3;
    }

    // Parent reads back the memory:
    // Under proper POSIX/Linux MAP_PRIVATE semantics (COW), child's write MUST NOT affect parent.
    // Parent must see *word_at_target == 0 and *word_at_other == 0.
    // If elfuse shares anonymous private memory across fork (e.g. via session-shared alias or COW gap),
    // parent will see the child's written values (*word_at_target == 1)!
    char report[128];
    int rlen = snprintf(report, sizeof(report), "PARENT_READ: target=0x%x other=0x%x\n", *word_at_target, *word_at_other);
    write(1, report, rlen);

    if (*word_at_target == 1) {
        write(1, "LEAK_DETECTED: child write leaked to parent (MAP_PRIVATE shared leak confirmed)\n", 80);
    } else if (*word_at_target == 0) {
        write(1, "ISOLATION_INTACT: parent sees 0 (COW isolation intact)\n", 55);
    } else {
        write(1, "UNEXPECTED_VALUE\n", 17);
    }

    munmap(p, sz);
    return 0;
}

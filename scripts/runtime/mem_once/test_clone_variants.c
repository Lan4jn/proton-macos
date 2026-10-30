#define _GNU_SOURCE
#include <sched.h>
#include <sys/mman.h>
#include <sys/wait.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <stdint.h>

static int child_func(void *arg) {
    volatile uint32_t *p = (volatile uint32_t *)arg;
    *p = 1;
    return 0;
}

int main(void) {
    write(1, "TEST_CLONE_START\n", 17);
    size_t sz = 0x70000;
    void *p = mmap(NULL, sz, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (p == MAP_FAILED) return 1;

    volatile uint32_t *target = (volatile uint32_t *)((uint8_t *)p + 0x2f440);
    *target = 0;

    // Allocate stack for clone
    void *stack = mmap(NULL, 0x10000, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    void *stack_top = (uint8_t *)stack + 0x10000;

    // Test A: clone with 0x1200011 (CLONE_CHILD_SETTID | CLONE_CHILD_CLEARTID | SIGCHLD) - exactly as seen in Wine id 729!
    int flags = 0x1200011;
    pid_t pid = clone(child_func, stack_top, flags, (void *)target);
    if (pid < 0) {
        write(2, "CLONE_FAIL\n", 11);
        return 2;
    }

    int status = 0;
    waitpid(pid, &status, 0);

    char buf[128];
    int len = snprintf(buf, sizeof(buf), "CLONE_FLAGS_0x1200011: parent sees target=0x%x\n", *target);
    write(1, buf, len);

    if (*target == 1) {
        write(1, "CLONE_0x1200011_LEAKED\n", 23);
    } else {
        write(1, "CLONE_0x1200011_ISOLATED\n", 25);
    }

    munmap(p, sz);
    munmap(stack, 0x10000);
    return 0;
}

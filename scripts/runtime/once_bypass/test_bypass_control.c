#define _GNU_SOURCE
#include <linux/futex.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

static uint32_t futex_word = 1;

int main(void) {
    write(1, "CONTROL_START\n", 14);
    write(1, "[WIN_ARM64_VK] Step 3: Calling vkCreateInstance(API=1.0)...\n", 60);

    // Call futex wait with val=1
    long ret = syscall(SYS_futex, &futex_word, FUTEX_WAIT | FUTEX_PRIVATE_FLAG, 1, NULL, NULL, 0);

    char buf[128];
    int len = snprintf(buf, sizeof(buf), "FUTEX_RET ret=%ld word=%u\n", ret, futex_word);
    write(1, buf, len);

    if (ret == 0 && futex_word == 2) {
        write(1, "CONTROL_BYPASS_OK\n", 19);
        return 0;
    } else {
        write(1, "CONTROL_NOT_BYPASSED\n", 22);
        return 1;
    }
}

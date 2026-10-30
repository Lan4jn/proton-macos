#define _GNU_SOURCE
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

static pthread_once_t once = PTHREAD_ONCE_INIT;
static int init_called = 0;

static void init_fn(void) {
    init_called = 1;
    write(1, "INIT_CALLED\n", 12);
}

int main(void) {
    write(1, "TEST_ONCE_START\n", 17);
    int rc = pthread_once(&once, init_fn);
    if (rc != 0) {
        write(2, "ONCE_FAIL\n", 10);
        return 1;
    }
    if (init_called != 1) {
        write(2, "INIT_NOT_CALLED\n", 17);
        return 2;
    }
    write(1, "TEST_ONCE_OK\n", 14);
    return 0;
}

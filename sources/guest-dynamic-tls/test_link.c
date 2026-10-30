#include <stdio.h>
#include <pthread.h>
#include <dlfcn.h>

void *worker(void *arg) {
    printf("Thread running!\n");
    return NULL;
}

int main(void) {
    printf("Main running!\n");
    pthread_t th;
    pthread_create(&th, NULL, worker, NULL);
    pthread_join(th, NULL);
    return 0;
}

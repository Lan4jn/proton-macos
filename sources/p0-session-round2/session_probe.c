#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

static void phase(const char *name, const char *token, long result, int err) {
    printf("{\"phase\":\"%s\",\"token\":\"%s\",\"pid\":%ld,\"ppid\":%ld,\"pgid\":%ld,\"sid\":%ld,\"result\":%ld,\"errno\":%d}\n",
           name, token, (long)getpid(), (long)getppid(), (long)getpgrp(), (long)getsid(0), result, err);
    fflush(stdout);
}
static int wait_ack(const char *dir, const char *name, const char *token) {
    char path[1024], buf[256];
    if (snprintf(path, sizeof path, "%s/%s.ack", dir, name) >= (int)sizeof path) return 0;
    struct timespec delay = {0, 10000000};
    for (int i=0; i<500; i++) {
        FILE *f=fopen(path,"r");
        if (f) { int ok=fgets(buf,sizeof buf,f) && strcmp(buf,token)==0; fclose(f); return ok; }
        nanosleep(&delay, NULL);
    }
    return 0;
}
int main(int argc, char **argv) {
    if (argc!=3 || strlen(argv[2])!=32 || strspn(argv[2],"0123456789abcdef")!=32) return 64;
    const char *dir=argv[1], *token=argv[2];
    phase("parent",token,0,0);
    pid_t pid=fork();
    if (pid<0) return 70;
    if (pid==0) {
        phase("pre",token,0,0);
        if (!wait_ack(dir,"pre",token)) _exit(71);
        errno=0; pid_t result=setsid(); int e=result<0 ? errno : 0;
        phase("post",token,(long)result,e);
        if (!wait_ack(dir,"post",token)) _exit(72);
        _exit(result<0 ? 73 : 0);
    }
    int status;
    if (waitpid(pid,&status,0)!=pid) return 74;
    phase("child_exit",token,WIFEXITED(status)?WEXITSTATUS(status):-1,0);
    return WIFEXITED(status)?WEXITSTATUS(status):75;
}

#define SIGCHLD 17
#define WNOHANG 1

static inline long sys_write(int fd, const void *buf, unsigned long count) {
    register long x8 __asm__("x8") = 64;
    register long x0 __asm__("x0") = fd;
    register long x1 __asm__("x1") = (long)buf;
    register long x2 __asm__("x2") = (long)count;
    __asm__ volatile("svc #0" : "+r"(x0) : "r"(x8), "r"(x1), "r"(x2) : "memory");
    return x0;
}

static inline long sys_clone(unsigned long flags, void *child_stack) {
    register long x8 __asm__("x8") = 220; // __NR_clone
    register long x0 __asm__("x0") = flags;
    register long x1 __asm__("x1") = (long)child_stack;
    register long x2 __asm__("x2") = 0;
    register long x3 __asm__("x3") = 0;
    register long x4 __asm__("x4") = 0;
    __asm__ volatile("svc #0" : "+r"(x0) : "r"(x8), "r"(x1), "r"(x2), "r"(x3), "r"(x4) : "memory");
    return x0;
}

static inline long sys_wait4(int pid, int *wstatus, int options, void *rusage) {
    register long x8 __asm__("x8") = 260; // __NR_wait4
    register long x0 __asm__("x0") = pid;
    register long x1 __asm__("x1") = (long)wstatus;
    register long x2 __asm__("x2") = options;
    register long x3 __asm__("x3") = (long)rusage;
    __asm__ volatile("svc #0" : "+r"(x0) : "r"(x8), "r"(x1), "r"(x2), "r"(x3) : "memory");
    return x0;
}

static inline void sys_exit(int code) {
    register long x8 __asm__("x8") = 93;
    register long x0 __asm__("x0") = code;
    __asm__ volatile("svc #0" : : "r"(x8), "r"(x0) : "memory");
    __builtin_unreachable();
}

void _start(void) {
    long pid = sys_clone(SIGCHLD, 0);
    if (pid < 0) {
        const char err[] = "clone failed\n";
        sys_write(2, err, sizeof(err) - 1);
        sys_exit(1);
    }
    if (pid == 0) {
        // Child
        const char c_msg[] = "Child process running\n";
        sys_write(1, c_msg, sizeof(c_msg) - 1);
        sys_exit(10);
    } else {
        // Parent
        int status = 0;
        long ret = sys_wait4(pid, &status, 0, 0);
        int exit_code = (status >> 8) & 0xff;
        if (exit_code == 10) {
            const char p_msg[] = "Parent reaped child exit code 10\n";
            sys_write(1, p_msg, sizeof(p_msg) - 1);
            sys_exit(0);
        } else {
            const char err[] = "Parent got wrong exit code\n";
            sys_write(2, err, sizeof(err) - 1);
            sys_exit(2);
        }
    }
}

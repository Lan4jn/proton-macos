// Test mmap + mprotect (JIT execution) under elfuse HVF
#define PROT_READ  1
#define PROT_WRITE 2
#define PROT_EXEC  4

#define MAP_SHARED    0x01
#define MAP_PRIVATE   0x02
#define MAP_ANONYMOUS 0x20

static inline long sys_write(int fd, const void *buf, unsigned long count) {
    register long x8 __asm__("x8") = 64;
    register long x0 __asm__("x0") = fd;
    register long x1 __asm__("x1") = (long)buf;
    register long x2 __asm__("x2") = (long)count;
    __asm__ volatile("svc #0" : "+r"(x0) : "r"(x8), "r"(x1), "r"(x2) : "memory");
    return x0;
}

static inline void *sys_mmap(void *addr, unsigned long length, int prot, int flags, int fd, long offset) {
    register long x8 __asm__("x8") = 222; // __NR_mmap
    register long x0 __asm__("x0") = (long)addr;
    register long x1 __asm__("x1") = (long)length;
    register long x2 __asm__("x2") = prot;
    register long x3 __asm__("x3") = flags;
    register long x4 __asm__("x4") = fd;
    register long x5 __asm__("x5") = offset;
    __asm__ volatile("svc #0" : "+r"(x0) : "r"(x8), "r"(x1), "r"(x2), "r"(x3), "r"(x4), "r"(x5) : "memory");
    return (void *)x0;
}

static inline long sys_mprotect(void *addr, unsigned long length, int prot) {
    register long x8 __asm__("x8") = 226; // __NR_mprotect
    register long x0 __asm__("x0") = (long)addr;
    register long x1 __asm__("x1") = (long)length;
    register long x2 __asm__("x2") = prot;
    __asm__ volatile("svc #0" : "+r"(x0) : "r"(x8), "r"(x1), "r"(x2) : "memory");
    return x0;
}

static inline void sys_exit(int code) {
    register long x8 __asm__("x8") = 93;
    register long x0 __asm__("x0") = code;
    __asm__ volatile("svc #0" : : "r"(x8), "r"(x0) : "memory");
    __builtin_unreachable();
}

void _start(void) {
    unsigned long page_size = 16384; // 16KB Apple page size or 4KB
    void *ptr = sys_mmap(0, page_size, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if ((long)ptr < 0 && (long)ptr > -4096) {
        const char err[] = "mmap failed\n";
        sys_write(2, err, sizeof(err) - 1);
        sys_exit(1);
    }

    // Write ARM64 code into mapped page:
    // mov w0, #77
    // ret
    unsigned int *code = (unsigned int *)ptr;
    code[0] = 0x528009a0; // mov w0, #77
    code[1] = 0xd65f03c0; // ret

    long prot_res = sys_mprotect(ptr, page_size, PROT_READ | PROT_EXEC);
    if (prot_res != 0) {
        const char err[] = "mprotect failed\n";
        sys_write(2, err, sizeof(err) - 1);
        sys_exit(2);
    }

    // Call JIT code
    int (*jit_fn)(void) = (int (*)(void))ptr;
    int res = jit_fn();

    if (res == 77) {
        const char msg[] = "mmap+JIT success: computed 77\n";
        sys_write(1, msg, sizeof(msg) - 1);
        sys_exit(0);
    } else {
        const char err[] = "mmap+JIT unexpected result\n";
        sys_write(2, err, sizeof(err) - 1);
        sys_exit(3);
    }
}

/*
 * mmap_probe.c - Freestanding AArch64 Linux probe for elfuse memory boundaries.
 * Probes the exact mmap behavior at:
 * 1) 0xfe00000000 len 4GiB (Below infra reserve: [0xfe00000000, 0xff00000000))
 * 2) 0xfeffff0000 len 4GiB (Wine's exact 4GiB range [0xfeffff0000, 0xffffff0000))
 * 3) 0xfeffff0000 len 64KiB (Wine's start boundary [0xfeffff0000, 0xff00000000))
 * 4) 0xff00000000 len 64KiB (Inside original Interpreter Base: [0xff00000000, 0xff00010000))
 * 5) 0x10000000000 len 64KiB (At guest_size: addr >= 1TiB)
 */

static inline long sc(long n, long a, long b, long c, long d, long e, long f) {
    register long x8 __asm__("x8") = n;
    register long x0 __asm__("x0") = a;
    register long x1 __asm__("x1") = b;
    register long x2 __asm__("x2") = c;
    register long x3 __asm__("x3") = d;
    register long x4 __asm__("x4") = e;
    register long x5 __asm__("x5") = f;
    __asm__ volatile("svc #0"
                     : "+r"(x0)
                     : "r"(x8), "r"(x1), "r"(x2), "r"(x3), "r"(x4), "r"(x5)
                     : "memory");
    return x0;
}

static void print_str(const char *s) {
    unsigned long len = 0;
    while (s[len]) len++;
    sc(64, 1, (long)s, len, 0, 0, 0); // sys_write(stdout, s, len)
}

static void print_hex(unsigned long v) {
    char buf[19];
    buf[0] = '0';
    buf[1] = 'x';
    for (int i = 15; i >= 0; i--) {
        int nib = (v >> (i * 4)) & 0xf;
        buf[17 - i] = (nib < 10) ? ('0' + nib) : ('a' + nib - 10);
    }
    buf[18] = '\0';
    print_str(buf);
}

static void print_dec(long v) {
    if (v < 0) {
        print_str("-");
        v = -v;
    }
    char buf[24];
    int idx = 0;
    if (v == 0) {
        buf[idx++] = '0';
    } else {
        char tmp[24];
        int tidx = 0;
        while (v > 0) {
            tmp[tidx++] = '0' + (v % 10);
            v /= 10;
        }
        while (tidx > 0) {
            buf[idx++] = tmp[--tidx];
        }
    }
    buf[idx] = '\0';
    print_str(buf);
}

void _start(void) {
    print_str("=== ELFUSE MMAP BOUNDARY PROBE (COMPREHENSIVE) ===\n");

    // Probe 1: 0xfe00000000, len 4GiB (0x100000000)
    // flags = MAP_PRIVATE(0x02) | MAP_ANON(0x20) | MAP_FIXED(0x10) = 0x32
    long ret1 = sc(222, 0xfe00000000ULL, 0x100000000ULL, 1, 0x32, -1, 0);
    print_str("Probe 1 [0xfe00000000, len 4GiB - Below Infra]: ret = ");
    if (ret1 < 0 && ret1 > -4096) {
        print_str("ERRNO ");
        print_dec(-ret1);
    } else {
        print_hex(ret1);
    }
    print_str("\n");

    // Probe 2: Wine's full 4GiB range: [0xfeffff0000, 0xffffff0000), len 4GiB (0x100000000)
    long ret2 = sc(222, 0xfeffff0000ULL, 0x100000000ULL, 1, 0x32, -1, 0);
    print_str("Probe 2 [0xfeffff0000, len 4GiB - Wine Full 4GiB]: ret = ");
    if (ret2 < 0 && ret2 > -4096) {
        print_str("ERRNO ");
        print_dec(-ret2);
    } else {
        print_hex(ret2);
    }
    print_str("\n");

    // Probe 3: Wine's start 64KiB chunk: [0xfeffff0000, 0xff00000000), len 64KiB (0x10000)
    long ret3 = sc(222, 0xfeffff0000ULL, 0x10000ULL, 1, 0x32, -1, 0);
    print_str("Probe 3 [0xfeffff0000, len 64KiB - Top of Infra Reserve]: ret = ");
    if (ret3 < 0 && ret3 > -4096) {
        print_str("ERRNO ");
        print_dec(-ret3);
    } else {
        print_hex(ret3);
    }
    print_str("\n");

    // Probe 4: Inside original ld.so interpreter region: [0xff00000000, 0xff00010000), len 64KiB
    long ret4 = sc(222, 0xff00000000ULL, 0x10000ULL, 1, 0x32, -1, 0);
    print_str("Probe 4 [0xff00000000, len 64KiB - Inside Interpreter Base]: ret = ");
    if (ret4 < 0 && ret4 > -4096) {
        print_str("ERRNO ");
        print_dec(-ret4);
    } else {
        print_hex(ret4);
    }
    print_str("\n");

    // Probe 5: Above guest_size: 0x10000000000 (1 TiB)
    long ret5 = sc(222, 0x10000000000ULL, 0x10000ULL, 1, 0x32, -1, 0);
    print_str("Probe 5 [0x10000000000, len 64KiB - High VA >= 1TiB]: ret = ");
    if (ret5 < 0 && ret5 > -4096) {
        print_str("ERRNO ");
        print_dec(-ret5);
    } else {
        print_hex(ret5);
    }
    print_str("\n");

    print_str("PROBE_COMPLETE\n");
    sc(94, 0, 0, 0, 0, 0, 0); // Always exit 0 after printing all probe outcomes
    __builtin_unreachable();
}

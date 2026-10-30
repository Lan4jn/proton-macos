#define _GNU_SOURCE
#include <dlfcn.h>
#include <execinfo.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

/* --- Allocation-free low-level I/O helpers (pure write(2), zero malloc) --- */

static void raw_write(const char *buf, size_t len)
{
    while (len > 0) {
        ssize_t ret = write(STDERR_FILENO, buf, len);
        if (ret <= 0)
            break;
        buf += ret;
        len -= (size_t)ret;
    }
}

static void raw_write_str(const char *s)
{
    if (!s) return;
    size_t len = 0;
    while (s[len]) len++;
    raw_write(s, len);
}

static void raw_write_hex64(uint64_t v)
{
    char buf[19];
    buf[0] = '0';
    buf[1] = 'x';
    for (int i = 15; i >= 0; i--) {
        int nib = (v >> (i * 4)) & 0xf;
        buf[17 - i] = (nib < 10) ? ('0' + nib) : ('a' + nib - 10);
    }
    buf[18] = '\0';
    raw_write(buf, 18);
}

/* --- Real function pointers --- */

typedef void (*cxa_throw_fn)(void *thrown_exception, void *tinfo, void (*dest)(void *));
typedef void (*throw_bad_alloc_fn)(void);

static cxa_throw_fn real_cxa_throw = NULL;
static throw_bad_alloc_fn real_throw_bad_alloc = NULL;

static __thread bool in_trace = false;

/* --- Resolution logic (non-fatal in constructor, deferred if C++ runtime not yet present) --- */

static cxa_throw_fn resolve_real_cxa_throw(void)
{
    raw_write_str("[PHASE_TRACE] RESOLVE_NEXT_TRY: __cxa_throw\n");
    cxa_throw_fn fn = (cxa_throw_fn)dlsym(RTLD_NEXT, "__cxa_throw");
    if (fn) {
        raw_write_str("[PHASE_TRACE] RESOLVE_NEXT_OK: __cxa_throw\n");
        return fn;
    }

    raw_write_str("[PHASE_TRACE] RESOLVE_NOLOAD_TRY: __cxa_throw\n");
    static const char *const candidates[] = {
        "libstdc++.so.6",
        "libstdc++.so",
        "libc++abi.so.1",
        "libc++.so.1",
        NULL
    };

    for (int i = 0; candidates[i] != NULL; i++) {
        void *h = dlopen(candidates[i], RTLD_LAZY | RTLD_NOLOAD);
        if (h) {
            fn = (cxa_throw_fn)dlsym(h, "__cxa_throw");
            dlclose(h);
            if (fn) {
                raw_write_str("[PHASE_TRACE] RESOLVE_NOLOAD_OK: __cxa_throw in ");
                raw_write_str(candidates[i]);
                raw_write_str("\n");
                return fn;
            }
        }
    }
    return NULL;
}

static throw_bad_alloc_fn resolve_real_throw_bad_alloc(void)
{
    raw_write_str("[PHASE_TRACE] RESOLVE_NEXT_TRY: _ZSt17__throw_bad_allocv\n");
    throw_bad_alloc_fn fn = (throw_bad_alloc_fn)dlsym(RTLD_NEXT, "_ZSt17__throw_bad_allocv");
    if (fn) {
        raw_write_str("[PHASE_TRACE] RESOLVE_NEXT_OK: _ZSt17__throw_bad_allocv\n");
        return fn;
    }

    raw_write_str("[PHASE_TRACE] RESOLVE_NOLOAD_TRY: _ZSt17__throw_bad_allocv\n");
    void *h = dlopen("libstdc++.so.6", RTLD_LAZY | RTLD_NOLOAD);
    if (h) {
        fn = (throw_bad_alloc_fn)dlsym(h, "_ZSt17__throw_bad_allocv");
        dlclose(h);
        if (fn) {
            raw_write_str("[PHASE_TRACE] RESOLVE_NOLOAD_OK: _ZSt17__throw_bad_allocv in libstdc++.so.6\n");
            return fn;
        }
    }
    return NULL;
}

/* --- Constructor: runs early at DSO load time --- */
static void badalloc_phase_init(void) __attribute__((constructor));
static void badalloc_phase_init(void)
{
    raw_write_str("[PHASE_TRACE] INIT_ENTER\n");

    real_cxa_throw = resolve_real_cxa_throw();
    real_throw_bad_alloc = resolve_real_throw_bad_alloc();

    if (!real_cxa_throw && !real_throw_bad_alloc) {
        raw_write_str("[PHASE_TRACE] INIT_RESOLVE_DEFERRED (no C++ runtime found yet in process)\n");
    }

    raw_write_str("[PHASE_TRACE] INIT_DONE\n");
}

/* --- Interposed __cxa_throw --- */
void __cxa_throw(void *thrown_exception, void *tinfo, void (*dest)(void *))
{
    /* 1. First instruction: pure allocation-free write of marker and raw caller PC */
    void *caller_pc = __builtin_return_address(0);
    raw_write_str("[PHASE_TRACE] THROW_ENTER | caller_pc: ");
    raw_write_hex64((uint64_t)caller_pc);
    raw_write_str(" | obj: ");
    raw_write_hex64((uint64_t)thrown_exception);
    raw_write_str(" | tinfo: ");
    raw_write_hex64((uint64_t)tinfo);
    raw_write_str(" | dest: ");
    raw_write_hex64((uint64_t)dest);
    raw_write_str("\n");

    /* 2. Resolve if deferred */
    if (!real_cxa_throw) {
        real_cxa_throw = resolve_real_cxa_throw();
        if (!real_cxa_throw) {
            raw_write_str("[PHASE_TRACE] THROW_RESOLVE_FAIL: unable to resolve real __cxa_throw\n");
            _exit(127);
        }
    }

    /* 3. Diagnostic backtrace under reentrancy guard */
    if (!in_trace) {
        in_trace = true;

        raw_write_str("[PHASE_TRACE] BACKTRACE_ENTER\n");
        void *frames[64];
        int nframes = backtrace(frames, 64);

        fprintf(stderr, "\n[BADALLOC_TRACE] === C++ EXCEPTION THROWN ===\n");
        fprintf(stderr, "[BADALLOC_TRACE] Caller PC: %p | Thrown Object: %p | TypeInfo Ptr: %p | Destructor: %p\n",
                caller_pc, thrown_exception, tinfo, (void *)dest);
        fprintf(stderr, "[BADALLOC_TRACE] Backtrace (%d frames):\n", nframes);

        for (int i = 0; i < nframes; i++) {
            void *addr = frames[i];
            Dl_info info;
            if (dladdr(addr, &info) && info.dli_fname) {
                uintptr_t base = (uintptr_t)info.dli_fbase;
                uintptr_t offset = (uintptr_t)addr - base;
                const char *sname = info.dli_sname ? info.dli_sname : "<unknown>";
                uintptr_t soff = info.dli_saddr ? ((uintptr_t)addr - (uintptr_t)info.dli_saddr) : 0;

                fprintf(stderr, "  [BADALLOC_TRACE] #%02d: %p in %s (+0x%lx) [%s+0x%lx]\n",
                        i, addr, info.dli_fname, (unsigned long)offset, sname, (unsigned long)soff);
            } else {
                fprintf(stderr, "  [BADALLOC_TRACE] #%02d: %p in <unknown module>\n", i, addr);
            }
        }
        fprintf(stderr, "[BADALLOC_TRACE] === END BADALLOC TRACE ===\n\n");
        fflush(stderr);

        raw_write_str("[PHASE_TRACE] BACKTRACE_DONE\n");
        in_trace = false;
    }

    /* 4. Forwarding phase */
    raw_write_str("[PHASE_TRACE] FORWARD_ENTER: calling real __cxa_throw\n");
    real_cxa_throw(thrown_exception, tinfo, dest);

    __builtin_unreachable();
}

/* --- Interposed std::__throw_bad_alloc() (_ZSt17__throw_bad_allocv) --- */
void _ZSt17__throw_bad_allocv(void)
{
    /* 1. First instruction: pure allocation-free marker with raw caller PC */
    void *caller_pc = __builtin_return_address(0);
    raw_write_str("[PHASE_TRACE] THROW_BAD_ALLOC_HELPER_ENTER | caller_pc: ");
    raw_write_hex64((uint64_t)caller_pc);
    raw_write_str("\n");

    /* 2. Resolve if deferred */
    if (!real_throw_bad_alloc) {
        real_throw_bad_alloc = resolve_real_throw_bad_alloc();
        if (!real_throw_bad_alloc) {
            raw_write_str("[PHASE_TRACE] HELPER_RESOLVE_FAIL: unable to resolve real _ZSt17__throw_bad_allocv\n");
            _exit(127);
        }
    }

    /* 3. Diagnostic backtrace */
    if (!in_trace) {
        in_trace = true;
        raw_write_str("[PHASE_TRACE] HELPER_BACKTRACE_ENTER\n");

        void *frames[64];
        int nframes = backtrace(frames, 64);

        fprintf(stderr, "\n[BADALLOC_TRACE] === STD::__THROW_BAD_ALLOC() INVOKED ===\n");
        fprintf(stderr, "[BADALLOC_TRACE] Caller PC: %p\n", caller_pc);
        fprintf(stderr, "[BADALLOC_TRACE] Backtrace (%d frames):\n", nframes);

        for (int i = 0; i < nframes; i++) {
            void *addr = frames[i];
            Dl_info info;
            if (dladdr(addr, &info) && info.dli_fname) {
                uintptr_t base = (uintptr_t)info.dli_fbase;
                uintptr_t offset = (uintptr_t)addr - base;
                const char *sname = info.dli_sname ? info.dli_sname : "<unknown>";
                uintptr_t soff = info.dli_saddr ? ((uintptr_t)addr - (uintptr_t)info.dli_saddr) : 0;

                fprintf(stderr, "  [BADALLOC_TRACE] #%02d: %p in %s (+0x%lx) [%s+0x%lx]\n",
                        i, addr, info.dli_fname, (unsigned long)offset, sname, (unsigned long)soff);
            } else {
                fprintf(stderr, "  [BADALLOC_TRACE] #%02d: %p in <unknown module>\n", i, addr);
            }
        }
        fprintf(stderr, "[BADALLOC_TRACE] === END BADALLOC TRACE ===\n\n");
        fflush(stderr);

        raw_write_str("[PHASE_TRACE] HELPER_BACKTRACE_DONE\n");
        in_trace = false;
    }

    /* 4. Forwarding to real helper */
    raw_write_str("[PHASE_TRACE] HELPER_FORWARD_ENTER: calling real _ZSt17__throw_bad_allocv\n");
    real_throw_bad_alloc();

    __builtin_unreachable();
}

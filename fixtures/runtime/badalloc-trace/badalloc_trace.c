#define _GNU_SOURCE
#include <dlfcn.h>
#include <execinfo.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

typedef void (*cxa_throw_fn)(void *thrown_exception, void *tinfo, void (*dest)(void *));
static cxa_throw_fn real_cxa_throw = NULL;
static __thread bool in_trace = false;

static cxa_throw_fn resolve_real_cxa_throw(void)
{
    cxa_throw_fn fn = (cxa_throw_fn)dlsym(RTLD_NEXT, "__cxa_throw");
    if (fn)
        return fn;

    /* Fallback for RTLD_LOCAL DSOs: query already-loaded C++ runtimes without modifying namespace */
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
            if (fn)
                return fn;
        }
    }
    return NULL;
}

static void init_real_cxa_throw(void) __attribute__((constructor));
static void init_real_cxa_throw(void)
{
    if (!real_cxa_throw) {
        real_cxa_throw = resolve_real_cxa_throw();
    }
}

/* Intercept __cxa_throw (Itanium C++ ABI) */
void __cxa_throw(void *thrown_exception, void *tinfo, void (*dest)(void *))
{
    if (!real_cxa_throw) {
        real_cxa_throw = resolve_real_cxa_throw();
        if (!real_cxa_throw) {
            const char err[] = "[BADALLOC_TRACE] FATAL: failed to resolve real __cxa_throw (RTLD_NEXT and RTLD_NOLOAD exhausted)\n";
            (void)write(STDERR_FILENO, err, sizeof(err) - 1);
            _exit(127);
        }
    }

    if (!in_trace) {
        in_trace = true;

        fprintf(stderr, "\n[BADALLOC_TRACE] === C++ EXCEPTION THROWN ===\n");
        fprintf(stderr, "[BADALLOC_TRACE] Thrown Object: %p | TypeInfo Ptr: %p | Destructor: %p\n",
                thrown_exception, tinfo, (void *)dest);

        void *frames[64];
        int nframes = backtrace(frames, 64);
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

        fprintf(stderr, "[BADALLOC_TRACE] Forwarding to real __cxa_throw...\n");
        fprintf(stderr, "[BADALLOC_TRACE] === END BADALLOC TRACE ===\n\n");
        fflush(stderr);

        in_trace = false;
    }

    /* Forward original arguments verbatim to real runtime */
    real_cxa_throw(thrown_exception, tinfo, dest);

    /* __cxa_throw never returns */
    __builtin_unreachable();
}

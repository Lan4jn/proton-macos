/*
 * fixtures/runtime/badalloc-trace/dlopen_main.c
 *
 * Pure C main executable that links ONLY against libdl and libc.
 * Contains no C++ code and no link-time dependency on libstdc++.
 * Loads plugin_cpp.so via dlopen(..., RTLD_LAZY | RTLD_LOCAL).
 */

#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

typedef int (*run_fn_t)(void);

int main(int argc, char **argv)
{
    const char *plugin_path = (argc > 1) ? argv[1] : "./plugin_cpp.so";

    void *h = dlopen(plugin_path, RTLD_LAZY | RTLD_LOCAL);
    if (!h) {
        fprintf(stderr, "dlopen failed: %s\n", dlerror());
        return 10;
    }

    run_fn_t run_fn = (run_fn_t)dlsym(h, "run_plugin_throw_catch");
    if (!run_fn) {
        fprintf(stderr, "dlsym failed: %s\n", dlerror());
        dlclose(h);
        return 11;
    }

    int res = run_fn();
    if (res == 42) {
        printf("DLOPEN_PLUGIN_42_OK\n");
        dlclose(h);
        return 0;
    }

    fprintf(stderr, "ERROR: run_plugin_throw_catch returned %d (expected 42)\n", res);
    dlclose(h);
    return 12;
}

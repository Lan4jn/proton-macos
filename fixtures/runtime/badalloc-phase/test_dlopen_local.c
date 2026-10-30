/*
 * fixtures/runtime/badalloc-phase/test_dlopen_local.c
 *
 * Case 3: Pure C main that loads C++ DSO via dlopen(..., RTLD_LOCAL).
 * Verifies that constructor handles delayed C++ runtime and resolve works upon throw.
 */

#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>

typedef int (*plugin_fn_t)(void);

int main(int argc, char **argv)
{
    const char *path = (argc > 1) ? argv[1] : "./plugin_cpp.so";
    void *h = dlopen(path, RTLD_LAZY | RTLD_LOCAL);
    if (!h) {
        fprintf(stderr, "dlopen failed: %s\n", dlerror());
        return 10;
    }

    plugin_fn_t fn = (plugin_fn_t)dlsym(h, "run_plugin_throw");
    if (!fn) {
        fprintf(stderr, "dlsym failed: %s\n", dlerror());
        dlclose(h);
        return 11;
    }

    int ret = fn();
    dlclose(h);

    if (ret == 42) {
        printf("CASE3_DLOPEN_OK\n");
        return 0;
    }
    return 12;
}

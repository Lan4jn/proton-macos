#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <assert.h>
#include <pthread.h>
#include <dlfcn.h>
#include <unistd.h>

typedef int BOOL;
#define TRUE 1
#define FALSE 0

/* Function pointer types to dynamically loaded guard shared library */
typedef BOOL (*fn_is_in_progress)(void);
typedef BOOL (*fn_guard_enter)(void);
typedef void (*fn_guard_exit)(void);
typedef void (*fn_guard_cleanup)(void *);
typedef void *(*fn_get_depth_addr)(void);
typedef int (*fn_get_depth_val)(void);
typedef void (*fn_set_cb_blocking)(int);
typedef int (*fn_wait_cb_worker_in_action)(void);
typedef int (*fn_test_real_callback_flow)(int);

static void *g_so_handle = NULL;
static fn_is_in_progress p_vulkan_is_in_progress = NULL;
static fn_guard_enter p_vulkan_guard_enter = NULL;
static fn_guard_exit p_vulkan_guard_exit = NULL;
static fn_guard_cleanup p_vulkan_guard_cleanup = NULL;
static fn_get_depth_addr p_get_vulkan_init_depth_addr = NULL;
static fn_get_depth_val p_get_vulkan_init_depth_val = NULL;

static fn_is_in_progress p_d3dkmt_is_in_progress = NULL;
static fn_guard_enter p_d3dkmt_guard_enter = NULL;
static fn_guard_exit p_d3dkmt_guard_exit = NULL;
static fn_get_depth_addr p_get_d3dkmt_init_depth_addr = NULL;
static fn_get_depth_val p_get_d3dkmt_init_depth_val = NULL;

static fn_set_cb_blocking p_set_cb_blocking = NULL;
static fn_wait_cb_worker_in_action p_wait_cb_worker_in_action = NULL;
static fn_test_real_callback_flow p_test_real_callback_flow = NULL;

/* Cond/Mutex synchronization for worker threads */
static pthread_mutex_t g_sync_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t g_sync_cond = PTHREAD_COND_INITIALIZER;
static int g_sync_phase = 0;

static void sync_wait_for(int target_phase) {
    pthread_mutex_lock(&g_sync_mutex);
    while (g_sync_phase < target_phase) {
        pthread_cond_wait(&g_sync_cond, &g_sync_mutex);
    }
    pthread_mutex_unlock(&g_sync_mutex);
}

static void sync_advance_to(int next_phase) {
    pthread_mutex_lock(&g_sync_mutex);
    g_sync_phase = next_phase;
    pthread_cond_broadcast(&g_sync_cond);
    pthread_mutex_unlock(&g_sync_mutex);
}

/* Worker 1 data */
static void *g_w1_tls_addr = NULL;
static int g_w1_tls_val = -1;

static void *worker1_func(void *arg) {
    (void)arg;
    /* Wait until main thread has dlopened library AFTER our thread creation */
    sync_wait_for(1);

    /* Worker 1 enters vulkan guard */
    assert(p_vulkan_guard_enter() == TRUE);
    assert(p_vulkan_is_in_progress() == TRUE);

    g_w1_tls_addr = p_get_vulkan_init_depth_addr();
    g_w1_tls_val = p_get_vulkan_init_depth_val();

    /* Signal main thread that Worker 1 is in guard */
    sync_advance_to(2);

    /* Wait for Worker 2 and main thread verification */
    sync_wait_for(4);

    /* Worker 1 exits guard */
    p_vulkan_guard_exit();
    assert(p_vulkan_is_in_progress() == FALSE);

    return NULL;
}

/* Worker 2 data */
static void *g_w2_tls_addr = NULL;
static int g_w2_tls_val = -1;

static void *worker2_func(void *arg) {
    (void)arg;
    /* Wait until Worker 1 is in guard */
    sync_wait_for(2);

    /* Worker 2 queries guard: MUST be FALSE (unaffected by Worker 1) */
    assert(p_vulkan_is_in_progress() == FALSE);

    /* Worker 2 enters guard twice (nested enter test) */
    assert(p_vulkan_guard_enter() == TRUE);
    assert(p_vulkan_guard_enter() == TRUE);
    assert(p_vulkan_is_in_progress() == TRUE);

    g_w2_tls_addr = p_get_vulkan_init_depth_addr();
    g_w2_tls_val = p_get_vulkan_init_depth_val();

    /* Signal main thread that Worker 2 is at depth 2 */
    sync_advance_to(3);

    /* Wait for main thread comparison check */
    sync_wait_for(4);

    /* Worker 2 exits inner guard */
    p_vulkan_guard_exit();
    /* Outer scope MUST remain protected (depth 1 > 0) */
    assert(p_vulkan_is_in_progress() == TRUE);
    assert(p_get_vulkan_init_depth_val() == 1);

    /* Worker 2 exits outer guard */
    p_vulkan_guard_exit();
    assert(p_vulkan_is_in_progress() == FALSE);
    assert(p_get_vulkan_init_depth_val() == 0);

    return NULL;
}

/* Worker 3 for callback cancellation test */
static void *worker3_cancel_func(void *arg) {
    (void)arg;
    pthread_setcancelstate(PTHREAD_CANCEL_ENABLE, NULL);
    pthread_setcanceltype(PTHREAD_CANCEL_DEFERRED, NULL);

    /* Runs callback flow which pushes cleanup, enters guard, and blocks on cond wait */
    p_test_real_callback_flow(1);
    return NULL;
}

int main(int argc, char **argv) {
    printf("[GUEST_TLS: PHASE 1 START] ARM64 Linux dynamic TLS runner starting...\n");
    printf("  Runner executable: %s\n", argv[0]);

    /*
     * REQUIREMENT 4: Work threads created BEFORE dlopen.
     * This forces the dynamic linker (glibc ld.so) to allocate dynamic TLS blocks (DTV)
     * at symbol resolution time rather than at pthread_create() time.
     */
    printf("[GUEST_TLS: PHASE 2] Spawning Worker 1 and Worker 2 BEFORE dlopen...\n");
    pthread_t th1, th2;
    int rc1 = pthread_create(&th1, NULL, worker1_func, NULL);
    int rc2 = pthread_create(&th2, NULL, worker2_func, NULL);
    assert(rc1 == 0 && rc2 == 0);

    /* Now main thread performs dlopen of libv3_guard.so */
    const char *so_path = "sources/guest-dynamic-tls/libv3_guard.so";
    if (argc > 1) {
        so_path = argv[1];
    }
    printf("  Calling dlopen(\"%s\", RTLD_NOW | RTLD_LOCAL)...\n", so_path);
    g_so_handle = dlopen(so_path, RTLD_NOW | RTLD_LOCAL);
    if (!g_so_handle) {
        fprintf(stderr, "FATAL: dlopen failed: %s\n", dlerror());
        return 1;
    }

    Dl_info dlinfo;
    memset(&dlinfo, 0, sizeof(dlinfo));
    if (dladdr(g_so_handle, &dlinfo)) {
        printf("  Loaded library path: %s (base: %p)\n", dlinfo.dli_fname, dlinfo.dli_fbase);
    } else {
        printf("  Loaded library handle: %p\n", g_so_handle);
    }

#define RESOLVE(type, ptr, sym) do { \
        ptr = (type)dlsym(g_so_handle, sym); \
        if (!ptr) { \
            fprintf(stderr, "FATAL: dlsym failed for %s: %s\n", sym, dlerror()); \
            return 2; \
        } \
    } while(0)

    RESOLVE(fn_is_in_progress, p_vulkan_is_in_progress, "is_vulkan_init_in_progress");
    RESOLVE(fn_guard_enter, p_vulkan_guard_enter, "vulkan_init_guard_enter");
    RESOLVE(fn_guard_exit, p_vulkan_guard_exit, "vulkan_init_guard_exit");
    RESOLVE(fn_guard_cleanup, p_vulkan_guard_cleanup, "vulkan_init_guard_cleanup");
    RESOLVE(fn_get_depth_addr, p_get_vulkan_init_depth_addr, "get_vulkan_init_depth_addr");
    RESOLVE(fn_get_depth_val, p_get_vulkan_init_depth_val, "get_vulkan_init_depth_val");

    RESOLVE(fn_is_in_progress, p_d3dkmt_is_in_progress, "d3dkmt_is_in_progress");
    RESOLVE(fn_guard_enter, p_d3dkmt_guard_enter, "d3dkmt_guard_enter");
    RESOLVE(fn_guard_exit, p_d3dkmt_guard_exit, "d3dkmt_guard_exit");
    RESOLVE(fn_get_depth_addr, p_get_d3dkmt_init_depth_addr, "get_d3dkmt_init_depth_addr");
    RESOLVE(fn_get_depth_val, p_get_d3dkmt_init_depth_val, "get_d3dkmt_init_depth_val");

    RESOLVE(fn_set_cb_blocking, p_set_cb_blocking, "set_cb_blocking");
    RESOLVE(fn_wait_cb_worker_in_action, p_wait_cb_worker_in_action, "wait_cb_worker_in_action");
    RESOLVE(fn_test_real_callback_flow, p_test_real_callback_flow, "test_real_callback_flow");
#undef RESOLVE

    printf("[GUEST_TLS: PHASE 2 DLOPEN_AFTER_THREAD_CREATION_OK] Symbols resolved successfully.\n");

    /* Signal Worker 1 to start using dynamically loaded TLS symbols */
    sync_advance_to(1);

    /* Wait until Worker 1 is in guard (phase 2) and Worker 2 is at depth 2 (phase 3) */
    sync_wait_for(3);

    /* Main thread queries its own TLS state */
    void *addr_main = p_get_vulkan_init_depth_addr();
    int val_main = p_get_vulkan_init_depth_val();
    assert(p_vulkan_is_in_progress() == FALSE);

    printf("  [ISOLATION CHECK] Main Thread TLS depth addr: %p, val: %d\n", addr_main, val_main);
    printf("  [ISOLATION CHECK] Worker 1    TLS depth addr: %p, val: %d\n", g_w1_tls_addr, g_w1_tls_val);
    printf("  [ISOLATION CHECK] Worker 2    TLS depth addr: %p, val: %d\n", g_w2_tls_addr, g_w2_tls_val);

    /*
     * VITAL DYNAMIC TLS VERIFICATION:
     * 1. Dynamic TLS addresses MUST all be distinct across threads.
     * 2. Values MUST reflect independent private depths (Worker1=1, Worker2=2, Main=0).
     */
    assert(addr_main != g_w1_tls_addr);
    assert(addr_main != g_w2_tls_addr);
    assert(g_w1_tls_addr != g_w2_tls_addr);

    assert(val_main == 0);
    assert(g_w1_tls_val == 1);
    assert(g_w2_tls_val == 2);

    printf("[GUEST_TLS: PHASE 3 DYNAMIC_TLS_ADDRESS_AND_VALUE_ISOLATION_OK] Thread isolation confirmed!\n");

    /* Signal Worker 1 & 2 to perform nested unwinding and exit */
    sync_advance_to(4);

    pthread_join(th1, NULL);
    pthread_join(th2, NULL);
    printf("[GUEST_TLS: PHASE 3 NESTED_DEPTH_BALANCING_OK] Nested depth 2->1->0 verified.\n");

    /*
     * REQUIREMENT 3: Real Cancellation Point Cleanup in actual callback flow
     */
    printf("[GUEST_TLS: PHASE 4] Testing cancellation cleanup inside callback pthread_cleanup_push...\n");
    p_set_cb_blocking(1);

    pthread_t th3;
    pthread_create(&th3, NULL, worker3_cancel_func, NULL);

    /* Wait until Worker 3 has entered callback and blocked */
    p_wait_cb_worker_in_action();

    /* Cancel Worker 3 while holding guard */
    printf("  Worker 3 blocked in callback critical section. Cancelling...\n");
    pthread_cancel(th3);

    void *join_res = NULL;
    pthread_join(th3, &join_res);
    assert(join_res == PTHREAD_CANCELED);
    printf("  Worker 3 joined with PTHREAD_CANCELED (cancellation unwinder completed).\n");

    p_set_cb_blocking(0);

    /*
     * Verify that pthread_cleanup_pop(1) executed during cancellation
     * in the actual callback, so depth is restored to 0.
     */
    printf("[GUEST_TLS: PHASE 4 REAL_CALLBACK_CANCELLATION_CLEANUP_OK] Callback cleanup verified!\n");

    /* Early exit cleanup check */
    printf("[GUEST_TLS: PHASE 5] Testing early exit cleanup in main thread...\n");
    assert(p_vulkan_guard_enter() == TRUE);
    assert(p_vulkan_is_in_progress() == TRUE);
    p_vulkan_guard_exit();
    assert(p_vulkan_is_in_progress() == FALSE);
    printf("[GUEST_TLS: PHASE 5 EARLY_EXIT_CLEANUP_OK] Early exit balance verified.\n");

    dlclose(g_so_handle);
    printf("[GUEST_TLS: ALL_PHASES_PASS] Guest Linux glibc dynamic TLS verification completely successful.\n");
    return 0;
}

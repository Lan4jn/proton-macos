/*
 * test_guard_v3.c: Native unit test suite for Wine win32u guard v3.
 * Directly includes automatically extracted guard definitions and real callback control flow
 * from patched vulkan.c and d3dkmt.c.
 *
 * Scenarios verified:
 * 1. Same-thread State Balance (enter -> inside -> exit -> outside)
 * 2. Two-thread Isolation (Barrier/Cond Sync, Pure 0 Sleep)
 * 3. Nested Enter Depth-Balancing (resolving v2 boolean limitation via TLS depth counter)
 * 4. Actual Callback Execution with Registered Cleanup (d3dkmt_init_vulkan & get_d3dkmt_vulkan_instance)
 * 5. Real Cancellation Point Cleanup in Actual Callback (pthread_cleanup_push/pop in callback)
 * 6. POSIX pthread_key Fault Injection Immunity (zero dynamic key allocation)
 * 7. v2 RED to v3 GREEN Regression: Elimination of Callback Once-Poisoning on Transient Resource Failure
 * 8. Business Vulkan Failure Non-Poisoning Contract (original fatal failure contract preserved)
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <assert.h>
#include <pthread.h>
#include <dlfcn.h>
#include <errno.h>
#include <unistd.h>
#include <sys/wait.h>
#include <sys/types.h>

/* Minimal Wine type shims explicitly declared */
typedef int BOOL;
#define TRUE 1
#define FALSE 0
typedef unsigned int UINT;
typedef int32_t VkResult;
#define VK_SUCCESS 0
#define VK_INCOMPLETE 5
#define VK_ERROR_OUT_OF_HOST_MEMORY -1

#define WARN(fmt, ...) do {} while(0)
#define ERR(fmt, ...) do {} while(0)
#define TRACE(fmt, ...) do {} while(0)
#define debugstr_a(s) (s)

struct vulkan_instance_extensions {
    int has_VK_KHR_get_physical_device_properties2;
    int has_VK_KHR_external_memory_capabilities;
};

struct vulkan_instance {
    int valid;
};

static struct vulkan_instance g_mock_vk_instance = { .valid = 1 };
static int g_vulkan_instance_create_calls = 0;
static int g_mock_vulkan_instance_create_fail = 0;

/* Mock synchronization for cancellation testing inside callback */
static pthread_mutex_t g_cb_cancel_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t g_cb_cancel_cond = PTHREAD_COND_INITIALIZER;
static int g_block_in_vulkan_instance_create = 0;
static int g_worker_inside_vulkan_instance_create = 0;

static struct vulkan_instance *vulkan_instance_create(const struct vulkan_instance_extensions *ext)
{
    (void)ext;
    g_vulkan_instance_create_calls++;

    if (g_block_in_vulkan_instance_create)
    {
        /* Signal parent that worker has entered callback critical section */
        pthread_mutex_lock(&g_cb_cancel_mutex);
        g_worker_inside_vulkan_instance_create = 1;
        pthread_cond_broadcast(&g_cb_cancel_cond);

        /* Wait to be cancelled at this standard POSIX cancellation point */
        while (1) {
            pthread_cond_wait(&g_cb_cancel_cond, &g_cb_cancel_mutex);
        }
        pthread_mutex_unlock(&g_cb_cancel_mutex);
    }

    if (g_mock_vulkan_instance_create_fail)
        return NULL;

    return &g_mock_vk_instance;
}

typedef struct {
    char extensionName[64];
} VkExtensionProperties;

/* Stubs for vulkan_init_once real dependencies */
typedef void *(*PFN_vkGetDeviceProcAddr)(void *, const char *);
typedef void *(*PFN_vkGetInstanceProcAddr)(void *, const char *);
typedef VkResult (*PFN_vkCreateInstance)(void *, void *, void *);
typedef VkResult (*PFN_vkEnumerateInstanceExtensionProperties)(const char *, uint32_t *, VkExtensionProperties *);

static PFN_vkGetDeviceProcAddr p_vkGetDeviceProcAddr = NULL;
static PFN_vkGetInstanceProcAddr p_vkGetInstanceProcAddr = NULL;
static PFN_vkCreateInstance p_vkCreateInstance = NULL;
static PFN_vkEnumerateInstanceExtensionProperties p_vkEnumerateInstanceExtensionProperties = NULL;

static void *vulkan_handle = NULL;
static int fshack_enabled = 0;

struct vulkan_driver_funcs {
    void (*p_map_instance_extensions)(const struct vulkan_instance_extensions *);
};
static void mock_map_instance_extensions(const struct vulkan_instance_extensions *ext) { (void)ext; }
static struct vulkan_driver_funcs lazydrv_funcs = { .p_map_instance_extensions = mock_map_instance_extensions };
static const struct vulkan_driver_funcs *driver_funcs = NULL;

struct vulkan_funcs_mock {
    PFN_vkGetInstanceProcAddr p_vkGetInstanceProcAddr;
    PFN_vkGetDeviceProcAddr p_vkGetDeviceProcAddr;
    struct vulkan_instance_extensions host_extensions;
    struct vulkan_instance_extensions client_extensions;
};
static struct vulkan_funcs_mock vulkan_funcs;

#define ALL_VK_INSTANCE_EXTS
#define ALL_VK_CLIENT_INSTANCE_EXTS

/* Fault injection hooks for POSIX pthread_key APIs */
static int fault_inject_key_create = 0;
static int fault_inject_setspecific = 0;
static int key_create_call_count = 0;

static int test_pthread_key_create(pthread_key_t *key, void (*destructor)(void *))
{
    key_create_call_count++;
    if (fault_inject_key_create)
    {
        return EAGAIN; /* Simulate out of keys / resource exhaustion */
    }
    return pthread_key_create(key, destructor);
}

static int test_pthread_setspecific(pthread_key_t key, const void *value)
{
    if (fault_inject_setspecific)
    {
        return EINVAL; /* Simulate invalid key or TLS failure */
    }
    return pthread_setspecific(key, value);
}

#define pthread_key_create test_pthread_key_create
#define pthread_setspecific test_pthread_setspecific

/* Include the EXACT code extracted from patched vulkan.c and d3dkmt.c */
#include "extracted_guard_v3.c"


/* --- Synchronization primitives without sleep --- */
typedef struct {
    pthread_mutex_t mutex;
    pthread_cond_t cond;
    int phase;
} sync_state_t;

static void sync_init(sync_state_t *s) {
    pthread_mutex_init(&s->mutex, NULL);
    pthread_cond_init(&s->cond, NULL);
    s->phase = 0;
}

static void sync_wait_for(sync_state_t *s, int target_phase) {
    pthread_mutex_lock(&s->mutex);
    while (s->phase < target_phase) {
        pthread_cond_wait(&s->cond, &s->mutex);
    }
    pthread_mutex_unlock(&s->mutex);
}

static void sync_advance_to(sync_state_t *s, int next_phase) {
    pthread_mutex_lock(&s->mutex);
    s->phase = next_phase;
    pthread_cond_broadcast(&s->cond);
    pthread_mutex_unlock(&s->mutex);
}

static void sync_destroy(sync_state_t *s) {
    pthread_mutex_destroy(&s->mutex);
    pthread_cond_destroy(&s->cond);
}

/* ========================================================================= */
/* Scenario 1: Same-thread State Balance                                    */
/* ========================================================================= */
static void scenario_same_thread_balance(void)
{
    printf("  [S1] Checking initial query states...\n");
    assert(is_vulkan_init_in_progress() == FALSE);
    assert(is_d3dkmt_init_in_progress() == FALSE);

    printf("  [S1] Entering vulkan init guard...\n");
    assert(vulkan_init_guard_enter() == TRUE);
    assert(is_vulkan_init_in_progress() == TRUE);

    printf("  [S1] Entering d3dkmt init guard...\n");
    assert(d3dkmt_init_guard_enter() == TRUE);
    assert(is_d3dkmt_init_in_progress() == TRUE);

    printf("  [S1] Exiting d3dkmt init guard...\n");
    d3dkmt_init_guard_exit();
    assert(is_d3dkmt_init_in_progress() == FALSE);
    assert(is_vulkan_init_in_progress() == TRUE);

    printf("  [S1] Exiting vulkan init guard...\n");
    vulkan_init_guard_exit();
    assert(is_vulkan_init_in_progress() == FALSE);

    printf("  [S1] Secondary re-entrance test...\n");
    assert(vulkan_init_guard_enter() == TRUE);
    assert(is_vulkan_init_in_progress() == TRUE);
    vulkan_init_guard_exit();
    assert(is_vulkan_init_in_progress() == FALSE);
    printf("  [S1] Passed same-thread state balance.\n");
}

/* ========================================================================= */
/* Scenario 2: Two-thread Isolation (Barrier/Cond Sync, Pure 0 Sleep)       */
/* ========================================================================= */
typedef struct {
    sync_state_t *sync;
    int monitor_observed_vulkan_state;
    int monitor_observed_d3dkmt_state;
} thread_isolation_ctx_t;

static void *isolation_worker_thread(void *arg)
{
    thread_isolation_ctx_t *ctx = (thread_isolation_ctx_t *)arg;

    assert(vulkan_init_guard_enter() == TRUE);
    assert(is_vulkan_init_in_progress() == TRUE);

    sync_advance_to(ctx->sync, 1);
    sync_wait_for(ctx->sync, 2);

    vulkan_init_guard_exit();
    assert(is_vulkan_init_in_progress() == FALSE);

    sync_advance_to(ctx->sync, 3);
    return NULL;
}

static void *isolation_monitor_thread(void *arg)
{
    thread_isolation_ctx_t *ctx = (thread_isolation_ctx_t *)arg;

    sync_wait_for(ctx->sync, 1);

    ctx->monitor_observed_vulkan_state = is_vulkan_init_in_progress();
    ctx->monitor_observed_d3dkmt_state = is_d3dkmt_init_in_progress();

    sync_advance_to(ctx->sync, 2);
    sync_wait_for(ctx->sync, 3);

    assert(is_vulkan_init_in_progress() == FALSE);
    return NULL;
}

static void scenario_two_thread_isolation(void)
{
    sync_state_t sync;
    sync_init(&sync);

    thread_isolation_ctx_t ctx;
    ctx.sync = &sync;
    ctx.monitor_observed_vulkan_state = -1;
    ctx.monitor_observed_d3dkmt_state = -1;

    pthread_t worker, monitor;
    pthread_create(&worker, NULL, isolation_worker_thread, &ctx);
    pthread_create(&monitor, NULL, isolation_monitor_thread, &ctx);

    pthread_join(worker, NULL);
    pthread_join(monitor, NULL);
    sync_destroy(&sync);

    printf("  [S2] Monitor observed vulkan guard state: %d (expected 0 / FALSE)\n", ctx.monitor_observed_vulkan_state);
    assert(ctx.monitor_observed_vulkan_state == FALSE);
    assert(ctx.monitor_observed_d3dkmt_state == FALSE);
    printf("  [S2] Passed two-thread isolation (0 sleep cond sync).\n");
}

/* ========================================================================= */
/* Scenario 3: Nested Enter Depth-Balancing                                 */
/* ========================================================================= */
static void scenario_nested_enter_depth(void)
{
    printf("  [S3] Testing nested enter depth balancing...\n");
    assert(is_vulkan_init_in_progress() == FALSE);

    /* Outer enter (depth 0 -> 1) */
    assert(vulkan_init_guard_enter() == TRUE);
    assert(is_vulkan_init_in_progress() == TRUE);
    printf("  [S3] Outer enter depth is 1 (in progress: %d)\n", is_vulkan_init_in_progress());

    /* Nested inner enter (depth 1 -> 2) */
    assert(vulkan_init_guard_enter() == TRUE);
    assert(is_vulkan_init_in_progress() == TRUE);
    printf("  [S3] Inner nested enter depth is 2 (in progress: %d)\n", is_vulkan_init_in_progress());

    /* Inner exit (depth 2 -> 1) */
    vulkan_init_guard_exit();
    /*
     * VITAL CHECK: In v2 this returned FALSE (unprotected)!
     * In v3, depth counter ensures outer scope REMAINS PROTECTED!
     */
    assert(is_vulkan_init_in_progress() == TRUE);
    printf("  [S3] After inner exit, outer scope remains protected: %d (expected 1 / TRUE)\n",
           is_vulkan_init_in_progress());

    /* Outer exit (depth 1 -> 0) */
    vulkan_init_guard_exit();
    assert(is_vulkan_init_in_progress() == FALSE);
    printf("  [S3] After outer exit, depth is 0 (in progress: %d)\n", is_vulkan_init_in_progress());

    /* Extra exits do not underflow */
    vulkan_init_guard_exit();
    assert(is_vulkan_init_in_progress() == FALSE);

    printf("  [S3] Passed nested enter depth-balancing.\n");
}

/* ========================================================================= */
/* Scenario 4: Real Callback Execution with Registered Cleanup              */
/* ========================================================================= */
static void scenario_actual_callback_execution(void)
{
    printf("  [S4] Calling get_d3dkmt_vulkan_instance() from real extracted control flow...\n");
    assert(is_d3dkmt_init_in_progress() == FALSE);

    struct vulkan_instance *inst = get_d3dkmt_vulkan_instance();
    printf("  [S4] Received instance = %p (expected &g_mock_vk_instance = %p)\n", inst, &g_mock_vk_instance);
    assert(inst == &g_mock_vk_instance);

    /* After callback returns via pthread_cleanup_pop(1), depth MUST be 0 */
    assert(is_d3dkmt_init_in_progress() == FALSE);

    /* Second call returns cached instance without re-entering init */
    int before_calls = g_vulkan_instance_create_calls;
    struct vulkan_instance *inst2 = get_d3dkmt_vulkan_instance();
    assert(inst2 == inst);
    assert(g_vulkan_instance_create_calls == before_calls);

    printf("  [S4] Passed actual callback execution with unified cleanup pop.\n");
}

/* ========================================================================= */
/* Scenario 5: Real Cancellation Point Cleanup in Actual Callback           */
/* ========================================================================= */
static void *cancel_worker_thread(void *arg)
{
    (void)arg;
    pthread_setcancelstate(PTHREAD_CANCEL_ENABLE, NULL);
    pthread_setcanceltype(PTHREAD_CANCEL_DEFERRED, NULL);

    /*
     * Calls get_d3dkmt_vulkan_instance -> runs d3dkmt_init_vulkan
     * d3dkmt_init_vulkan registers pthread_cleanup_push( d3dkmt_init_guard_cleanup, NULL )
     * Inside vulkan_instance_create, worker blocks on pthread_cond_wait
     */
    get_d3dkmt_vulkan_instance();
    return NULL;
}

static void scenario_callback_cancellation(void)
{
    printf("  [S5] Testing thread cancellation inside real d3dkmt_init_vulkan callback...\n");
    g_block_in_vulkan_instance_create = 1;
    g_worker_inside_vulkan_instance_create = 0;

    pthread_t thread;
    pthread_create(&thread, NULL, cancel_worker_thread, NULL);

    /* Wait until worker enters d3dkmt_init_vulkan and blocks inside vulkan_instance_create */
    pthread_mutex_lock(&g_cb_cancel_mutex);
    while (!g_worker_inside_vulkan_instance_create) {
        pthread_cond_wait(&g_cb_cancel_cond, &g_cb_cancel_mutex);
    }
    pthread_mutex_unlock(&g_cb_cancel_mutex);

    printf("  [S5] Worker is inside callback critical section holding guard. Cancelling thread...\n");
    pthread_cancel(thread);

    void *res;
    /*
     * POSIX guarantee: pthread_join establishes happens-before relationship.
     * The cancellation unwinder executed pthread_cleanup_push registered in d3dkmt_init_vulkan!
     */
    pthread_join(thread, &res);
    assert(res == PTHREAD_CANCELED);

    g_block_in_vulkan_instance_create = 0;

    printf("  [S5] Worker cancelled. Verifying d3dkmt_init_depth cleanup via pthread_cleanup_push...\n");
    assert(is_d3dkmt_init_in_progress() == FALSE);

    printf("  [S5] Passed real cancellation point cleanup registered inside callback.\n");
}

/* ========================================================================= */
/* Scenario 6: POSIX pthread_key Fault Injection Immunity                   */
/* ========================================================================= */
static void scenario_key_fault_immunity(void)
{
    printf("  [S6] Injecting pthread_key_create & pthread_setspecific failures...\n");
    fault_inject_key_create = 1;
    fault_inject_setspecific = 1;
    key_create_call_count = 0;

    /*
     * In v3, guard uses compiler native TLS (__thread).
     * It NEVER calls pthread_key_create or pthread_setspecific!
     */
    assert(vulkan_init_guard_enter() == TRUE);
    assert(is_vulkan_init_in_progress() == TRUE);
    vulkan_init_guard_exit();
    assert(is_vulkan_init_in_progress() == FALSE);

    assert(d3dkmt_init_guard_enter() == TRUE);
    assert(is_d3dkmt_init_in_progress() == TRUE);
    d3dkmt_init_guard_exit();
    assert(is_d3dkmt_init_in_progress() == FALSE);

    printf("  [S6] Total pthread_key_create calls made: %d (expected exactly 0)\n", key_create_call_count);
    assert(key_create_call_count == 0);
    printf("  [S6] Passed pthread_key fault injection immunity (zero dynamic key allocation).\n");
}

/* ========================================================================= */
/* Scenario 7: v2 RED to v3 GREEN Regression: Once-Poisoning Elimination    */
/* ========================================================================= */
static void scenario_v2_red_to_v3_green(void)
{
    printf("  [S7] Running exact v2 RED fault scenario on v3...\n");
    /*
     * In v2 Scenario 8, fault_inject_key_create = 1 caused d3dkmt_init_guard_enter()
     * to fail, returning NULL, which permanently poisoned pthread_once as done.
     * In v3, native TLS is immune to pthread_key exhaustion.
     */
    fault_inject_key_create = 1;
    fault_inject_setspecific = 1;
    g_vulkan_instance_create_calls = 0;

    printf("  [S7] Step 1: Initial call with fault injection active...\n");
    struct vulkan_instance *inst1 = get_d3dkmt_vulkan_instance();
    printf("  [S7] First call returned inst1 = %p\n", inst1);
    assert(inst1 == &g_mock_vk_instance);
    assert(g_vulkan_instance_create_calls == 1);

    printf("  [S7] Step 2: Second call verifying cached instance...\n");
    struct vulkan_instance *inst2 = get_d3dkmt_vulkan_instance();
    printf("  [S7] Second call returned inst2 = %p\n", inst2);
    assert(inst2 == inst1);
    assert(g_vulkan_instance_create_calls == 1);

    printf("  [S7] [V3 GREEN CONFIRMED] Callback once-poisoning successfully eliminated!\n");
}

/* ========================================================================= */
/* Scenario 8: Business Vulkan Failure Non-Poisoning Contract               */
/* ========================================================================= */
static void scenario_business_failure_contract(void)
{
    printf("  [S8] Simulating business failure: host driver missing (vulkan_instance_create returns NULL)...\n");
    g_mock_vulkan_instance_create_fail = 1;
    g_vulkan_instance_create_calls = 0;

    struct vulkan_instance *inst = get_d3dkmt_vulkan_instance();
    printf("  [S8] Business failure returned inst = %p (expected NULL)\n", inst);
    assert(inst == NULL);
    assert(g_vulkan_instance_create_calls == 1);

    /* Verify guard depth is cleanly 0 */
    assert(is_d3dkmt_init_in_progress() == FALSE);

    /* Second call returns cached NULL, conforming to Wine upstream business contract */
    struct vulkan_instance *inst2 = get_d3dkmt_vulkan_instance();
    assert(inst2 == NULL);
    assert(g_vulkan_instance_create_calls == 1);

    printf("  [S8] Passed business failure original contract preservation (Acceptance 5).\n");
}

/* ========================================================================= */
/* Process Isolation Test Harness                                           */
/* ========================================================================= */
typedef struct {
    const char *name;
    void (*fn)(void);
} test_case_t;

int main(void)
{
    test_case_t tests[] = {
        {"1. Same-thread State Balance", scenario_same_thread_balance},
        {"2. Two-thread Isolation (Barrier/Cond Sync)", scenario_two_thread_isolation},
        {"3. Nested Enter Depth-Balancing", scenario_nested_enter_depth},
        {"4. Actual Callback Execution with Unified Cleanup Pop", scenario_actual_callback_execution},
        {"5. Real Cancellation Point Cleanup in Actual Callback", scenario_callback_cancellation},
        {"6. POSIX pthread_key Fault Injection Immunity", scenario_key_fault_immunity},
        {"7. v2 RED -> v3 GREEN Regression: Once-Poisoning Elimination", scenario_v2_red_to_v3_green},
        {"8. Business Vulkan Failure Non-Poisoning Contract Preservation", scenario_business_failure_contract},
    };

    int total = sizeof(tests) / sizeof(tests[0]);
    int passed = 0;
    int failed = 0;

    printf("============================================================\n");
    printf("Wine Win32u Reentrancy Guard v3 Test Suite\n");
    printf("Running %d isolated scenarios via fork()...\n", total);
    printf("============================================================\n\n");

    for (int i = 0; i < total; i++) {
        printf("--- Running [%s] ---\n", tests[i].name);
        fflush(stdout);

        pid_t pid = fork();
        if (pid < 0) {
            perror("fork");
            return 1;
        }

        if (pid == 0) {
            /* Child process: isolated address space */
            tests[i].fn();
            exit(0);
        }

        int status = 0;
        waitpid(pid, &status, 0);
        if (WIFEXITED(status) && WEXITSTATUS(status) == 0) {
            printf("[RESULT: PASS] %s\n\n", tests[i].name);
            passed++;
        } else {
            printf("[RESULT: FAIL] %s (exit code %d)\n\n", tests[i].name, WEXITSTATUS(status));
            failed++;
        }
    }

    printf("============================================================\n");
    printf("Summary: Total=%d, Passed=%d, Failed=%d\n", total, passed, failed);
    printf("============================================================\n");

    return (failed == 0) ? 0 : 1;
}
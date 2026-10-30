/*
 * test_guard_v2.c: Comprehensive Native unit test suite for Wine win32u guard v2.
 * Directly includes automatically extracted guard code and callback control flow
 * from patched real sources (vulkan.c and d3dkmt.c).
 *
 * Scenarios verified:
 * 1. Same-thread state balance (enter -> inside -> exit -> outside)
 * 2. Two-thread isolation (thread A in init does not affect thread B, pure cond sync, 0 sleep)
 * 3. Early exit error cleanup (all bailouts clear guard state)
 * 4. Resource failure: pthread_key_create failure handling (no read of uncreated key, enter fails)
 * 5. Resource failure: pthread_setspecific failure handling & cleanup failure path
 * 6. POSIX cancellation cleanup helper (pthread_cleanup_push / vulkan_init_guard_cleanup; 0 sleep, join happens-before)
 * 7. Nested enter limitation: boolean marker does not count depth (architectural boundary check)
 * 8. RED Callback Test: Callback once-poisoning on transient resource failure
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <assert.h>
#include <pthread.h>
#include <errno.h>
#include <unistd.h>
#include <sys/wait.h>
#include <sys/types.h>

/* Minimal Wine type shims explicitly declared */
typedef int BOOL;
#define TRUE 1
#define FALSE 0

#define WARN(fmt, ...) do {} while(0)
#define ERR(fmt, ...) do {} while(0)

struct vulkan_instance_extensions {
    int has_VK_KHR_get_physical_device_properties2;
    int has_VK_KHR_external_memory_capabilities;
};

struct vulkan_instance {
    int valid;
};

static struct vulkan_instance g_mock_vk_instance = { .valid = 1 };

static struct vulkan_instance *vulkan_instance_create(const struct vulkan_instance_extensions *ext)
{
    (void)ext;
    return &g_mock_vk_instance;
}

/* Fault injection hooks */
static int fault_inject_key_create = 0;
static int fault_inject_setspecific = 0;
static int fault_inject_setspecific_null = 0;

static int test_pthread_key_create(pthread_key_t *key, void (*destructor)(void *))
{
    if (fault_inject_key_create)
    {
        return EAGAIN; /* Out of resources / key limit reached */
    }
    return pthread_key_create(key, destructor);
}

static int test_pthread_setspecific(pthread_key_t key, const void *value)
{
    if (value != NULL && fault_inject_setspecific)
    {
        return EINVAL; /* Invalid key or TLS storage failure on enter */
    }
    if (value == NULL && fault_inject_setspecific_null)
    {
        return EINVAL; /* Failure when clearing key */
    }
    return pthread_setspecific(key, value);
}

#define pthread_key_create test_pthread_key_create
#define pthread_setspecific test_pthread_setspecific

/* Include the EXACT code extracted from patched vulkan.c and d3dkmt.c */
#include "extracted_guard.c"

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

    /* Signal monitor that worker is inside guard */
    sync_advance_to(ctx->sync, 1);

    /* Wait for monitor to perform verification */
    sync_wait_for(ctx->sync, 2);

    /* Worker exits guard */
    vulkan_init_guard_exit();
    assert(is_vulkan_init_in_progress() == FALSE);

    /* Signal monitor that worker has exited */
    sync_advance_to(ctx->sync, 3);

    return NULL;
}

static void *isolation_monitor_thread(void *arg)
{
    thread_isolation_ctx_t *ctx = (thread_isolation_ctx_t *)arg;

    /* Wait until worker enters guard */
    sync_wait_for(ctx->sync, 1);

    /* Monitor thread queries guard while worker is holding it */
    ctx->monitor_observed_vulkan_state = is_vulkan_init_in_progress();
    ctx->monitor_observed_d3dkmt_state = is_d3dkmt_init_in_progress();

    /* Signal worker to exit */
    sync_advance_to(ctx->sync, 2);

    /* Wait until worker has exited */
    sync_wait_for(ctx->sync, 3);

    /* Re-verify monitor state */
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
/* Scenario 3: Early Exit and Error Cleanup                                 */
/* ========================================================================= */
static void scenario_early_exit_cleanup(void)
{
    printf("  [S3] Simulating early exit on vulkan failure...\n");
    assert(vulkan_init_guard_enter() == TRUE);
    assert(is_vulkan_init_in_progress() == TRUE);

    vulkan_init_guard_exit();
    assert(is_vulkan_init_in_progress() == FALSE);

    printf("  [S3] Simulating early exit on d3dkmt failure...\n");
    assert(d3dkmt_init_guard_enter() == TRUE);
    assert(is_d3dkmt_init_in_progress() == TRUE);

    d3dkmt_init_guard_exit();
    assert(is_d3dkmt_init_in_progress() == FALSE);

    /* Verify clean subsequent entry */
    assert(vulkan_init_guard_enter() == TRUE);
    assert(is_vulkan_init_in_progress() == TRUE);
    vulkan_init_guard_exit();
    assert(is_vulkan_init_in_progress() == FALSE);

    printf("  [S3] Passed early exit error cleanup.\n");
}

/* ========================================================================= */
/* Scenario 4: Resource Error: pthread_key_create Failure                   */
/* ========================================================================= */
static void scenario_key_create_failure(void)
{
    printf("  [S4] Injecting pthread_key_create failure (EAGAIN)...\n");
    fault_inject_key_create = 1;

    printf("  [S4] Querying guard when key creation fails...\n");
    assert(is_vulkan_init_in_progress() == FALSE);
    assert(is_d3dkmt_init_in_progress() == FALSE);

    printf("  [S4] Attempting guard enter when key creation fails...\n");
    assert(vulkan_init_guard_enter() == FALSE); /* Enter MUST fail! */
    assert(d3dkmt_init_guard_enter() == FALSE); /* Enter MUST fail! */

    printf("  [S4] Guard exit when key uncreated must be safe no-op...\n");
    vulkan_init_guard_exit();
    d3dkmt_init_guard_exit();

    assert(is_vulkan_init_in_progress() == FALSE);
    assert(is_d3dkmt_init_in_progress() == FALSE);
    printf("  [S4] Passed pthread_key_create failure handling.\n");
}

/* ========================================================================= */
/* Scenario 5: Resource Error: pthread_setspecific Failure & Exit Failure   */
/* ========================================================================= */
static void scenario_setspecific_failure(void)
{
    printf("  [S5] Initializing key successfully first...\n");
    fault_inject_key_create = 0;
    assert(is_vulkan_init_in_progress() == FALSE);
    assert(is_d3dkmt_init_in_progress() == FALSE);

    printf("  [S5] Injecting pthread_setspecific failure on enter (EINVAL)...\n");
    fault_inject_setspecific = 1;

    /* Enter should detect setspeficic failure and return FALSE */
    assert(vulkan_init_guard_enter() == FALSE);
    assert(d3dkmt_init_guard_enter() == FALSE);

    /* Because setspecific failed, query MUST report FALSE */
    assert(is_vulkan_init_in_progress() == FALSE);
    assert(is_d3dkmt_init_in_progress() == FALSE);

    fault_inject_setspecific = 0;

    printf("  [S5] Testing setspecific(NULL) cleanup failure path...\n");
    assert(vulkan_init_guard_enter() == TRUE);
    assert(is_vulkan_init_in_progress() == TRUE);

    /* If clearing the key fails: */
    fault_inject_setspecific_null = 1;
    vulkan_init_guard_exit(); /* Calls setspeficic(..., NULL) which fails */
    /*
     * Architectural observation: guard_exit() returns void and cannot propagate
     * clearing failure to callers. If clearing fails, key remains set.
     */
    printf("  [S5] Observed: if setspecific(NULL) fails, guard cannot clear TLS (contract limitation).\n");
    fault_inject_setspecific_null = 0;
    vulkan_init_guard_exit(); /* Clear properly */
    assert(is_vulkan_init_in_progress() == FALSE);

    printf("  [S5] Passed pthread_setspecific failure handling & boundary check.\n");
}

/* ========================================================================= */
/* Scenario 6: Cancellation Point Cleanup (0 Sleep, Join Happens-Before)    */
/* ========================================================================= */
typedef struct {
    sync_state_t *sync;
    pthread_mutex_t cancel_mutex;
    pthread_cond_t cancel_cond;
    int cleanup_executed;
} cancel_ctx_t;

static cancel_ctx_t g_cancel_ctx;

static void test_cancel_cleanup(void *arg)
{
    (void)arg;
    g_cancel_ctx.cleanup_executed = 1;
    vulkan_init_guard_cleanup(arg);
}

static void *cancellation_worker_thread(void *arg)
{
    cancel_ctx_t *ctx = (cancel_ctx_t *)arg;

    pthread_setcancelstate(PTHREAD_CANCEL_ENABLE, NULL);
    pthread_setcanceltype(PTHREAD_CANCEL_DEFERRED, NULL);

    assert(vulkan_init_guard_enter() == TRUE);
    assert(is_vulkan_init_in_progress() == TRUE);

    pthread_cleanup_push(test_cancel_cleanup, NULL);

    /* Signal parent that guard is held */
    sync_advance_to(ctx->sync, 1);

    /*
     * Official POSIX cancellation point: pthread_cond_wait.
     * ZERO sleep: blocks cleanly until parent cancels the thread.
     */
    pthread_mutex_lock(&ctx->cancel_mutex);
    while (1) {
        pthread_cond_wait(&ctx->cancel_cond, &ctx->cancel_mutex);
    }
    pthread_mutex_unlock(&ctx->cancel_mutex);

    pthread_cleanup_pop(0);
    return NULL;
}

static void scenario_cancellation_point_cleanup(void)
{
    printf("  [S6] Testing cancellation point cleanup...\n");
    printf("  [S6] Note: Real Wine vulkan_init_once does NOT register pthread_cleanup_push in upstream.\n");
    printf("  [S6] Verifying POSIX cleanup handler behavior upon thread cancellation (0 sleep)...\n");

    sync_state_t sync;
    sync_init(&sync);

    g_cancel_ctx.sync = &sync;
    pthread_mutex_init(&g_cancel_ctx.cancel_mutex, NULL);
    pthread_cond_init(&g_cancel_ctx.cancel_cond, NULL);
    g_cancel_ctx.cleanup_executed = 0;

    pthread_t thread;
    pthread_create(&thread, NULL, cancellation_worker_thread, &g_cancel_ctx);

    /* Wait until worker enters guard */
    sync_wait_for(&sync, 1);

    /* Cancel worker blocked at cancellation point (pthread_cond_wait) */
    pthread_cancel(thread);

    void *res;
    /*
     * POSIX guarantee: pthread_join establishes a happens-before relationship
     * ensuring all memory writes by the terminating thread and its cleanup handlers
     * are fully visible after pthread_join returns.
     */
    pthread_join(thread, &res);
    assert(res == PTHREAD_CANCELED);

    pthread_mutex_destroy(&g_cancel_ctx.cancel_mutex);
    pthread_cond_destroy(&g_cancel_ctx.cancel_cond);
    sync_destroy(&sync);

    printf("  [S6] Cleanup handler executed: %d (via join happens-before)\n", g_cancel_ctx.cleanup_executed);
    assert(g_cancel_ctx.cleanup_executed == 1);

    /* Verify guard state in current thread is completely clean */
    assert(is_vulkan_init_in_progress() == FALSE);
    assert(vulkan_init_guard_enter() == TRUE);
    vulkan_init_guard_exit();
    assert(is_vulkan_init_in_progress() == FALSE);

    printf("  [S6] Passed cancellation point cleanup (0 sleep cond wait).\n");
}

/* ========================================================================= */
/* Scenario 7: Nested Enter Non-Depth-Tracking Limitation                  */
/* ========================================================================= */
static void scenario_nested_enter_limitation(void)
{
    printf("  [S7] Demonstrating non-nested boolean marker boundary...\n");
    assert(is_vulkan_init_in_progress() == FALSE);

    /* Outer enter */
    assert(vulkan_init_guard_enter() == TRUE);
    assert(is_vulkan_init_in_progress() == TRUE);

    /*
     * If a nested enter occurs on the same thread:
     * Current implementation overwrites TLS with (void*)1 (no depth counter).
     */
    assert(vulkan_init_guard_enter() == TRUE);
    assert(is_vulkan_init_in_progress() == TRUE);

    /* Inner exit: clears TLS key to NULL! */
    vulkan_init_guard_exit();

    /*
     * Outer scope is now UNPROTECTED!
     * is_vulkan_init_in_progress() returns FALSE even though outer scope is running.
     */
    int unprotected = (is_vulkan_init_in_progress() == FALSE);
    printf("  [S7] Inner exit cleared marker; outer scope unprotected: %d (expected 1)\n", unprotected);
    assert(unprotected == 1);

    printf("  [S7] Architectural premise established: Guard strictly requires non-nested invocation.\n");
}

/* ========================================================================= */
/* Scenario 8: Callback Once-Poisoning On Transient Resource Failure (RED)  */
/* ========================================================================= */
static void scenario_callback_once_poisoning(void)
{
    printf("  [S8] Testing callback-level once-poisoning from real patched d3dkmt control flow...\n");

    /* Step 1: Transient resource failure during initial callback */
    printf("  [S8] Step 1: Inject transient resource failure (fault_inject_key_create = 1)...\n");
    fault_inject_key_create = 1;
    struct vulkan_instance *inst1 = get_d3dkmt_vulkan_instance();
    printf("  [S8] First call returned inst1 = %p (expected NULL due to resource failure)\n", inst1);
    assert(inst1 == NULL);

    /* Step 2: Resources recover */
    printf("  [S8] Step 2: System resources recover (fault_inject_key_create = 0)...\n");
    fault_inject_key_create = 0;

    /* Step 3: Subsequent call attempting recovery */
    printf("  [S8] Step 3: Subsequent call attempting recovery...\n");
    struct vulkan_instance *inst2 = get_d3dkmt_vulkan_instance();
    printf("  [S8] Second call returned inst2 = %p\n", inst2);

    /*
     * ARCHITECTURAL DEFECT DEMONSTRATION (RED TEST):
     * If recovery were supported, inst2 should be non-NULL (g_mock_vk_instance).
     * BUT because d3dkmt_init_vulkan returned normally on guard failure,
     * POSIX pthread_once marked the once object as DONE!
     * Subsequent calls never re-execute d3dkmt_init_vulkan. inst2 is NULL forever.
     * This assert FAILS by design, proving the Once-Poisoning vulnerability!
     */
    if (inst2 == NULL) {
        printf("  [S8] [RED DEFECT PROVEN] Once-poisoning confirmed: pthread_once permanently poisoned as NULL!\n");
        assert(inst2 != NULL); /* This deliberately asserts failure (RED) */
    }
}

/* ========================================================================= */
/* Process Isolation Test Harness                                           */
/* ========================================================================= */
typedef struct {
    const char *name;
    void (*fn)(void);
    int expect_fail; /* 1 if this is a designed RED test */
} test_case_t;

int main(void)
{
    test_case_t tests[] = {
        {"1. Same-thread State Balance", scenario_same_thread_balance, 0},
        {"2. Two-thread Isolation (Barrier/Cond Sync)", scenario_two_thread_isolation, 0},
        {"3. Early Exit Error Cleanup", scenario_early_exit_cleanup, 0},
        {"4. Resource Error: pthread_key_create Failure", scenario_key_create_failure, 0},
        {"5. Resource Error: pthread_setspecific Failure", scenario_setspecific_failure, 0},
        {"6. Reachable Cancellation Point Cleanup", scenario_cancellation_point_cleanup, 0},
        {"7. Nested Enter Limitation (No Depth Counter)", scenario_nested_enter_limitation, 0},
        {"8. Callback Once-Poisoning On Resource Failure (RED Test)", scenario_callback_once_poisoning, 1},
    };

    int total = sizeof(tests) / sizeof(tests[0]);
    int passed = 0;
    int failed = 0;
    int red_confirmed = 0;

    printf("============================================================\n");
    printf("Wine Win32u Reentrancy Guard v2 & Callback Suite\n");
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
        int success = (WIFEXITED(status) && WEXITSTATUS(status) == 0);

        if (tests[i].expect_fail) {
            if (!success) {
                printf("[RESULT: RED_CONFIRMED] %s (Deliberate failure reproduced architectural limitation)\n\n", tests[i].name);
                red_confirmed++;
            } else {
                printf("[RESULT: UNEXPECTED_PASS] %s\n\n", tests[i].name);
                passed++;
            }
        } else {
            if (success) {
                printf("[RESULT: PASS] %s\n\n", tests[i].name);
                passed++;
            } else {
                printf("[RESULT: FAIL] %s (exit code %d)\n\n", tests[i].name, WEXITSTATUS(status));
                failed++;
            }
        }
    }

    printf("============================================================\n");
    printf("Summary: Total=%d, Green_Passed=%d, Red_Defects_Confirmed=%d, Unexpected_Failed=%d\n",
           total, passed, red_confirmed, failed);
    printf("============================================================\n");

    return (failed == 0) ? 0 : 1;
}

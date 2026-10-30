/*
 * Native Standalone pthread test verifying exact Re-entrancy Guard semantics.
 * Tested scenarios:
 * 1. First Vulkan Entry (vulkan_init_once -> driver_init -> lock_display -> get_vulkan_gpus -> deferred)
 * 2. First D3DKMT Entry (d3dkmt_init_vulkan -> vulkan_instance_create -> get_vulkan_gpus -> deferred)
 * 3. Concurrent Thread Isolation (Thread A inside init; Thread B querying guard must see FALSE)
 * 4. Early Exit / Error Cleanup (all failure paths must clear thread-specific key)
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <assert.h>
#include <pthread.h>

typedef int BOOL;
#define TRUE 1
#define FALSE 0

static const pthread_once_t default_once_init = PTHREAD_ONCE_INIT;

/* --- Exact guard implementation from candidate patch for vulkan.c --- */
static pthread_key_t vulkan_init_key;
static pthread_once_t vulkan_key_once = PTHREAD_ONCE_INIT;

static void init_vulkan_key(void)
{
    pthread_key_create( &vulkan_init_key, NULL );
}

BOOL is_vulkan_init_in_progress(void)
{
    pthread_once( &vulkan_key_once, init_vulkan_key );
    return pthread_getspecific( vulkan_init_key ) != NULL;
}

/* --- Exact guard implementation from candidate patch for d3dkmt.c --- */
static pthread_key_t d3dkmt_init_key;
static pthread_once_t d3dkmt_key_once = PTHREAD_ONCE_INIT;

static void init_d3dkmt_key(void)
{
    pthread_key_create( &d3dkmt_init_key, NULL );
}

static BOOL is_d3dkmt_init_in_progress(void)
{
    pthread_once( &d3dkmt_key_once, init_d3dkmt_key );
    return pthread_getspecific( d3dkmt_init_key ) != NULL;
}

/* --- Simulation Call Chain --- */
static pthread_once_t d3dkmt_once = PTHREAD_ONCE_INIT;
static pthread_once_t driver_once = PTHREAD_ONCE_INIT;

static int sim_d3dkmt_vulkan_instance_created = 0;
static int sim_vulkan_driver_inited = 0;
static int sim_gpu_probe_deferred_count = 0;
static int sim_fallback_taken_count = 0;

static void *sim_vulkan_instance_create(void);
static void *sim_get_d3dkmt_vulkan_instance(void);

BOOL sim_get_vulkan_gpus(void)
{
    if (is_vulkan_init_in_progress()) {
        sim_gpu_probe_deferred_count++;
        return FALSE; /* Defer to avoid deadlock */
    }
    void *instance = sim_get_d3dkmt_vulkan_instance();
    if (!instance) return FALSE;
    return TRUE;
}

void sim_lock_display_devices(void)
{
    if (!sim_get_vulkan_gpus()) {
        /* Fallback to OpenGL / default adapter */
        sim_fallback_taken_count++;
    }
}

void sim_vulkan_driver_init(void)
{
    /* Simulate driver init querying display devices */
    sim_lock_display_devices();
    sim_vulkan_driver_inited = 1;
}

void sim_lazydrv_map_instance_extensions(void)
{
    pthread_once( &driver_once, sim_vulkan_driver_init );
}

/* Simulated d3dkmt_init_vulkan */
void sim_d3dkmt_init_vulkan(void)
{
    pthread_once( &d3dkmt_key_once, init_d3dkmt_key );
    pthread_setspecific( d3dkmt_init_key, (void *)(intptr_t)1 );

    void *inst = sim_vulkan_instance_create();
    if (inst) sim_d3dkmt_vulkan_instance_created = 1;

    pthread_setspecific( d3dkmt_init_key, NULL );
}

static void *sim_get_d3dkmt_vulkan_instance(void)
{
    if (is_d3dkmt_init_in_progress()) return NULL;
    pthread_once( &d3dkmt_once, sim_d3dkmt_init_vulkan );
    return sim_d3dkmt_vulkan_instance_created ? (void *)0xcafe : NULL;
}

static void *sim_vulkan_instance_create(void)
{
    /* Instance creation calls driver map extensions */
    sim_lazydrv_map_instance_extensions();
    return (void *)0xbeef;
}

/* Simulated vulkan_init_once with exit mode:
 * 0 = normal
 * 1 = early exit 1 (no handle)
 * 2 = early exit 2 (dlsym fail)
 * 3 = failure label exit
 */
int sim_vulkan_init_once(int exit_mode)
{
    pthread_once( &vulkan_key_once, init_vulkan_key );
    pthread_setspecific( vulkan_init_key, (void *)(intptr_t)1 );

    if (exit_mode == 1) {
        pthread_setspecific( vulkan_init_key, NULL );
        return -1;
    }
    if (exit_mode == 2) {
        pthread_setspecific( vulkan_init_key, NULL );
        return -2;
    }

    /* Normal execution calls map extensions */
    sim_lazydrv_map_instance_extensions();

    if (exit_mode == 3) {
        /* failed label */
        pthread_setspecific( vulkan_init_key, NULL );
        return -3;
    }

    pthread_setspecific( vulkan_init_key, NULL );
    return 0;
}

/* --- Scenario 3: Concurrency barrier & thread --- */
static pthread_mutex_t sync_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t sync_cond = PTHREAD_COND_INITIALIZER;
static int stage = 0;
static BOOL thread_b_saw_vulkan_in_progress = FALSE;

static void *thread_b_worker(void *arg)
{
    (void)arg;
    /* Wait until Thread A sets stage to 1 */
    pthread_mutex_lock( &sync_lock );
    while (stage != 1) pthread_cond_wait( &sync_cond, &sync_lock );
    pthread_mutex_unlock( &sync_lock );

    /* Thread B queries guard while Thread A holds key */
    thread_b_saw_vulkan_in_progress = is_vulkan_init_in_progress();

    /* Inform Thread A that check is complete */
    pthread_mutex_lock( &sync_lock );
    stage = 2;
    pthread_cond_signal( &sync_cond );
    pthread_mutex_unlock( &sync_lock );

    return NULL;
}

int main(void)
{
    printf("=== Native Re-entrancy Guard Test Suite ===\n");

    /* Test 1: Scenario A - First Vulkan Entry */
    printf("[Test 1] Running Scenario A: First Vulkan Entry...\n");
    assert(is_vulkan_init_in_progress() == FALSE);
    int res = sim_vulkan_init_once(0);
    assert(res == 0);
    assert(sim_vulkan_driver_inited == 1);
    assert(sim_gpu_probe_deferred_count == 1);
    assert(sim_fallback_taken_count == 1);
    assert(is_vulkan_init_in_progress() == FALSE);
    printf("  -> PASS: Deferred without recursion, driver inited, TLS cleaned up.\n");

    /* Reset state for Test 2 */
    d3dkmt_once = default_once_init;
    driver_once = default_once_init;
    sim_d3dkmt_vulkan_instance_created = 0;
    sim_vulkan_driver_inited = 0;
    sim_gpu_probe_deferred_count = 0;
    sim_fallback_taken_count = 0;

    /* Test 2: Scenario B - First D3DKMT Entry */
    printf("[Test 2] Running Scenario B: First D3DKMT Entry...\n");
    assert(is_d3dkmt_init_in_progress() == FALSE);
    void *inst = sim_get_d3dkmt_vulkan_instance();
    assert(inst != NULL);
    assert(sim_d3dkmt_vulkan_instance_created == 1);
    assert(is_d3dkmt_init_in_progress() == FALSE);
    printf("  -> PASS: D3DKMT initiated without self-deadlock, TLS cleaned up.\n");

    /* Test 3: Scenario C - Concurrency & Thread Isolation */
    printf("[Test 3] Running Scenario C: Concurrent Thread Isolation...\n");
    stage = 0;
    pthread_t tb;
    pthread_create( &tb, NULL, thread_b_worker, NULL );

    /* Thread A sets vulkan_init_key */
    pthread_once( &vulkan_key_once, init_vulkan_key );
    pthread_setspecific( vulkan_init_key, (void *)(intptr_t)1 );
    assert(is_vulkan_init_in_progress() == TRUE);

    /* Signal Thread B */
    pthread_mutex_lock( &sync_lock );
    stage = 1;
    pthread_cond_signal( &sync_cond );
    while (stage != 2) pthread_cond_wait( &sync_cond, &sync_lock );
    pthread_mutex_unlock( &sync_lock );

    pthread_join( tb, NULL );

    /* Thread B must have seen FALSE (complete thread isolation) */
    assert(thread_b_saw_vulkan_in_progress == FALSE);
    pthread_setspecific( vulkan_init_key, NULL );
    assert(is_vulkan_init_in_progress() == FALSE);
    printf("  -> PASS: Thread B saw FALSE while Thread A held TLS key. No cross-thread data race.\n");

    /* Test 4: Exit Cleanup on Early Failures */
    printf("[Test 4] Running Exit Cleanup Verification on Early Errors...\n");
    assert(sim_vulkan_init_once(1) == -1);
    assert(is_vulkan_init_in_progress() == FALSE);
    assert(sim_vulkan_init_once(2) == -2);
    assert(is_vulkan_init_in_progress() == FALSE);
    assert(sim_vulkan_init_once(3) == -3);
    assert(is_vulkan_init_in_progress() == FALSE);
    printf("  -> PASS: All 3 failure exit paths restored TLS key to NULL cleanly.\n");

    printf("=== ALL 4 NATIVE GUARD TESTS PASSED ===\n");
    return 0;
}

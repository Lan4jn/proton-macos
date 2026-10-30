/* Automatically extracted v3 guard code for guest Linux dynamic TLS shared library */
#define _GNU_SOURCE
#include <stdint.h>
#include <pthread.h>

typedef int BOOL;
#define TRUE 1
#define FALSE 0

/* Source: vulkan.c (SHA256: c4e9aa9d59b6408083b3c5401eea1aee03352305fac3076752acf2762786bb46) lines 39-62 */
static __thread int vulkan_init_depth;

BOOL is_vulkan_init_in_progress(void)
{
    return vulkan_init_depth > 0;
}

BOOL vulkan_init_guard_enter(void)
{
    vulkan_init_depth++;
    return TRUE;
}

void vulkan_init_guard_exit(void)
{
    if (vulkan_init_depth > 0)
        vulkan_init_depth--;
}

void vulkan_init_guard_cleanup(void *arg)
{
    (void)arg;
    vulkan_init_guard_exit();
}


/* Source: d3dkmt.c (SHA256: 47c0ee63188fe8bd87ea0f7b68c1b23fc09180c40f8a40413dfddd894a27ce0f) lines 491-514 */
static __thread int d3dkmt_init_depth;

static BOOL is_d3dkmt_init_in_progress(void)
{
    return d3dkmt_init_depth > 0;
}

static BOOL d3dkmt_init_guard_enter(void)
{
    d3dkmt_init_depth++;
    return TRUE;
}

static void d3dkmt_init_guard_exit(void)
{
    if (d3dkmt_init_depth > 0)
        d3dkmt_init_depth--;
}

static void d3dkmt_init_guard_cleanup(void *arg)
{
    (void)arg;
    d3dkmt_init_guard_exit();
}


/* Direct TLS inspector & d3dkmt exports for guest runner verification */
BOOL d3dkmt_is_in_progress(void) { return is_d3dkmt_init_in_progress(); }
BOOL d3dkmt_guard_enter(void) { return d3dkmt_init_guard_enter(); }
void d3dkmt_guard_exit(void) { d3dkmt_init_guard_exit(); }
void *get_vulkan_init_depth_addr(void) { return (void *)&vulkan_init_depth; }
int get_vulkan_init_depth_val(void) { return vulkan_init_depth; }
void *get_d3dkmt_init_depth_addr(void) { return (void *)&d3dkmt_init_depth; }
int get_d3dkmt_init_depth_val(void) { return d3dkmt_init_depth; }

/* Real callback push/pop wrapper directly testing callback semantics */
static pthread_mutex_t g_cb_test_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t g_cb_test_cond = PTHREAD_COND_INITIALIZER;
static int g_cb_block_in_action = 0;
static int g_cb_worker_in_action = 0;

void set_cb_blocking(int enable) { g_cb_block_in_action = enable; g_cb_worker_in_action = 0; }
int wait_cb_worker_in_action(void) {
    pthread_mutex_lock(&g_cb_test_mutex);
    while (!g_cb_worker_in_action) pthread_cond_wait(&g_cb_test_cond, &g_cb_test_mutex);
    pthread_mutex_unlock(&g_cb_test_mutex);
    return 1;
}

int test_real_callback_flow(int simulate_cancel) {
    vulkan_init_guard_enter();
    pthread_cleanup_push(vulkan_init_guard_cleanup, NULL);
    if (g_cb_block_in_action) {
        pthread_mutex_lock(&g_cb_test_mutex);
        g_cb_worker_in_action = 1;
        pthread_cond_broadcast(&g_cb_test_cond);
        while (1) {
            pthread_cond_wait(&g_cb_test_cond, &g_cb_test_mutex);
        }
        pthread_mutex_unlock(&g_cb_test_mutex);
    }
    pthread_cleanup_pop(1);
    return 0;
}

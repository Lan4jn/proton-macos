/* Automatically extracted guard code from patched real sources */
/* Source 1: vulkan.c (SHA256: 6164a9e75e5cef2062a932a99b4a4a673e95b4ef971149f0af316aa592d36efc) lines 39-72 */
/* --- BEGIN VULKAN GUARD --- */
static pthread_key_t vulkan_init_key;
static pthread_once_t vulkan_key_once = PTHREAD_ONCE_INIT;
static int vulkan_key_init_status = -1;

static void init_vulkan_key(void)
{
    vulkan_key_init_status = pthread_key_create( &vulkan_init_key, NULL );
}

BOOL is_vulkan_init_in_progress(void)
{
    pthread_once( &vulkan_key_once, init_vulkan_key );
    if (vulkan_key_init_status != 0) return FALSE;
    return pthread_getspecific( vulkan_init_key ) != NULL;
}

BOOL vulkan_init_guard_enter(void)
{
    pthread_once( &vulkan_key_once, init_vulkan_key );
    if (vulkan_key_init_status != 0) return FALSE;
    if (pthread_setspecific( vulkan_init_key, (void *)(intptr_t)1 ) != 0) return FALSE;
    return TRUE;
}

void vulkan_init_guard_exit(void)
{
    if (vulkan_key_init_status == 0)
        pthread_setspecific( vulkan_init_key, NULL );
}

void vulkan_init_guard_cleanup(void *arg)
{
    vulkan_init_guard_exit();
}

/* --- END VULKAN GUARD --- */

/* Source 2: d3dkmt.c (SHA256: 2c35766f6054ad4c41fb8ca695661835aedcda1191db1d03551108f0b350201b) lines 491-524 */
/* --- BEGIN D3DKMT GUARD --- */
static pthread_key_t d3dkmt_init_key;
static pthread_once_t d3dkmt_key_once = PTHREAD_ONCE_INIT;
static int d3dkmt_key_init_status = -1;

static void init_d3dkmt_key(void)
{
    d3dkmt_key_init_status = pthread_key_create( &d3dkmt_init_key, NULL );
}

static BOOL is_d3dkmt_init_in_progress(void)
{
    pthread_once( &d3dkmt_key_once, init_d3dkmt_key );
    if (d3dkmt_key_init_status != 0) return FALSE;
    return pthread_getspecific( d3dkmt_init_key ) != NULL;
}

static BOOL d3dkmt_init_guard_enter(void)
{
    pthread_once( &d3dkmt_key_once, init_d3dkmt_key );
    if (d3dkmt_key_init_status != 0) return FALSE;
    if (pthread_setspecific( d3dkmt_init_key, (void *)(intptr_t)1 ) != 0) return FALSE;
    return TRUE;
}

static void d3dkmt_init_guard_exit(void)
{
    if (d3dkmt_key_init_status == 0)
        pthread_setspecific( d3dkmt_init_key, NULL );
}

static void d3dkmt_init_guard_cleanup(void *arg)
{
    d3dkmt_init_guard_exit();
}

/* --- END D3DKMT GUARD --- */

/* Source 3: d3dkmt.c callback control flow lines 527-552 */
/* --- BEGIN D3DKMT CALLBACK FLOW --- */
static struct vulkan_instance *d3dkmt_vulkan_instance;

static void d3dkmt_init_vulkan(void)
{
    static const struct vulkan_instance_extensions extensions =
    {
        .has_VK_KHR_get_physical_device_properties2 = 1,
        .has_VK_KHR_external_memory_capabilities = 1,
    };

    if (!d3dkmt_init_guard_enter())
    {
        WARN( "Failed to enter d3dkmt init guard\n" );
        d3dkmt_vulkan_instance = NULL;
        return;
    }
    d3dkmt_vulkan_instance = vulkan_instance_create( &extensions );
    d3dkmt_init_guard_exit();
    if (!d3dkmt_vulkan_instance) WARN( "Failed to create the vulkan instance\n" );
}

static struct vulkan_instance *get_d3dkmt_vulkan_instance(void)
{
    static pthread_once_t once = PTHREAD_ONCE_INIT;
    if (is_d3dkmt_init_in_progress()) return NULL;
    pthread_once( &once, d3dkmt_init_vulkan );
    return d3dkmt_vulkan_instance;
}

/* --- END D3DKMT CALLBACK FLOW --- */

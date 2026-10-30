/* Automatically extracted guard code from patched real sources (v3) */
/* Source 1: vulkan.c (SHA256: c4e9aa9d59b6408083b3c5401eea1aee03352305fac3076752acf2762786bb46) lines 39-62 */
/* --- BEGIN VULKAN GUARD --- */
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

/* --- END VULKAN GUARD --- */

/* Source 2: d3dkmt.c (SHA256: 47c0ee63188fe8bd87ea0f7b68c1b23fc09180c40f8a40413dfddd894a27ce0f) lines 491-514 */
/* --- BEGIN D3DKMT GUARD --- */
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

/* --- END D3DKMT GUARD --- */

/* Source 3: d3dkmt.c callback flow lines 517-540 */
/* --- BEGIN D3DKMT CALLBACK FLOW --- */
static struct vulkan_instance *d3dkmt_vulkan_instance;

static void d3dkmt_init_vulkan(void)
{
    static const struct vulkan_instance_extensions extensions =
    {
        .has_VK_KHR_get_physical_device_properties2 = 1,
        .has_VK_KHR_external_memory_capabilities = 1,
    };

    d3dkmt_init_guard_enter();
    pthread_cleanup_push( d3dkmt_init_guard_cleanup, NULL );

    d3dkmt_vulkan_instance = vulkan_instance_create( &extensions );
    if (!d3dkmt_vulkan_instance) WARN( "Failed to create the vulkan instance\n" );

    pthread_cleanup_pop( 1 );
}

static struct vulkan_instance *get_d3dkmt_vulkan_instance(void)
{
    static pthread_once_t once = PTHREAD_ONCE_INIT;
    if (is_d3dkmt_init_in_progress()) return NULL;
    pthread_once( &once, d3dkmt_init_vulkan );
    return d3dkmt_vulkan_instance;
}

/* --- END D3DKMT CALLBACK FLOW --- */

/* Source 4: vulkan.c callback flow lines 4118-4205 */
/* --- BEGIN VULKAN CALLBACK FLOW --- */
static void vulkan_init_once(void)
{
    struct vulkan_instance_extensions extensions = {0};
    VkExtensionProperties *properties = NULL;
    uint32_t count = 0;
    VkResult res = VK_SUCCESS;
    const char *env;

    vulkan_init_guard_enter();
    pthread_cleanup_push( vulkan_init_guard_cleanup, NULL );

    env = getenv( "WINE_DISABLE_FULLSCREEN_HACK" );
    fshack_enabled = !env || !atoi( env );

#ifdef SONAME_LIBVULKAN
    vulkan_handle = dlopen( SONAME_LIBVULKAN, RTLD_NOW );
    if (!vulkan_handle) ERR( "Failed to load %s\n", SONAME_LIBVULKAN );
#else
    ERR( "Wine was built without Vulkan support.\n" );
#endif

    if (vulkan_handle)
    {
        if (!(p_vkGetDeviceProcAddr = dlsym( vulkan_handle, "vkGetDeviceProcAddr" )))
        {
            ERR( "Failed to find vkGetDeviceProcAddr\n" );
            dlclose( vulkan_handle );
            vulkan_handle = NULL;
        }
        else if (!(p_vkGetInstanceProcAddr = dlsym( vulkan_handle, "vkGetInstanceProcAddr" )))
        {
            ERR( "Failed to find vkGetInstanceProcAddr\n" );
            dlclose( vulkan_handle );
            vulkan_handle = NULL;
        }
        else
        {
            driver_funcs = &lazydrv_funcs;
            vulkan_funcs.p_vkGetInstanceProcAddr = p_vkGetInstanceProcAddr;
            vulkan_funcs.p_vkGetDeviceProcAddr = p_vkGetDeviceProcAddr;

#define LOAD_FUNCPTR( f ) p_##f = (PFN_##f)p_vkGetInstanceProcAddr( NULL, #f );
            LOAD_FUNCPTR( vkCreateInstance );
            LOAD_FUNCPTR( vkEnumerateInstanceExtensionProperties );
#undef LOAD_FUNCPTR

            do
            {
                free( properties );
                properties = NULL;
                if ((res = p_vkEnumerateInstanceExtensionProperties( NULL, &count, NULL ))) break;
                if (!count || !(properties = malloc( count * sizeof(*properties) ))) { res = VK_ERROR_OUT_OF_HOST_MEMORY; break; }
            } while ((res = p_vkEnumerateInstanceExtensionProperties( NULL, &count, properties ) == VK_INCOMPLETE));

            if (!res)
            {
                TRACE( "Host instance extensions:\n" );
                for (uint32_t i = 0; i < count; i++)
                {
                    const char *extension = properties[i].extensionName;
#define USE_VK_EXT(x)                           \
                    if (!strcmp( extension, #x ))           \
                    {                                       \
                        extensions.has_ ## x = 1;           \
                        TRACE( "  - %s\n", extension );     \
                    } else
                    ALL_VK_INSTANCE_EXTS
#undef USE_VK_EXT
                    WARN( "Extension %s is not supported.\n", debugstr_a(extension) );
                }
                vulkan_funcs.host_extensions = extensions;

                /* map host instance extensions for VK_KHR_win32_surface */
                driver_funcs->p_map_instance_extensions( &extensions );

                /* filter out unsupported client instance extensions */
#define USE_VK_EXT(x) vulkan_funcs.client_extensions.has_ ## x = extensions.has_ ## x;
                ALL_VK_CLIENT_INSTANCE_EXTS
#undef USE_VK_EXT
            }
        }
    }

    if (res) ERR( "Failed to initialize instance extensions, res %d\n", res );
    free( properties );

    pthread_cleanup_pop( 1 );
}

/* --- END VULKAN CALLBACK FLOW --- */

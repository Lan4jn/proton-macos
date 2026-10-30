/*
 * System parameters functions
 *
 * Copyright 1994 Alexandre Julliard
 * Copyright 2019 Zhiyi Zhang for CodeWeavers
 * Copyright 2021 Jacek Caban for CodeWeavers
 *
 * This library is free software; you can redistribute it and/or
 * modify it under the terms of the GNU Lesser General Public
 * License as published by the Free Software Foundation; either
 * version 2.1 of the License, or (at your option) any later version.
 *
 * This library is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 * Lesser General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public
 * License along with this library; if not, write to the Free Software
 * Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA 02110-1301, USA
 */

#if 0
#pragma makedep unix
#endif

#include <pthread.h>
#include <assert.h>

#include "ntstatus.h"
#define WIN32_NO_STATUS
#include "ntgdi_private.h"
#include "ntuser_private.h"
#include "winreg.h"
#include "cfgmgr32.h"
#include "d3dkmdt.h"
#include "wine/wingdi16.h"
#include "wine/server.h"

WINE_DEFAULT_DEBUG_CHANNEL(system);

#define WINE_ENUM_PHYSICAL_SETTINGS  ((DWORD) -3)

static LONG dpi_context; /* process DPI awareness context */

static HKEY video_key, enum_key, control_key, config_key, volatile_base_key;

static const char devicemap_video_keyA[] = "\\Registry\\Machine\\HARDWARE\\DEVICEMAP\\VIDEO";
static const char enum_keyA[] = "\\Registry\\Machine\\System\\CurrentControlSet\\Enum";
static const char control_keyA[] = "\\Registry\\Machine\\System\\CurrentControlSet\\Control";
static const char config_keyA[] = "\\Registry\\Machine\\System\\CurrentControlSet\\Hardware Profiles\\Current";
static const char directx_keyA[] = "\\Registry\\Machine\\Software\\Microsoft\\DirectX";

static const char devpropkey_gpu_uuidA[] = "Properties\\{233A9EF3-AFC4-4ABD-B564-C32F21F1535C}\\0002";
static const char devpropkey_gpu_luidA[] = "Properties\\{60B193CB-5276-4D0F-96FC-F173ABAD3EC6}\\0002";
static const char devpkey_device_driver_date[] = "Properties\\{A8B865DD-2E3D-4094-AD97-E593A70C75D6}\\0002";
static const char devpkey_device_driver_version[] = "Properties\\{A8B865DD-2E3D-4094-AD97-E593A70C75D6}\\0003";
static const char devpkey_device_driver_desc[] = "Properties\\{A8B865DD-2E3D-4094-AD97-E593A70C75D6}\\0004";
static const char devpkey_device_matching_device_id[] = "Properties\\{A8B865DD-2E3D-4094-AD97-E593A70C75D6}\\0008";
static const char devpkey_device_driver_provider[] = "Properties\\{A8B865DD-2E3D-4094-AD97-E593A70C75D6}\\0009";
static const char devpkey_device_bus_number[] = "Properties\\{A45C254E-DF1C-4EFD-8020-67D146A850E0}\\0017";
static const char devpkey_device_removal_policy[] = "Properties\\{A45C254E-DF1C-4EFD-8020-67D146A850E0}\\0021";
static const char devpropkey_device_ispresentA[] = "Properties\\{540B947E-8B40-45BC-A8A2-6A0B894CBDA2}\\0005";
static const char devpropkey_monitor_gpu_luidA[] = "Properties\\{CA085853-16CE-48AA-B114-DE9C72334223}\\0001";
static const char devpropkey_monitor_output_idA[] = "Properties\\{CA085853-16CE-48AA-B114-DE9C72334223}\\0002";
static const char wine_devpropkey_monitor_rcworkA[] = "Properties\\{233a9ef3-afc4-4abd-b564-c32f21f1535b}\\0004";
static const char wine_devpropkey_monitor_hdr_enabledA[] = "Properties\\{233a9ef3-afc4-4abd-b564-c32f21f1535b}\\0006";

static const WCHAR linkedW[] = {'L','i','n','k','e','d',0};
static const WCHAR symbolic_link_valueW[] =
    {'S','y','m','b','o','l','i','c','L','i','n','k','V','a','l','u','e',0};
static const WCHAR state_flagsW[] = {'S','t','a','t','e','F','l','a','g','s',0};
static const WCHAR hardware_idW[] = {'H','a','r','d','w','a','r','e','I','D',0};
static const WCHAR device_descW[] = {'D','e','v','i','c','e','D','e','s','c',0};
static const WCHAR driver_descW[] = {'D','r','i','v','e','r','D','e','s','c',0};
static const WCHAR yesW[] = {'Y','e','s',0};
static const WCHAR noW[] = {'N','o',0};
static const WCHAR modesW[] = {'M','o','d','e','s',0};
static const WCHAR mode_countW[] = {'M','o','d','e','C','o','u','n','t',0};
static const WCHAR dpiW[] = {'D','p','i',0};
static const WCHAR depthW[] = {'D','e','p','t','h',0};
static const WCHAR physicalW[] = {'P','h','y','s','i','c','a','l',0};

static const char  guid_devclass_displayA[] = "{4D36E968-E325-11CE-BFC1-08002BE10318}";
static const WCHAR guid_devclass_displayW[] =
    {'{','4','D','3','6','E','9','6','8','-','E','3','2','5','-','1','1','C','E','-',
     'B','F','C','1','-','0','8','0','0','2','B','E','1','0','3','1','8','}',0};
static const char  guid_devclass_monitorA[] = "{4D36E96E-E325-11CE-BFC1-08002BE10318}";
static const WCHAR guid_devclass_monitorW[] =
    {'{','4','D','3','6','E','9','6','E','-','E','3','2','5','-','1','1','C','E','-',
     'B','F','C','1','-','0','8','0','0','2','B','E','1','0','3','1','8','}',0};

static const char guid_devinterface_display_adapterA[] = "{5B45201D-F2F2-4F3B-85BB-30FF1F953599}";
static const char guid_display_device_arrivalA[] = "{1CA05180-A699-450A-9A0C-DE4FBE3DDD89}";
static const char guid_devinterface_monitorA[] = "{E6F07B5F-EE97-4A90-B076-33F57BF4EAA7}";

static const UINT32 qdc_retrieve_flags_mask = QDC_ALL_PATHS | QDC_ONLY_ACTIVE_PATHS | QDC_DATABASE_CURRENT;

#define NEXT_DEVMODEW(mode) ((DEVMODEW *)((char *)((mode) + 1) + (mode)->dmDriverExtra))

struct gpu
{
    LONG refcount;
    struct list entry;
    char path[MAX_PATH];
    WCHAR name[128];
    char guid[39];
    LUID luid;
    UINT index;
    GUID uuid;
    UINT source_count;
};

struct source
{
    LONG refcount;
    struct list entry;
    char path[MAX_PATH];
    unsigned int id;
    struct gpu *gpu;
    HKEY key;
    UINT dpi;
    UINT depth; /* emulated depth */
    UINT state_flags;
    UINT monitor_count;
    UINT mode_count;
    DEVMODEW current;
    DEVMODEW physical;
    DEVMODEW *modes;
};

#define MONITOR_INFO_HAS_MONITOR_ID 0x00000001
#define MONITOR_INFO_HAS_MONITOR_NAME 0x00000002
#define MONITOR_INFO_HAS_PREFERRED_MODE 0x00000004
struct edid_monitor_info
{
    unsigned int flags;
    /* MONITOR_INFO_HAS_MONITOR_ID */
    unsigned short manufacturer, product_code;
    char monitor_id_string[8];
    /* MONITOR_INFO_HAS_MONITOR_NAME */
    WCHAR monitor_name[14];
    /* MONITOR_INFO_HAS_PREFERRED_MODE */
    unsigned int preferred_width, preferred_height;
};

struct monitor
{
    LONG refcount;
    struct list entry;
    char path[MAX_PATH];
    struct source *source;
    HANDLE handle;
    unsigned int id;
    unsigned int output_id;
    RECT rc_work;
    BOOL is_clone;
    struct edid_monitor_info edid_info;
    BOOL hdr_enabled;
};

static struct list gpus = LIST_INIT(gpus);
static struct list sources = LIST_INIT(sources);
static struct list monitors = LIST_INIT(monitors);
static INT64 last_query_display_time;
static UINT64 monitor_update_serial;
static pthread_mutex_t display_lock = PTHREAD_MUTEX_INITIALIZER;

static BOOL emulate_modelist = TRUE;
static BOOL emulate_modeset = TRUE;
static UINT limit_resolutions = 0;
BOOL decorated_mode = TRUE;
UINT64 thunk_lock_callback = 0;

#define VIRTUAL_HMONITOR ((HMONITOR)(UINT_PTR)(0x10000 + 1))
static struct monitor virtual_monitor =
{
    .handle = VIRTUAL_HMONITOR,
    .rc_work.right = 1024,
    .rc_work.bottom = 768,
};

/* the various registry keys that are used to store parameters */
enum parameter_key
{
    COLORS_KEY,
    DESKTOP_KEY,
    KEYBOARD_KEY,
    MOUSE_KEY,
    METRICS_KEY,
    SOUND_KEY,
    VERSION_KEY,
    SHOWSOUNDS_KEY,
    KEYBOARDPREF_KEY,
    SCREENREADER_KEY,
    AUDIODESC_KEY,
    NB_PARAM_KEYS
};

static const char *parameter_key_names[NB_PARAM_KEYS] =
{
    "Control Panel\\Colors",
    "Control Panel\\Desktop",
    "Control Panel\\Keyboard",
    "Control Panel\\Mouse",
    "Control Panel\\Desktop\\WindowMetrics",
    "Control Panel\\Sound",
    "Software\\Microsoft\\Windows NT\\CurrentVersion\\Windows",
    "Control Panel\\Accessibility\\ShowSounds",
    "Control Panel\\Accessibility\\Keyboard Preference",
    "Control Panel\\Accessibility\\Blind Access",
    "Control Panel\\Accessibility\\AudioDescription",
};

/* System parameters storage */
union sysparam_all_entry;

struct sysparam_entry
{
    BOOL             (*get)( union sysparam_all_entry *entry, UINT int_param, void *ptr_param, UINT dpi );
    BOOL             (*set)( union sysparam_all_entry *entry, UINT int_param, void *ptr_param, UINT flags );
    BOOL             (*init)( union sysparam_all_entry *entry );
    enum parameter_key base_key;
    const char        *regval;
    enum parameter_key mirror_key;
    const char        *mirror;
    BOOL               loaded;
};

struct sysparam_uint_entry
{
    struct sysparam_entry hdr;
    UINT                  val;
};

struct sysparam_bool_entry
{
    struct sysparam_entry hdr;
    BOOL                  val;
};

struct sysparam_dword_entry
{
    struct sysparam_entry hdr;
    DWORD                 val;
};

struct sysparam_rgb_entry
{
    struct sysparam_entry hdr;
    COLORREF              val;
    HBRUSH                brush;
    HPEN                  pen;
};

struct sysparam_binary_entry
{
    struct sysparam_entry hdr;
    void                 *ptr;
    size_t                size;
};

struct sysparam_path_entry
{
    struct sysparam_entry hdr;
    WCHAR                *path;
};

struct sysparam_font_entry
{
    struct sysparam_entry hdr;
    UINT                  weight;
    LOGFONTW              val;
    WCHAR                 fullname[LF_FACESIZE];
};

struct sysparam_pref_entry
{
    struct sysparam_entry hdr;
    union sysparam_all_entry *parent;
    UINT                  offset;
    UINT                  mask;
};

union sysparam_all_entry
{
    struct sysparam_entry        hdr;
    struct sysparam_uint_entry   uint;
    struct sysparam_bool_entry   boolean;
    struct sysparam_dword_entry  dword;
    struct sysparam_rgb_entry    rgb;
    struct sysparam_binary_entry bin;
    struct sysparam_path_entry   path;
    struct sysparam_font_entry   font;
    struct sysparam_pref_entry   pref;
};

static UINT system_dpi;
static RECT work_area;
static DWORD process_layout = ~0u;

static HDC display_dc;
static pthread_mutex_t display_dc_lock = PTHREAD_MUTEX_INITIALIZER;

static pthread_mutex_t user_mutex;
static unsigned int user_lock_thread, user_lock_rec;

#define GAMMA_RAMP_SIZE 256

static WORD gamma_ramp_i[GAMMA_RAMP_SIZE * 3];
static float gamma_ramp[GAMMA_RAMP_SIZE * 4];
static LONG gamma_serial;

BOOL get_float_gamma_ramp( float *data, LONG *serial )
{
    pthread_mutex_lock( &display_lock );
    if ((*serial = gamma_serial)) memcpy( data, gamma_ramp, sizeof(gamma_ramp) );
    pthread_mutex_unlock( &display_lock );
    return !!*serial;
}

BOOL get_global_gamma_ramp( void *data )
{
    pthread_mutex_lock( &display_lock );
    memcpy( data, gamma_ramp_i, sizeof(gamma_ramp_i) );
    pthread_mutex_unlock( &display_lock );
    return TRUE;
}

BOOL set_global_gamma_ramp( void *data )
{
    const WORD *ramp = data;
    int i;

    pthread_mutex_lock( &display_lock );

    if (!memcmp( gamma_ramp_i, ramp, sizeof(gamma_ramp_i) )) goto done;
    for (i = 0; i < GAMMA_RAMP_SIZE; ++i)
    {
        gamma_ramp[i * 4] = ramp[i] / 65535.f;
        gamma_ramp[i * 4 + 1] = ramp[i + GAMMA_RAMP_SIZE] / 65535.f;
        gamma_ramp[i * 4 + 2] = ramp[i + 2 * GAMMA_RAMP_SIZE] / 65535.f;
    }
    memcpy( gamma_ramp_i, ramp, sizeof(gamma_ramp_i) );
    if (!++gamma_serial) gamma_serial = 1;
    TRACE( "new gamma serial: %u\n", gamma_serial );

done:
    pthread_mutex_unlock( &display_lock );
    return TRUE;
}

static void init_default_gamma_ramp(void)
{
    unsigned int i;

    for (i = 0; i < GAMMA_RAMP_SIZE; ++i)
    {
        int default_value = i * 65535 / (GAMMA_RAMP_SIZE - 1);
        gamma_ramp_i[i] = default_value;
        gamma_ramp_i[i + GAMMA_RAMP_SIZE] = default_value;
        gamma_ramp_i[i + 2 * GAMMA_RAMP_SIZE] = default_value;
        gamma_ramp[i * 4] = gamma_ramp_i[i] / 65535.f;
        gamma_ramp[i * 4 + 1] = gamma_ramp_i[i + GAMMA_RAMP_SIZE] / 65535.f;
        gamma_ramp[i * 4 + 2] = gamma_ramp_i[i + 2 * GAMMA_RAMP_SIZE] / 65535.f;
    }
}

void user_lock(void)
{
    pthread_mutex_lock( &user_mutex );
    if (!user_lock_rec++) user_lock_thread = GetCurrentThreadId();
}

void user_unlock(void)
{
    if (!--user_lock_rec) user_lock_thread = 0;
    pthread_mutex_unlock( &user_mutex );
}

void user_check_not_lock(void)
{
    if (user_lock_thread == GetCurrentThreadId())
    {
        ERR( "BUG: holding USER lock\n" );
        assert( 0 );
    }
}

static HANDLE get_display_device_init_mutex( void )
{
    WCHAR bufferW[256];
    UNICODE_STRING name = {.Buffer = bufferW};
    OBJECT_ATTRIBUTES attr;
    char buffer[256];
    HANDLE mutex;

    snprintf( buffer, ARRAY_SIZE(buffer), "\\Sessions\\%u\\BaseNamedObjects\\display_device_init",
              NtCurrentTeb()->Peb->SessionId );
    name.MaximumLength = asciiz_to_unicode( bufferW, buffer );
    name.Length = name.MaximumLength - sizeof(WCHAR);

    InitializeObjectAttributes( &attr, &name, OBJ_OPENIF, NULL, NULL );
    if (NtCreateMutant( &mutex, MUTEX_ALL_ACCESS, &attr, FALSE ) < 0) return 0;
    NtWaitForSingleObject( mutex, FALSE, NULL );
    return mutex;
}

static void release_display_device_init_mutex( HANDLE mutex )
{
    NtReleaseMutant( mutex, NULL );
    NtClose( mutex );
}

static struct gpu *gpu_acquire( struct gpu *gpu )
{
    UINT ref = InterlockedIncrement( &gpu->refcount );
    TRACE( "gpu %p increasing refcount to %u\n", gpu, ref );
    return gpu;
}

static void gpu_release( struct gpu *gpu )
{
    UINT ref = InterlockedDecrement( &gpu->refcount );
    TRACE( "gpu %p decreasing refcount to %u\n", gpu, ref );
    if (!ref) free( gpu );
}

static struct source *source_acquire( struct source *source )
{
    UINT ref = InterlockedIncrement( &source->refcount );
    TRACE( "source %p increasing refcount to %u\n", source, ref );
    return source;
}

static void source_release( struct source *source )
{
    UINT ref = InterlockedDecrement( &source->refcount );
    TRACE( "source %p decreasing refcount to %u\n", source, ref );
    if (!ref)
    {
        if (source->key) NtClose( source->key );
        gpu_release( source->gpu );
        free( source->modes );
        free( source );
    }
}

static void monitor_release( struct monitor *monitor )
{
    UINT ref = InterlockedDecrement( &monitor->refcount );
    TRACE( "monitor %p decreasing refcount to %u\n", monitor, ref );
    if (!ref)
    {
        if (monitor->source) source_release( monitor->source );
        free( monitor );
    }
}

C_ASSERT(sizeof(DEVMODEW) - offsetof(DEVMODEW, dmFields) == 0x94);

static void get_monitor_info_from_edid( struct edid_monitor_info *info, const unsigned char *edid, unsigned int edid_len )
{
    unsigned int i, j;
    unsigned short w;
    unsigned char d;
    const char *s;

    info->flags = 0;
    if (!edid || edid_len < 128) return;

    w = (edid[8] << 8) | edid[9]; /* Manufacturer ID, big endian. */
    for (i = 0; i < 3; ++i)
    {
        d = w & 0x1f;
        if (!d || d - 1 > 'Z' - 'A') return;
        info->monitor_id_string[2 - i] = 'A' + d - 1;
        w >>= 5;
    }
    if (w) return;
    w = edid[10] | (edid[11] << 8); /* Product code, little endian. */
    info->manufacturer = *(unsigned short *)(edid + 8);
    info->product_code = w;
    snprintf( info->monitor_id_string + 3, sizeof(info->monitor_id_string) - 3, "%04X", w );
    info->flags = MONITOR_INFO_HAS_MONITOR_ID;
    TRACE( "Monitor id %s.\n", info->monitor_id_string );

    for (i = 0; i < 4; ++i)
    {
        if (edid[54 + i * 18] || edid[54 + i * 18 + 1])
        {
            /* Detailed timing descriptor. */
            if (info->flags & MONITOR_INFO_HAS_PREFERRED_MODE) continue;
            info->preferred_width = edid[54 + i * 18 + 2] | ((UINT32)(edid[54 + i * 18 + 4] & 0xf0) << 4);
            info->preferred_height = edid[54 + i * 18 + 5] | ((UINT32)(edid[54 + i * 18 + 7] & 0xf0) << 4);
            if (info->preferred_width && info->preferred_height)
                info->flags |= MONITOR_INFO_HAS_PREFERRED_MODE;
            continue;
        }
        if (edid[54 + i * 18 + 3] != 0xfc) continue;
        /* "Display name" ASCII descriptor. */
        s = (const char *)&edid[54 + i * 18 + 5];
        for (j = 0; s[j] && j < 13; ++j)
            info->monitor_name[j] = s[j];
        while (j && isspace(s[j - 1])) --j;
        info->monitor_name[j] = 0;
        info->flags |= MONITOR_INFO_HAS_MONITOR_NAME;
        break;
    }
}

static const char *debugstr_devmodew( const DEVMODEW *devmode )
{
    char position[32] = {0};
    if (devmode->dmFields & DM_POSITION) snprintf( position, sizeof(position), " at %s", wine_dbgstr_point( (POINT *)&devmode->dmPosition ) );
    return wine_dbg_sprintf( "%ux%u %ubits %uHz rotated %u degrees %sstretched %sinterlaced%s",
                             devmode->dmPelsWidth, devmode->dmPelsHeight, devmode->dmBitsPerPel,
                             devmode->dmDisplayFrequency, devmode->dmDisplayOrientation * 90,
                             devmode->dmDisplayFixedOutput == DMDFO_STRETCH ? "" : "un",
                             devmode->dmDisplayFlags & DM_INTERLACED ? "" : "non-",
                             position );
}

static UINT devmode_get( const DEVMODEW *mode, UINT field )
{
    switch (field)
    {
    case DM_DISPLAYORIENTATION: return mode->dmFields & DM_DISPLAYORIENTATION ? mode->dmDisplayOrientation : 0;
    case DM_BITSPERPEL: return mode->dmFields & DM_BITSPERPEL ? mode->dmBitsPerPel : 0;
    case DM_PELSWIDTH: return mode->dmFields & DM_PELSWIDTH ? mode->dmPelsWidth : 0;
    case DM_PELSHEIGHT: return mode->dmFields & DM_PELSHEIGHT ? mode->dmPelsHeight : 0;
    case DM_DISPLAYFLAGS: return mode->dmFields & DM_DISPLAYFLAGS ? mode->dmDisplayFlags : 0;
    case DM_DISPLAYFREQUENCY: return mode->dmFields & DM_DISPLAYFREQUENCY ? mode->dmDisplayFrequency : 0;
    case DM_DISPLAYFIXEDOUTPUT: return mode->dmFields & DM_DISPLAYFIXEDOUTPUT ? mode->dmDisplayFixedOutput : 0;
    }
    return 0;
}

static BOOL is_detached_mode( const DEVMODEW *mode )
{
    return mode->dmFields & DM_POSITION &&
           mode->dmFields & DM_PELSWIDTH &&
           mode->dmFields & DM_PELSHEIGHT &&
           mode->dmPelsWidth == 0 &&
           mode->dmPelsHeight == 0;
}

static BOOL write_source_mode( HKEY hkey, UINT index, const DEVMODEW *mode )
{
    WCHAR bufferW[MAX_PATH] = {0};

    assert( index == ENUM_CURRENT_SETTINGS || index == ENUM_REGISTRY_SETTINGS || index == WINE_ENUM_PHYSICAL_SETTINGS );

    if (index == ENUM_CURRENT_SETTINGS) asciiz_to_unicode( bufferW, "Current" );
    else if (index == ENUM_REGISTRY_SETTINGS) asciiz_to_unicode( bufferW, "Registry" );
    else if (index == WINE_ENUM_PHYSICAL_SETTINGS) asciiz_to_unicode( bufferW, "Physical" );
    else return FALSE;

    return set_reg_value( hkey, bufferW, REG_BINARY, &mode->dmFields, sizeof(*mode) - offsetof(DEVMODEW, dmFields) );
}

static BOOL read_source_mode( HKEY hkey, UINT index, DEVMODEW *mode )
{
    char value_buf[offsetof(KEY_VALUE_PARTIAL_INFORMATION, Data[sizeof(*mode)])];
    KEY_VALUE_PARTIAL_INFORMATION *value = (void *)value_buf;
    const char *key;

    assert( index == ENUM_CURRENT_SETTINGS || index == ENUM_REGISTRY_SETTINGS || index == WINE_ENUM_PHYSICAL_SETTINGS );

    if (index == ENUM_CURRENT_SETTINGS) key = "Current";
    else if (index == ENUM_REGISTRY_SETTINGS) key = "Registry";
    else if (index == WINE_ENUM_PHYSICAL_SETTINGS) key = "Physical";
    else return FALSE;

    if (!query_reg_ascii_value( hkey, key, value, sizeof(value_buf) )) return FALSE;
    memcpy( &mode->dmFields, value->Data, offsetof(DEVMODEW, dmICMMethod) - offsetof(DEVMODEW, dmFields) );
    return TRUE;
}

static BOOL source_get_registry_settings( const struct source *source, DEVMODEW *mode )
{
    BOOL ret = FALSE;
    HANDLE mutex;
    HKEY hkey;

    mutex = get_display_device_init_mutex();

    if (!(hkey = reg_open_ascii_key( config_key, source->path ))) ret = FALSE;
    else
    {
        ret = read_source_mode( hkey, ENUM_REGISTRY_SETTINGS, mode );
        NtClose( hkey );
    }

    release_display_device_init_mutex( mutex );
    return ret;
}

static BOOL source_set_registry_settings( const struct source *source, const DEVMODEW *mode )
{
    HANDLE mutex;
    HKEY hkey;
    BOOL ret;

    mutex = get_display_device_init_mutex();

    if (!(hkey = reg_open_ascii_key( config_key, source->path ))) ret = FALSE;
    else
    {
        ret = write_source_mode( hkey, ENUM_REGISTRY_SETTINGS, mode );
        NtClose( hkey );
    }

    release_display_device_init_mutex( mutex );
    return ret;
}

static BOOL source_get_current_settings( const struct source *source, DEVMODEW *mode )
{
    memcpy( &mode->dmFields, &source->current.dmFields, offsetof(DEVMODEW, dmICMMethod) - offsetof(DEVMODEW, dmFields) );
    if (source->depth) mode->dmBitsPerPel = source->depth;
    return TRUE;
}

static BOOL source_set_current_settings( const struct source *source, const DEVMODEW *mode )
{
    HANDLE mutex;
    HKEY hkey;
    BOOL ret;

    mutex = get_display_device_init_mutex();

    if (!(hkey = reg_open_ascii_key( config_key, source->path ))) ret = FALSE;
    else
    {
        ret = write_source_mode( hkey, ENUM_CURRENT_SETTINGS, mode );
        if (ret) set_reg_value( hkey, depthW, REG_DWORD, &mode->dmBitsPerPel, sizeof(mode->dmBitsPerPel) );
        NtClose( hkey );
    }

    release_display_device_init_mutex( mutex );
    return ret;
}

static int mode_compare(const void *p1, const void *p2)
{
    BOOL a_interlaced, b_interlaced, a_stretched, b_stretched;
    DWORD a_width, a_height, b_width, b_height;
    const DEVMODEW *a = p1, *b = p2;
    int ret;

    /* Depth in descending order */
    if ((ret = b->dmBitsPerPel - a->dmBitsPerPel)) return ret;

    /* Use the width and height in landscape mode for comparison */
    if (a->dmDisplayOrientation == DMDO_DEFAULT || a->dmDisplayOrientation == DMDO_180)
    {
        a_width = a->dmPelsWidth;
        a_height = a->dmPelsHeight;
    }
    else
    {
        a_width = a->dmPelsHeight;
        a_height = a->dmPelsWidth;
    }

    if (b->dmDisplayOrientation == DMDO_DEFAULT || b->dmDisplayOrientation == DMDO_180)
    {
        b_width = b->dmPelsWidth;
        b_height = b->dmPelsHeight;
    }
    else
    {
        b_width = b->dmPelsHeight;
        b_height = b->dmPelsWidth;
    }

    /* Width in ascending order */
    if ((ret = a_width - b_width)) return ret;

    /* Height in ascending order */
    if ((ret = a_height - b_height)) return ret;

    /* Frequency in descending order */
    if ((ret = b->dmDisplayFrequency - a->dmDisplayFrequency)) return ret;

    /* Orientation in ascending order */
    if ((ret = a->dmDisplayOrientation - b->dmDisplayOrientation)) return ret;

    if (!(a->dmFields & DM_DISPLAYFLAGS)) a_interlaced = FALSE;
    else a_interlaced = !!(a->dmDisplayFlags & DM_INTERLACED);
    if (!(b->dmFields & DM_DISPLAYFLAGS)) b_interlaced = FALSE;
    else b_interlaced = !!(b->dmDisplayFlags & DM_INTERLACED);

    /* Interlaced in ascending order */
    if ((ret = a_interlaced - b_interlaced)) return ret;

    if (!(a->dmFields & DM_DISPLAYFIXEDOUTPUT)) a_stretched = FALSE;
    else a_stretched = a->dmDisplayFixedOutput == DMDFO_STRETCH;
    if (!(b->dmFields & DM_DISPLAYFIXEDOUTPUT)) b_stretched = FALSE;
    else b_stretched = b->dmDisplayFixedOutput == DMDFO_STRETCH;

    /* Stretched in ascending order */
    if ((ret = a_stretched - b_stretched)) return ret;

    return 0;
}

static unsigned int query_reg_subkey_value( HKEY hkey, const char *name, KEY_VALUE_PARTIAL_INFORMATION *value, unsigned int size )
{
    HKEY subkey;

    if (!(subkey = reg_open_ascii_key( hkey, name ))) return 0;
    size = query_reg_value( subkey, NULL, value, size );
    NtClose( subkey );
    return size;
}

static BOOL read_source_from_registry( unsigned int index, struct source *source, char *gpu_path )
{
    char buffer[4096];
    KEY_VALUE_PARTIAL_INFORMATION *value = (void *)buffer;
    WCHAR *value_str = (WCHAR *)value->Data;
    DWORD i, size;
    HKEY hkey;

    if (!enum_key && !(enum_key = reg_open_ascii_key( NULL, enum_keyA )))
        return FALSE;

    /* Find source */
    snprintf( buffer, sizeof(buffer), "\\Device\\Video%d", index );
    size = query_reg_ascii_value( video_key, buffer, value, sizeof(buffer) );
    if (!size || value->Type != REG_SZ) return FALSE;

    /* DeviceKey */
    size = sizeof("\\Registry\\Machine");
    if (value->DataLength / sizeof(WCHAR) <= size) return FALSE;
    for (i = 0; i < value->DataLength / sizeof(WCHAR) - size; i++) source->path[i] = value_str[size + i];
    if (!(hkey = reg_open_ascii_key( config_key, source->path ))) return FALSE;

    /* StateFlags */
    if (query_reg_ascii_value( hkey, "StateFlags", value, sizeof(buffer) ) && value->Type == REG_DWORD)
        source->state_flags = *(const DWORD *)value->Data;

    /* Dpi */
    if (query_reg_ascii_value( hkey, "Dpi", value, sizeof(buffer) ) && value->Type == REG_DWORD)
        source->dpi = *(DWORD *)value->Data;

    /* Depth */
    if (query_reg_ascii_value( hkey, "Depth", value, sizeof(buffer) ) && value->Type == REG_DWORD)
        source->depth = *(const DWORD *)value->Data;

    /* ModeCount */
    if (query_reg_ascii_value( hkey, "ModeCount", value, sizeof(buffer) ) && value->Type == REG_DWORD)
        source->mode_count = *(const DWORD *)value->Data;

    /* Modes */
    size = offsetof( KEY_VALUE_PARTIAL_INFORMATION, Data[(source->mode_count + 1) * sizeof(*source->modes)] );
    if (!(value = malloc( size )) || !query_reg_ascii_value( hkey, "Modes", value, size )) free( value );
    else
    {
        source->modes = (DEVMODEW *)value;
        source->mode_count = value->DataLength / sizeof(*source->modes);
        memmove( source->modes, value->Data, value->DataLength );
        memset( source->modes + source->mode_count, 0, sizeof(*source->modes) ); /* extra empty mode for easier iteration */
        qsort( source->modes, source->mode_count, sizeof(*source->modes), mode_compare );
    }
    value = (void *)buffer;

    /* Cache current and physical display modes */
    if (read_source_mode( hkey, ENUM_CURRENT_SETTINGS, &source->current ))
        source->current.dmSize = sizeof(source->current);
    source->physical = source->current;
    if (read_source_mode( hkey, WINE_ENUM_PHYSICAL_SETTINGS, &source->physical ))
        source->physical.dmSize = sizeof(source->physical);

    /* DeviceID */
    size = query_reg_ascii_value( hkey, "GPUID", value, sizeof(buffer) );
    NtClose( hkey );
    if (!size || value->Type != REG_SZ || !source->mode_count || !source->modes) return FALSE;

    for (i = 0; i < value->DataLength / sizeof(WCHAR); i++) gpu_path[i] = value_str[i];
    return TRUE;
}

static BOOL read_monitor_from_registry( struct monitor *monitor )
{
    char buffer[4096];
    KEY_VALUE_PARTIAL_INFORMATION *value = (void *)buffer;
    HKEY hkey, subkey;
    DWORD size;

    if (!(hkey = reg_open_ascii_key( enum_key, monitor->path ))) return FALSE;

    /* Output ID */
    size = query_reg_subkey_value( hkey, devpropkey_monitor_output_idA,
                                   value, sizeof(buffer) );
    if (size != sizeof(monitor->output_id))
    {
        NtClose( hkey );
        return FALSE;
    }
    monitor->output_id = *(const unsigned int *)value->Data;

    /* rc_work, WINE_DEVPROPKEY_MONITOR_RCWORK */
    size = query_reg_subkey_value( hkey, wine_devpropkey_monitor_rcworkA,
                                   value, sizeof(buffer) );
    if (size != sizeof(monitor->rc_work))
    {
        NtClose( hkey );
        return FALSE;
    }
    monitor->rc_work = *(const RECT *)value->Data;

    /* EDID */
    if ((subkey = reg_open_ascii_key( hkey, "Device Parameters" )))
    {
        if (query_reg_ascii_value( subkey, "EDID", value, sizeof(buffer) ))
            get_monitor_info_from_edid( &monitor->edid_info, value->Data, value->DataLength );
        NtClose( subkey );
    }

    /* WINE_DEVPROPKEY_MONITOR_HDR_ENABLED */
    size = query_reg_subkey_value( hkey, wine_devpropkey_monitor_hdr_enabledA,
                                   value, sizeof(buffer) );
    if (size != sizeof(monitor->hdr_enabled))
    {
        NtClose( hkey );
        return FALSE;
    }
    monitor->hdr_enabled = *(const BOOL *)value->Data;

    NtClose( hkey );
    return TRUE;
}

static BOOL read_source_monitor_path( HKEY hkey, UINT index, char *path )
{
    char buffer[4096];
    KEY_VALUE_PARTIAL_INFORMATION *value = (void *)buffer;
    WCHAR *value_str = (WCHAR *)value->Data;
    DWORD size;
    UINT i;

    snprintf( buffer, sizeof(buffer), "MonitorID%u", index );
    size = query_reg_ascii_value( hkey, buffer, value, sizeof(buffer) );
    if (!size || value->Type != REG_SZ) return FALSE;

    for (i = 0; i < value->DataLength / sizeof(WCHAR); i++) path[i] = value_str[i];
    return TRUE;
}

static void reg_empty_key( HKEY root, const char *key_name, BOOL subkeys_only )
{
    char buffer[4096];
    KEY_NODE_INFORMATION *key = (KEY_NODE_INFORMATION *)buffer;
    KEY_VALUE_FULL_INFORMATION *value = (KEY_VALUE_FULL_INFORMATION *)buffer;
    DWORD size;
    HKEY hkey = key_name ? reg_open_ascii_key( root, key_name ) : root;

    while (!NtEnumerateKey( hkey, 0, KeyNodeInformation, key, sizeof(buffer), &size ))
        reg_delete_tree( hkey, key->Name, key->NameLength );

    if (!subkeys_only)
    {
        while (!NtEnumerateValueKey( hkey, 0, KeyValueFullInformation, value, sizeof(buffer), &size ))
        {
            UNICODE_STRING name = { value->NameLength, value->NameLength, value->Name };
            NtDeleteValueKey( hkey, &name );
        }
    }

    if (hkey != root) NtClose( hkey );
}

static void clear_display_devices(void)
{
    struct source *source;
    struct monitor *monitor;
    struct gpu *gpu;

    if (list_head( &monitors ) == &virtual_monitor.entry)
    {
        list_init( &monitors );
        return;
    }

    while (!list_empty( &monitors ))
    {
        monitor = LIST_ENTRY( list_head( &monitors ), struct monitor, entry );
        list_remove( &monitor->entry );
        monitor_release( monitor );
    }

    while (!list_empty( &sources ))
    {
        source = LIST_ENTRY( list_head( &sources ), struct source, entry );
        list_remove( &source->entry );
        source_release( source );
    }

    while (!list_empty( &gpus ))
    {
        gpu = LIST_ENTRY( list_head( &gpus ), struct gpu, entry );
        list_remove( &gpu->entry );
        gpu_release( gpu );
    }
}

static void prepare_devices(void)
{
    char buffer[4096];
    KEY_NODE_INFORMATION *key = (void *)buffer;
    KEY_VALUE_PARTIAL_INFORMATION *value = (void *)buffer;
    WCHAR *value_str = (WCHAR *)value->Data;
    unsigned i = 0;
    DWORD size;
    HKEY hkey, subkey, device_key, prop_key;

    clear_display_devices();

    if (!enum_key) enum_key = reg_create_ascii_key( NULL, enum_keyA, 0, NULL );
    if (!control_key) control_key = reg_create_ascii_key( NULL, control_keyA, 0, NULL );
    if (!video_key) video_key = reg_create_ascii_key( NULL, devicemap_video_keyA, REG_OPTION_VOLATILE, NULL );

    /* delete monitors */
    reg_empty_key( enum_key, "DISPLAY", FALSE );
    snprintf( buffer, sizeof(buffer), "Class\\%s", guid_devclass_monitorA );
    hkey = reg_create_ascii_key( control_key, buffer, 0, NULL );
    reg_empty_key( hkey, NULL, FALSE );
    set_reg_ascii_value( hkey, "", "Monitors" );
    set_reg_ascii_value( hkey, "Class", "Monitor" );
    NtClose( hkey );

    /* delete sources */
    reg_empty_key( video_key, NULL, FALSE );

    /* clean GPUs */
    snprintf( buffer, sizeof(buffer), "Class\\%s", guid_devclass_displayA );
    hkey = reg_create_ascii_key( control_key, buffer, 0, NULL );
    reg_empty_key( hkey, NULL, FALSE );
    set_reg_ascii_value( hkey, "", "Display adapters" );
    set_reg_ascii_value( hkey, "Class", "Display" );
    NtClose( hkey );
    if ((hkey = reg_create_ascii_key( NULL, directx_keyA, 0, NULL )))
    {
        reg_empty_key( hkey, NULL, TRUE );
        NtClose( hkey );
    }

    hkey = reg_open_ascii_key( enum_key, "PCI" );

    /* To preserve GPU GUIDs, mark them as not present and delete them in cleanup_devices if needed. */
    while (!NtEnumerateKey( hkey, i++, KeyNodeInformation, key, sizeof(buffer), &size ))
    {
        unsigned int j = 0;

        if (!(subkey = reg_open_key( hkey, key->Name, key->NameLength ))) continue;

        while (!NtEnumerateKey( subkey, j++, KeyNodeInformation, key, sizeof(buffer), &size ))
        {
            if (!(device_key = reg_open_key( subkey, key->Name, key->NameLength ))) continue;
            size = query_reg_ascii_value( device_key, "ClassGUID", value, sizeof(buffer) );
            if (size != sizeof(guid_devclass_displayW) || wcscmp( value_str, guid_devclass_displayW ))
            {
                NtClose( device_key );
                continue;
            }

            if ((prop_key = reg_create_ascii_key( device_key, devpropkey_device_ispresentA, 0, NULL )))
            {
                BOOL present = FALSE;
                set_reg_value( prop_key, NULL, 0xffff0000 | DEVPROP_TYPE_BOOLEAN,
                               &present, sizeof(present) );
                NtClose( prop_key );
            }

            NtClose( device_key );
        }

        NtClose( subkey );
    }

    NtClose( hkey );
}

static void cleanup_devices(void)
{
    char buffer[4096];
    KEY_NODE_INFORMATION *key = (void *)buffer;
    KEY_VALUE_PARTIAL_INFORMATION *value = (void *)buffer;
    WCHAR bufferW[512], *value_str = (WCHAR *)value->Data;
    unsigned i = 0;
    DWORD size;
    HKEY hkey, subkey, device_key, prop_key;

    hkey = reg_open_ascii_key( enum_key, "PCI" );

    while (!NtEnumerateKey( hkey, i++, KeyNodeInformation, key, sizeof(buffer), &size ))
    {
        unsigned int j = 0;

        if (!(subkey = reg_open_key( hkey, key->Name, key->NameLength ))) continue;

        while (!NtEnumerateKey( subkey, j++, KeyNodeInformation, key, sizeof(buffer), &size ))
        {
            BOOL present = FALSE;

            if (!(device_key = reg_open_key( subkey, key->Name, key->NameLength ))) continue;
            memcpy( bufferW, key->Name, key->NameLength );
            bufferW[key->NameLength / sizeof(WCHAR)] = 0;

            size = query_reg_ascii_value( device_key, "ClassGUID", value, sizeof(buffer) );
            if (size != sizeof(guid_devclass_displayW) || wcscmp( value_str, guid_devclass_displayW ))
            {
                NtClose( device_key );
                continue;
            }

            if ((prop_key = reg_open_ascii_key( device_key, devpropkey_device_ispresentA )))
            {
                if (query_reg_value( prop_key, NULL, value, sizeof(buffer) ) == sizeof(BOOL))
                    present = *(const BOOL *)value->Data;
                NtClose( prop_key );
            }

            NtClose( device_key );

            if (!present && reg_delete_tree( subkey, bufferW, lstrlenW( bufferW ) * sizeof(WCHAR) ))
                j = 0;
        }

        NtClose( subkey );
    }

    NtClose( hkey );
}

/* see UuidCreate */
static void uuid_create( GUID *uuid )
{
    char buf[4096];
    NtQuerySystemInformation( SystemInterruptInformation, buf, sizeof(buf), NULL );
    memcpy( uuid, buf, sizeof(*uuid) );
    uuid->Data3 &= 0x0fff;
    uuid->Data3 |= (4 << 12);
    uuid->Data4[0] &= 0x3f;
    uuid->Data4[0] |= 0x80;
}

#define TICKSPERSEC  10000000
#define SECSPERDAY   86400
#define DAYSPERQUADRICENTENNIUM  (365 * 400 + 97)
#define DAYSPERNORMALQUADRENNIUM (365 * 4 + 1)

static unsigned int format_date( WCHAR *bufferW, LONGLONG time )
{
    int cleaps, years, yearday, months, days;
    unsigned int day, month, year;
    char buffer[33];

    days = time / TICKSPERSEC / SECSPERDAY;

    /* compute year, month and day of month, see RtlTimeToTimeFields */
    cleaps = (3 * ((4 * days + 1227) / DAYSPERQUADRICENTENNIUM) + 3) / 4;
    days += 28188 + cleaps;
    years = (20 * days - 2442) / (5 * DAYSPERNORMALQUADRENNIUM);
    yearday = days - (years * DAYSPERNORMALQUADRENNIUM) / 4;
    months = (64 * yearday) / 1959;
    if (months < 14)
    {
        month = months - 1;
        year = years + 1524;
    }
    else
    {
        month = months - 13;
        year = years + 1525;
    }
    day = yearday - (1959 * months) / 64 ;

    snprintf( buffer, sizeof(buffer), "%u-%u-%u", month, day, year );
    return asciiz_to_unicode( bufferW, buffer );
}

struct device_manager_ctx
{
    UINT gpu_count;
    UINT source_count;
    UINT monitor_count;
    HANDLE mutex;
    struct list vulkan_gpus;
    struct list opengl_gpus;
    BOOL has_primary;
    /* for
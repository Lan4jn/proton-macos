/*
 * cpu_regprobe.c: Read-only ARM64 Windows PE Probe for CPU Hardware Registry Keys.
 * Strictly uses ntdll Native APIs (NtOpenKey, NtQueryValueKey, NtWriteFile, NtTerminateProcess).
 * Zero registry writes. Zero PE patching.
 */

typedef void *HANDLE;
typedef long NTSTATUS;
typedef unsigned long ULONG;
typedef unsigned short USHORT;
typedef unsigned short WCHAR;
typedef unsigned char UCHAR;

#define STATUS_SUCCESS 0x00000000
#define STATUS_OBJECT_NAME_NOT_FOUND 0xC0000034
#define STATUS_OBJECT_PATH_NOT_FOUND 0xC000003A
#define STATUS_BUFFER_OVERFLOW 0x80000005
#define STATUS_BUFFER_TOO_SMALL 0xC0000023

#define OBJ_CASE_INSENSITIVE 0x00000040L
#define KEY_QUERY_VALUE 0x0001

typedef struct _UNICODE_STRING {
    USHORT Length;
    USHORT MaximumLength;
    WCHAR *Buffer;
} UNICODE_STRING;

typedef struct _OBJECT_ATTRIBUTES {
    ULONG Length;
    HANDLE RootDirectory;
    UNICODE_STRING *ObjectName;
    ULONG Attributes;
    void *SecurityDescriptor;
    void *SecurityQualityOfService;
} OBJECT_ATTRIBUTES;

typedef enum _KEY_VALUE_INFORMATION_CLASS {
    KeyValueBasicInformation,
    KeyValueFullInformation,
    KeyValuePartialInformation,
    KeyValueFullInformationAlign64
} KEY_VALUE_INFORMATION_CLASS;

typedef struct _IO_STATUS_BLOCK {
    union {
        NTSTATUS Status;
        void *Pointer;
    };
    ULONG *Information;
} IO_STATUS_BLOCK;

__declspec(dllimport) NTSTATUS __stdcall NtOpenKey(HANDLE *KeyHandle, ULONG DesiredAccess, OBJECT_ATTRIBUTES *ObjectAttributes);
__declspec(dllimport) NTSTATUS __stdcall NtQueryValueKey(HANDLE KeyHandle, UNICODE_STRING *ValueName, KEY_VALUE_INFORMATION_CLASS KeyValueInformationClass, void *KeyValueInformation, ULONG Length, ULONG *ResultLength);
__declspec(dllimport) NTSTATUS __stdcall NtClose(HANDLE Handle);
__declspec(dllimport) NTSTATUS __stdcall NtWriteFile(HANDLE FileHandle, HANDLE Event, void *ApcRoutine, void *ApcContext, IO_STATUS_BLOCK *IoStatusBlock, void *Buffer, ULONG Length, void *ByteOffset, ULONG *Key);
__declspec(dllimport) void __stdcall NtTerminateProcess(HANDLE ProcessHandle, NTSTATUS ExitStatus);

static HANDLE get_stdout_handle(void) {
    // In Wine console PE, handle 7 is standard output
    return (HANDLE)(void *)(long long)7;
}

static void write_str(const char *s) {
    ULONG len = 0;
    while (s[len]) len++;
    IO_STATUS_BLOCK iosb;
    NtWriteFile(get_stdout_handle(), 0, 0, 0, &iosb, (void *)s, len, 0, 0);
}

static void init_unicode_string(UNICODE_STRING *us, const WCHAR *s) {
    USHORT len = 0;
    while (s[len]) len++;
    us->Length = len * sizeof(WCHAR);
    us->MaximumLength = (len + 1) * sizeof(WCHAR);
    us->Buffer = (WCHAR *)s;
}

static const WCHAR key_path[] = L"\\Registry\\Machine\\Hardware\\Description\\System\\CentralProcessor\\0";

static const WCHAR *val_names[] = {
    L"~MHz",
    L"FeatureSet",
    L"Component Information",
    L"Configuration Data",
    L"Identifier",
    L"ProcessorNameString",
    L"VendorIdentifier",
    L"CP 00000001",
    L"CP 00000002",
    L"CP 00000003",
    L"CP 00000004"
};

void mainCRTStartup(void) {
    HANDLE hkey = 0;
    OBJECT_ATTRIBUTES attr;
    UNICODE_STRING us_key;
    NTSTATUS status;
    int missing_values = 0;

    write_str("CPU_REGPROBE_START\n");

    init_unicode_string(&us_key, key_path);
    attr.Length = sizeof(OBJECT_ATTRIBUTES);
    attr.RootDirectory = 0;
    attr.ObjectName = &us_key;
    attr.Attributes = OBJ_CASE_INSENSITIVE;
    attr.SecurityDescriptor = 0;
    attr.SecurityQualityOfService = 0;

    status = NtOpenKey(&hkey, KEY_QUERY_VALUE, &attr);
    if (status != STATUS_SUCCESS) {
        write_str("KEY: \\Registry\\Machine\\Hardware\\Description\\System\\CentralProcessor\\0 MISSING\n");
        write_str("CPU_REGPROBE_END status=2\n");
        NtTerminateProcess((HANDLE)-1, 2);
    }

    write_str("KEY: \\Registry\\Machine\\Hardware\\Description\\System\\CentralProcessor\\0 FOUND\n");

    UCHAR buf[512];
    ULONG result_len = 0;

    for (int i = 0; i < 11; i++) {
        UNICODE_STRING us_val;
        init_unicode_string(&us_val, val_names[i]);
        status = NtQueryValueKey(hkey, &us_val, KeyValuePartialInformation, buf, sizeof(buf), &result_len);
        if (status == STATUS_SUCCESS) {
            write_str("VAL: FOUND\n");
        } else {
            write_str("VAL: MISSING\n");
            missing_values++;
        }
    }

    NtClose(hkey);

    if (missing_values > 0) {
        write_str("CPU_REGPROBE_END status=3\n");
        NtTerminateProcess((HANDLE)-1, 3);
    }

    write_str("CPU_REGPROBE_END status=0\n");
    NtTerminateProcess((HANDLE)-1, 0);
}

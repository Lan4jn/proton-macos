__declspec(dllimport) long __stdcall NtTerminateProcess(void *handle, long status);

void mainCRTStartup(void) {
#ifdef __aarch64__
    NtTerminateProcess((void *)-1, 37);
#else
    NtTerminateProcess((void *)-1, 43);
#endif
}

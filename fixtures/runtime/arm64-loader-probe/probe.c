typedef unsigned long DWORD;
typedef void *HANDLE;
__declspec(dllimport) HANDLE GetStdHandle(DWORD);
__declspec(dllimport) int WriteFile(HANDLE,const void*,DWORD,DWORD*,void*);
__declspec(dllimport) void *LoadLibraryA(const char*);
__declspec(dllimport) void *GetProcAddress(void*,const char*);
__declspec(dllimport) DWORD GetLastError(void);
__declspec(dllimport) void ExitProcess(DWORD);
static void out(const char *s) {
    DWORD len=0,done=0; while(s[len])++len;
    WriteFile(GetStdHandle((DWORD)-11),s,len,&done,0);
}
static void number(DWORD n) {
    char b[16]; unsigned i=0; do { b[i++]=(char)('0'+n%10); n/=10; } while(n);
    for(unsigned j=0;j<i/2;++j){char c=b[j];b[j]=b[i-j-1];b[i-j-1]=c;} b[i]=0; out(b); out("\n");
}
void mainCRTStartup(void) {
#if MODE == 0
    out("ARM64_KERNEL32_OK\n"); ExitProcess(37);
#elif MODE == 1
    out("ARM64_USER32_LOAD_ENTER\n");
    void *m=LoadLibraryA("user32.dll");
    if(!m){out("ARM64_USER32_LOAD_ERROR=");number(GetLastError());ExitProcess(10);}
    out("ARM64_USER32_LOAD_RETURNED\n");
    DWORD (*f)(void)=(DWORD(*)(void))GetProcAddress(m,"GetDpiForSystem");
    if(!f){out("ARM64_DPI_RESOLVE_ERROR\n");ExitProcess(11);}
    out("ARM64_DPI_ENTER\n"); DWORD dpi=f();
    out("ARM64_DPI_RETURNED=");number(dpi);ExitProcess(38);
#else
    out("ARM64_VULKAN_LOAD_ENTER\n");
    void *m=LoadLibraryA("vulkan-1.dll");
    if(!m){out("ARM64_VULKAN_LOAD_ERROR=");number(GetLastError());ExitProcess(10);}
    out("ARM64_VULKAN_LOAD_RETURNED\n");ExitProcess(39);
#endif
}

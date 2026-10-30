typedef unsigned long DWORD;
__declspec(dllimport) void* __stdcall GetStdHandle(DWORD);
__declspec(dllimport) int __stdcall WriteFile(void*,const void*,DWORD,DWORD*,void*);
__declspec(dllimport) void __stdcall ExitProcess(DWORD);
void mainCRTStartup(void){const char text[]="X64_FEX_OK\r\n";DWORD wrote=0;int ok=WriteFile(GetStdHandle((DWORD)-11),text,sizeof(text)-1,&wrote,0);ExitProcess(ok&&wrote==sizeof(text)-1?0:7);}

/* Freestanding Windows x64 PE. No native Cocoa/Linux substitute. */
typedef unsigned long DWORD;
typedef unsigned int UINT;
typedef unsigned short WORD;
typedef unsigned long long U64;
typedef long long I64;
typedef void *HANDLE;
typedef I64 (*WNDPROC)(HANDLE,UINT,U64,I64);
__declspec(dllimport) HANDLE GetStdHandle(DWORD);
__declspec(dllimport) int WriteFile(HANDLE,const void*,DWORD,DWORD*,void*);
__declspec(dllimport) void ExitProcess(UINT);
__declspec(dllimport) U64 GetTickCount64(void);
__declspec(dllimport) DWORD GetLastError(void);
__declspec(dllimport) HANDLE LoadLibraryA(const char*);
__declspec(dllimport) void* GetProcAddress(HANDLE,const char*);
__declspec(dllimport) HANDLE GetModuleHandleA(const char*);
struct RECT {long left,top,right,bottom;};
struct POINT {long x,y;};
struct MSG {HANDLE hwnd;UINT message;U64 wParam;I64 lParam;DWORD time;struct POINT pt;DWORD lPrivate;};
struct PAINTSTRUCT {HANDLE hdc;int erase;struct RECT paint;int restore,inc;unsigned char reserved[32];};
struct WNDCLASSEX {UINT size,style;WNDPROC proc;int cls_extra,wnd_extra;HANDLE instance,icon,cursor,background;const char *menu,*name;HANDLE icon_small;};
static WORD (*RegisterClassExA)(const struct WNDCLASSEX*);
static HANDLE (*CreateWindowExA)(DWORD,const char*,const char*,DWORD,int,int,int,int,HANDLE,HANDLE,HANDLE,void*);
static int (*ShowWindow)(HANDLE,int);
static int (*GetMessageA)(struct MSG*,HANDLE,UINT,UINT);
static int (*TranslateMessage)(const struct MSG*);
static I64 (*DispatchMessageA)(const struct MSG*);
static I64 (*DefWindowProcA)(HANDLE,UINT,U64,I64);
static HANDLE (*BeginPaint)(HANDLE,struct PAINTSTRUCT*);
static int (*EndPaint)(HANDLE,const struct PAINTSTRUCT*);
static void (*PostQuitMessage)(int);
static int (*InvalidateRect)(HANDLE,const struct RECT*,int);
static int (*DestroyWindow)(HANDLE);
static HANDLE (*CreateSolidBrush)(DWORD);
static int (*DeleteObject)(HANDLE);
static int (*FillRect)(HANDLE,const struct RECT*,HANDLE);
static int (*TextOutA)(HANDLE,int,int,const char*,int);
static U64 start;
static int painted;
static HANDLE brush;
static void out(const char *s){DWORD n=0,w=0;while(s[n])n++;if(!WriteFile(GetStdHandle((DWORD)-11),s,n,&w,0)||w!=n)ExitProcess(91);}
static void number(U64 n){char buf[24];int i=0;do{buf[i++]=(char)('0'+n%10);n/=10;}while(n);while(i){char x[2]={buf[--i],0};out(x);}}
static void stage(const char *s,U64 v){out("WINDOW_STAGE t_ms=");number(GetTickCount64()-start);out(" stage=");out(s);out(" value=");number(v);out("\r\n");}
static void fail(const char *s,UINT code){stage(s,GetLastError());ExitProcess(code);}
static void *symbol(HANDLE mod,const char *name){void *p=GetProcAddress(mod,name);if(!p){out("MISSING_API ");out(name);out("\r\n");fail("RESOLVE_FAIL",11);}return p;}
static I64 window_proc(HANDLE hwnd,UINT msg,U64 wp,I64 lp){
 if(msg==0x000f){
  struct PAINTSTRUCT ps;stage("PAINT_BEGIN",0);HANDLE dc=BeginPaint(hwnd,&ps);
  if(!dc)fail("BEGINPAINT_FAIL",21);
  struct RECT area={0,0,320,200};
  if(!FillRect(dc,&area,brush))fail("FILL_FAIL",22);
  if(!TextOutA(dc,24,36,"Windows x64 PE paint OK",23))fail("TEXT_FAIL",23);
  if(!EndPaint(hwnd,&ps))fail("ENDPAINT_FAIL",24);
  painted=1;stage("PAINT_OK",1);PostQuitMessage(0);return 0;
 }
 return DefWindowProcA(hwnd,msg,wp,lp);
}
void mainCRTStartup(void){
 start=GetTickCount64();stage("PROCESS_START",1);
 stage("USER32_BEGIN",0);HANDLE user=LoadLibraryA("user32.dll");if(!user)fail("USER32_FAIL",10);stage("USER32_OK",1);
#define RESOLVE(M,N) N=(void*)symbol(M,#N)
 RESOLVE(user,RegisterClassExA);RESOLVE(user,CreateWindowExA);RESOLVE(user,ShowWindow);RESOLVE(user,GetMessageA);
 RESOLVE(user,TranslateMessage);RESOLVE(user,DispatchMessageA);RESOLVE(user,DefWindowProcA);RESOLVE(user,BeginPaint);
 RESOLVE(user,EndPaint);RESOLVE(user,PostQuitMessage);RESOLVE(user,InvalidateRect);RESOLVE(user,DestroyWindow);RESOLVE(user,FillRect);
 stage("GDI32_BEGIN",0);HANDLE gdi=LoadLibraryA("gdi32.dll");if(!gdi)fail("GDI32_FAIL",12);RESOLVE(gdi,CreateSolidBrush);RESOLVE(gdi,DeleteObject);RESOLVE(gdi,TextOutA);stage("GDI32_OK",1);
 brush=CreateSolidBrush(0x803010);if(!brush)fail("BRUSH_FAIL",13);
 struct WNDCLASSEX wc={sizeof(wc),0,window_proc,0,0,GetModuleHandleA(0),0,0,0,0,"ProtonLabX64Window",0};
 stage("REGISTER_BEGIN",0);WORD atom=RegisterClassExA(&wc);if(!atom)fail("REGISTER_FAIL",14);stage("REGISTER_OK",atom);
 stage("CREATE_BEGIN",0);HANDLE hwnd=CreateWindowExA(0,wc.name,"Proton Lab x64 GDI",0x00cf0000,80,80,360,240,0,0,wc.instance,0);
 if(!hwnd)fail("CREATE_FAIL",15);stage("CREATE_OK",1);
 stage("SHOW_BEGIN",0);int previous=ShowWindow(hwnd,5);stage("SHOW_OK",(UINT)previous);
 if(!InvalidateRect(hwnd,0,1))fail("INVALIDATE_FAIL",16);
 stage("LOOP_ENTER",0);struct MSG msg;int ret;
 while((ret=GetMessageA(&msg,0,0,0))>0){stage("MESSAGE",msg.message);TranslateMessage(&msg);DispatchMessageA(&msg);}
 if(ret<0)fail("GETMESSAGE_FAIL",17);stage("LOOP_QUIT",msg.wParam);
 if(!painted||msg.wParam)fail("PAINT_MISSING",18);
 stage("DESTROY_BEGIN",0);if(!DestroyWindow(hwnd))fail("DESTROY_FAIL",19);stage("DESTROY_OK",1);
 if(!DeleteObject(brush))fail("DELETEBRUSH_FAIL",20);
 stage("EXIT_OK",0);ExitProcess(0);
}

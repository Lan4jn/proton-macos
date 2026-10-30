static inline long sc(long n,long a,long b,long c,long d,long e,long f) {
 register long x8 __asm__("x8")=n,x0 __asm__("x0")=a,x1 __asm__("x1")=b,x2 __asm__("x2")=c,x3 __asm__("x3")=d,x4 __asm__("x4")=e,x5 __asm__("x5")=f;
 __asm__ volatile("svc #0":"+r"(x0):"r"(x8),"r"(x1),"r"(x2),"r"(x3),"r"(x4),"r"(x5):"memory");return x0;
}
static void done(int code,const char*s,unsigned long len){sc(64,code?2:1,(long)s,len,0,0,0);sc(94,code,0,0,0,0,0);__builtin_unreachable();}
#define END(code,s) done(code,s,sizeof(s)-1)

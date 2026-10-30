typedef unsigned long U;
#include "frame.h"
struct Packet {U ready,seq,phase;unsigned char pixels[16384];};
volatile struct Packet packet;
static long sc(long n,long a,long b,long c){register long x8 __asm__("x8")=n;register long x0 __asm__("x0")=a;register long x1 __asm__("x1")=b;register long x2 __asm__("x2")=c;__asm__ volatile("svc #0":"+r"(x0):"r"(x8),"r"(x1),"r"(x2):"memory");return x0;}
static U clocktick(void){U v;__asm__ volatile("mrs %0,cntvct_el0":"=r"(v));return v;}
static U frequency(void){U v;__asm__ volatile("mrs %0,cntfrq_el0":"=r"(v));return v;}
static void text(const char *s){long n=0;while(s[n])n++;sc(64,1,(long)s,n);}
static void number(U n){char a[24];long i=0;do{a[i++]=(char)('0'+n%10);n/=10;}while(n);while(i)sc(64,1,(long)&a[--i],1);}
void _start(void){
 for(U i=0;i<16384;i++)packet.pixels[i]=frame[i];
 packet.phase=1;packet.seq=1;__asm__ volatile("dmb ish":::"memory");packet.ready=0x504958454c;
 U freq=frequency(),max_gap=0,last=clocktick();struct {long sec,nsec;} sleep={0,1000000};
 text("GUEST_READY frequency=");number(freq);text("\n");
 for(U i=0;i<200;i++){packet.seq++;sc(172,0,0,0);sc(101,(long)&sleep,0,0);U now=clocktick();if(now-last>max_gap)max_gap=now-last;last=now;}
 text("HEARTBEAT1 max_gap_ticks=");number(max_gap);text("\n");
 packet.phase=2;text("COMPUTE_BEGIN_NO_SYSCALL\n");U begin=clocktick();
 while(clocktick()-begin<freq*3){packet.seq++;__asm__ volatile("":::"memory");}
 packet.phase=3;sc(172,0,0,0);text("COMPUTE_NO_SYSCALL ticks=");number(clocktick()-begin);text("\n");
 max_gap=0;last=clocktick();
 for(U i=0;i<200;i++){packet.seq++;sc(172,0,0,0);sc(101,(long)&sleep,0,0);U now=clocktick();if(now-last>max_gap)max_gap=now-last;last=now;}
 text("HEARTBEAT3 max_gap_ticks=");number(max_gap);text("\n");
 packet.phase=4;sc(172,0,0,0);text("GUEST_DONE\n");sc(93,0,0,0);for(;;){}
}

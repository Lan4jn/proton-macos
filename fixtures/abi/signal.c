#include "syscalls.h"
static volatile int seen;
static void handler(int signum){seen=signum;}
__attribute__((naked)) static void restore(void){__asm__("mov x8,#139\nsvc #0");}
struct act{void(*handler)(int);unsigned long flags;void(*restorer)(void);unsigned long mask;};
void _start(void){
 struct act a={handler,0x04000000,restore,0};
 if(sc(134,10,(long)&a,0,8,0,0)!=0)END(2,"SIGACTION_FAIL\n");
 long pid=sc(172,0,0,0,0,0,0);if(sc(129,pid,10,0,0,0,0)!=0)END(3,"KILL_FAIL\n");
 if(seen!=10)END(4,"SIGNAL_NOT_DELIVERED\n");END(0,"SIGNAL_OK\n");
}

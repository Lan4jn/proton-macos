#include "syscalls.h"
struct ts{long sec,nsec;};
void _start(void){
 volatile int*p=(void*)sc(222,0,16384,3,0x21,-1,0);
 if((unsigned long)p>=(unsigned long)-4095)END(2,"MMAP_FAIL\n");
 *p=0;long child=sc(220,17,0,0,0,0,0);
 if(child<0)END(3,"CLONE_FAIL\n");
 if(!child){struct ts delay={0,50000000};sc(101,(long)&delay,0,0,0,0,0);*p=1;__asm__ volatile("dmb ish":::"memory");long wake=sc(98,(long)p,1,1,0,0,0);if(wake<0)END(4,"WAKE_FAIL\n");sc(94,0,0,0,0,0,0);}
 struct ts limit={1,0};long wait=sc(98,(long)p,0,0,(long)&limit,0,0);int status=-1;sc(260,child,(long)&status,0,0,0,0);
 if(wait==-110)END(5,"FUTEX_TIMEOUT_DESPITE_SHARED_WRITE\n");
 if((wait!=0&&wait!=-11)||*p!=1||status!=0)END(5,"FUTEX_WAIT_FAIL\n");
 END(0,"FUTEX_OK\n");
}

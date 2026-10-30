#include "syscalls.h"
void _start(void){
 volatile int*p=(void*)sc(222,0,16384,3,0x21,-1,0);
 if((unsigned long)p>=(unsigned long)-4095)END(2,"MMAP_FAIL\n");
 *p=1;long child=sc(220,17,0,0,0,0,0);
 if(child<0)END(3,"CLONE_FAIL\n");
 if(!child){*p=123;sc(94,0,0,0,0,0,0);}
 int status=-1;long waited=sc(260,child,(long)&status,0,0,0,0);
 if(waited!=child||status!=0||*p!=123)END(4,"SHARED_NOT_VISIBLE\n");
 END(0,"SHARED_OK\n");
}

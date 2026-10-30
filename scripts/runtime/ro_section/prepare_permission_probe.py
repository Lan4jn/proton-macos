#!/usr/bin/env python3
"""Extract actual Wine helper and get_unix_prot into an isolated semantic regression.
This is not an end-to-end NtProtectVirtualMemory test or a session-section trace.
"""
from pathlib import Path
import hashlib,json
LAB=Path(__file__).resolve().parents[3]
SRC=LAB/'sources/wine-pin-adea/pristine/wine-adea6cbac9d00bb22910145354d00c463fcf3afc/dlls/ntdll/unix/virtual.c'
OUT=LAB/'sources/wine-ro-section-adapt'
src=SRC.read_text()
def function(name):
    start=src.index(name)
    start=src.rfind('\n',0,start)+1
    brace=src.index('{',start); level=1; end=brace+1
    while level:
        level+=(src[end]=='{')-(src[end]=='}'); end+=1
    return src[start:end]
helper=function('static NTSTATUS map_file_into_view(')
convert=function('static int get_unix_prot(')
old='''#ifdef __linux__
        flags |= MAP_PRIVATE;
#else
        flags |= MAP_SHARED;
        prot &= ~PROT_WRITE;
#endif'''
assert helper.count(old)==1
adapted=helper.replace(old,'''        flags |= MAP_SHARED;
        prot &= ~PROT_WRITE;''')
# Same Linux branch selected on both native host and guest for baseline comparison.
helper=helper.replace('#ifdef __linux__','#if 1')
preamble=r'''
#define _GNU_SOURCE
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <errno.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <signal.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/wait.h>
typedef unsigned char BYTE;
typedef unsigned long NTSTATUS;
typedef int BOOL;
#define VPROT_READ 0x01
#define VPROT_WRITE 0x02
#define VPROT_EXEC 0x04
#define VPROT_WRITECOPY 0x08
#define VPROT_GUARD 0x10
#define VPROT_COMMITTED 0x20
#define VPROT_WRITEWATCH 0x40
#define STATUS_SUCCESS 0
#define STATUS_NOT_SUPPORTED 1
#define STATUS_ACCESS_DENIED 2
#define STATUS_NO_MEMORY 3
#define STATUS_INVALID_PARAMETER 4
#define ERR(...) fprintf(stderr,__VA_ARGS__)
#define ROUND_SIZE(a,b,m) (((uintptr_t)(a)+(b)+(m))&~(uintptr_t)(m))
#define ROUND_ADDR(a,m) ((void*)((uintptr_t)(a)&~(uintptr_t)(m)))
static size_t page_mask,host_page_mask;
struct file_view {void *base; size_t size;};
static int failures;
#define REQUIRE(x) do {if(!(x)){fprintf(stderr,"setup failure line=%d errno=%d\n",__LINE__,errno);exit(90);}}while(0)
static int fixture(size_t n){char name[]="section-XXXXXX";int fd=mkstemp(name);REQUIRE(fd>=0);REQUIRE(unlink(name)==0);REQUIRE(ftruncate(fd,n)==0);unsigned char b=0x31;REQUIRE(pwrite(fd,&b,1,0)==1);return fd;}
static struct file_view reserve(size_t n){struct file_view v={mmap(NULL,n,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0),n};REQUIRE(v.base!=MAP_FAILED);return v;}
static unsigned char disk(int fd){unsigned char b=0;REQUIRE(pread(fd,&b,1,0)==1);return b;}
static void result(const char *name,int ok){printf("%s=%s\n",name,ok?"PASS":"FAIL");if(!ok)failures++;}
'''
tests=r'''
int main(void){
 setvbuf(stdout,NULL,_IONBF,0);
 size_t p=sysconf(_SC_PAGESIZE);page_mask=host_page_mask=p-1;
 printf("MODE=%s PAGE_SIZE=%zu\n",MODE,p);
 int fd=fixture(p*2);
 struct file_view wc=reserve(p);
 REQUIRE(map_file_into_view(&wc,fd,0,p,0,VPROT_COMMITTED|VPROT_READ|VPROT_WRITECOPY,0)==0);
 ((volatile unsigned char*)wc.base)[0]=0x55;
 result("INITIAL_WRITECOPY_ISOLATION",disk(fd)==0x31);
 munmap(wc.base,p);
 struct file_view rw=reserve(p);
 REQUIRE(map_file_into_view(&rw,fd,0,p,0,VPROT_COMMITTED|VPROT_READ|VPROT_WRITE,0)==0);
 ((volatile unsigned char*)rw.base)[0]=0x44;
 result("READWRITE_SHARED_VISIBLE",disk(fd)==0x44);
 unsigned char initial=0x31;REQUIRE(pwrite(fd,&initial,1,0)==1);
 struct file_view ro=reserve(p);
 REQUIRE(map_file_into_view(&ro,fd,0,p,0,VPROT_COMMITTED|VPROT_READ,0)==0);
 REQUIRE(mprotect(ro.base,p,get_unix_prot(VPROT_COMMITTED|VPROT_READ))==0);
 result("READONLY_READ",((volatile unsigned char*)ro.base)[0]==0x31);
 pid_t child=fork();REQUIRE(child>=0);
 if(!child){((volatile unsigned char*)ro.base)[0]=0x66;_exit(0);}
 int status; REQUIRE(waitpid(child,&status,0)==child);
 result("READONLY_WRITE_FAULT",WIFSIGNALED(status)&&(WTERMSIG(status)==SIGSEGV||WTERMSIG(status)==SIGBUS));
 unsigned char update=0x42;REQUIRE(pwrite(fd,&update,1,0)==1);
 result("READONLY_LIVE_UPDATE",((volatile unsigned char*)ro.base)[0]==0x42);
 // Force original helper's EINVAL mmap fallback with unaligned file offset.
 struct file_view fallback=reserve(p);
 REQUIRE(map_file_into_view(&fallback,fd,0,p,1,VPROT_COMMITTED|VPROT_READ,0)==0);
 REQUIRE(mprotect(fallback.base,p,get_unix_prot(VPROT_COMMITTED|VPROT_READ))==0);
 result("FALLBACK_PREAD_READ",((volatile unsigned char*)fallback.base)[0]==0);
 REQUIRE(mprotect(fallback.base,p,get_unix_prot(VPROT_COMMITTED|VPROT_READ|VPROT_WRITECOPY))==0);
 ((volatile unsigned char*)fallback.base)[0]=0x67;
 unsigned char offset_one=0xff;REQUIRE(pread(fd,&offset_one,1,1)==1);
 result("FALLBACK_PRIVATE_UPGRADE_ISOLATED",offset_one==0);
 munmap(fallback.base,p);
 // NtProtect -> set_protection -> set_vprot -> mprotect_range uses this exact
 // get_unix_prot for PAGE_WRITECOPY. This tests that Unix boundary, not PE NtProtect.
 int prot=get_unix_prot(VPROT_COMMITTED|VPROT_READ|VPROT_WRITECOPY);
 REQUIRE(mprotect(ro.base,p,prot)==0);
 ((volatile unsigned char*)ro.base)[0]=0x7a;
 unsigned char file_byte=disk(fd),sibling=((volatile unsigned char*)rw.base)[0];
 printf("UPGRADE_OBSERVED private=0x7a backing=0x%02x sibling=0x%02x expected_backing=0x42\n",file_byte,sibling);
 int leak=file_byte!=0x42||sibling!=0x42;
 result("READONLY_TO_WRITECOPY_NO_LEAK",!leak);
 munmap(ro.base,p);munmap(rw.base,p);close(fd);
 if(leak){puts("STOP_PRIVATE_WRITE_LEAK: no deployment or second patch");return 42;}
 return failures?1:0;
}
'''
for label,body in [('baseline',helper),('approved_candidate',adapted)]:
    # Observations apply solely to these test fixtures; never imply real session attribution.
    marker='''        struct stat observed;
        if (!fstat(fd, &observed)) fprintf(stderr,
            "RO_HELPER_OBSERVE size=%zu offset=%lld unlinked=%d prot=%x vprot=%x caller=%p fixture=permission_probe\\n",
            size,(long long)offset,observed.st_nlink==0,prot,vprot,__builtin_return_address(0));
'''
    body=body.replace('    map_size = ROUND_SIZE(',marker+'    map_size = ROUND_SIZE(',1)
    text=preamble+'\n#define MODE "'+label+'"\n'+convert+'\n'+body+'\n'+tests
    (OUT/(label+'.c')).write_text(text)
(LAB/'logs/ro-section/extraction.json').write_text(json.dumps({'source':str(SRC),'source_sha256':hashlib.sha256(src.encode()).hexdigest(),'functions':['map_file_into_view','get_unix_prot'],'scope':'isolated Unix-boundary regression; no production Wine patch and no PE NtProtect execution','candidate_change':'only RO else mapping policy, plus fixture-only observation'},indent=2)+'\n')
print('Generated baseline and approved-candidate isolated Unix permission regressions')

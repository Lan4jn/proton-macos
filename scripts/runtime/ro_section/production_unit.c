/* Stage A: include complete production TU, not copied helper bodies. */
#include "../../../sources/wine-ro-section-adapt/wine/dlls/ntdll/unix/virtual.c"
#include <sys/wait.h>
#include <sys/resource.h>
static int failures;
#define REQUIRE(x) do { if (!(x)) { fprintf(stderr,"SETUP line=%d errno=%d\n",__LINE__,errno); exit(90); } } while (0)
static void check(const char *name,int ok) { printf("%s=%s\n",name,ok?"PASS":"FAIL"); failures+=!ok; }
static void init_protection(struct file_view *view)
{
    size_t i,first=(size_t)view->base>>page_shift,last=((size_t)view->base+view->size-1)>>page_shift;
    if(!pages_vprot){pages_vprot_size=65536;pages_vprot=calloc(pages_vprot_size,sizeof(*pages_vprot));REQUIRE(pages_vprot);}
    for(i=first>>pages_vprot_shift;i<=(last>>pages_vprot_shift);i++)
        if(!pages_vprot[i]) {pages_vprot[i]=calloc(pages_vprot_mask+1,1);REQUIRE(pages_vprot[i]);}
    set_page_vprot(view->base,view->size,VPROT_READ|VPROT_COMMITTED);
}
static void write_fault(struct file_view *v,int fd,size_t pos,unsigned char expected)
{
    pid_t child=fork();REQUIRE(child>=0);
    if(!child){((volatile unsigned char*)v->base)[pos]=0xee;_exit(0);}
    int status;REQUIRE(waitpid(child,&status,0)==child);
    unsigned char b;REQUIRE(pread(fd,&b,1,pos)==1);
    check("DOWNGRADE_WRITE_FAULT",WIFSIGNALED(status)&&(WTERMSIG(status)==SIGSEGV||WTERMSIG(status)==SIGBUS));
    check("FAULT_PRESERVES_FILE",b==expected);
}
int main(void)
{
    setvbuf(stdout,NULL,_IONBF,0); struct rlimit limit={0,0};setrlimit(RLIMIT_CORE,&limit);
    char name[]="production-section-XXXXXX";int fd=mkstemp(name);REQUIRE(fd>=0);unlink(name);
    size_t p=4096,n=p*3;host_page_size=p;host_page_mask=p-1;
    REQUIRE(ftruncate(fd,n)==0);
    unsigned char bytes[3]={0x31,0x41,0x51};for(int i=0;i<3;i++)REQUIRE(pwrite(fd,bytes+i,1,i*p)==1);
    struct file_view v={0};v.base=mmap(NULL,n,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);v.size=n;v.protect=SEC_FILE|VPROT_READ|VPROT_WRITE;
    REQUIRE(v.base!=MAP_FAILED);init_protection(&v);
    REQUIRE(map_file_into_view(&v,fd,0,n,0,VPROT_READ|VPROT_COMMITTED,FALSE)==STATUS_SUCCESS);
    REQUIRE(set_protection(&v,v.base,n,PAGE_READONLY)==STATUS_SUCCESS);
    unsigned char *sibling=mmap(NULL,n,PROT_READ,MAP_SHARED,fd,0);REQUIRE(sibling!=MAP_FAILED);
    unsigned char update=0x42;REQUIRE(pwrite(fd,&update,1,p)==1);
    check("PRODUCTION_RO_LIVE_UPDATE",((volatile unsigned char*)v.base)[p]==0x42);
    REQUIRE(set_protection(&v,(char*)v.base+p,p,PAGE_WRITECOPY)==STATUS_SUCCESS);
    ((volatile unsigned char*)v.base)[p]=0x7a;
    unsigned char b;REQUIRE(pread(fd,&b,1,p)==1);
    check("PRODUCTION_WRITECOPY_NO_BACKING_LEAK",b==0x42);
    check("PRODUCTION_WRITECOPY_NO_SIBLING_LEAK",sibling[p]==0x42);
    REQUIRE(set_protection(&v,(char*)v.base+p,p,PAGE_WRITECOPY)==STATUS_SUCCESS);
    check("REPEAT_UPGRADE_PRESERVES_PRIVATE",((volatile unsigned char*)v.base)[p]==0x7a);
    REQUIRE(set_protection(&v,(char*)v.base+p,p,PAGE_READONLY)==STATUS_SUCCESS);
    check("DOWNGRADE_PRESERVES_PRIVATE",((volatile unsigned char*)v.base)[p]==0x7a);
    write_fault(&v,fd,p,0x42);
    update=0x61;REQUIRE(pwrite(fd,&update,1,0)==1);
    printf("NEIGHBOR observed=0x%02x expected=0x61 addr=%p\n",((volatile unsigned char*)v.base)[0],v.base);
    check("UNTOUCHED_NEIGHBOR_LIVE",((volatile unsigned char*)v.base)[0]==0x61);
    REQUIRE(set_protection(&v,v.base,p,PAGE_READWRITE)==STATUS_SUCCESS);
    ((volatile unsigned char*)v.base)[0]=0x62;
    REQUIRE(pread(fd,&b,1,0)==1);printf("WRITE_SHARED backing=0x%02x sibling=0x%02x expected=0x62\n",b,sibling[0]);check("PRODUCTION_WRITE_SHARED",b==0x62&&sibling[0]==0x62);
    munmap(v.base,n);munmap(sibling,n);close(fd);
    printf("PRODUCTION_SOURCE_UNIT failures=%d\n",failures);return failures?42:0;
}

/* Unit-only debug bridge stubs: no mapping/protection functions are stubbed. */
int __wine_dbg_header(enum __wine_debug_class cls,struct __wine_debug_channel *channel,const char *function) { return 0; }
int __wine_dbg_output(const char *text) { return fputs(text,stderr); }

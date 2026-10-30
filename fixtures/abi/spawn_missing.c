extern int posix_spawn(int*,const char*,const void*,const void*,char*const[],char*const[]);
extern int puts(const char*);
extern int printf(const char*,...);
extern int waitpid(int,int*,int);
extern char **environ;
int main(void){int pid=-1;char*av[]={"/definitely_missing_proton_lab",0};int err=posix_spawn(&pid,av[0],0,0,av,environ);if(err==2){puts("SPAWN_ENOENT_OK");return 0;}if(err==0){int s;waitpid(pid,&s,0);printf("SPAWN_RETURN=%d CHILD_EXIT=%d\n",err,(s>>8)&255);}puts("SPAWN_DID_NOT_RETURN_ENOENT");return 9;}

// SPDX-License-Identifier: GPL-2.0-only
/* Diagnostic PID 1. Load the same external modules in child processes and
 * retain each real errno/oops in printk. Never mount installed Android/data. */
typedef unsigned long size_t;
static long call(long nr,long a,long b,long c,long d,long e,long f) {
    register long x8 __asm__("x8")=nr;
    register long x0 __asm__("x0")=a, x1 __asm__("x1")=b;
    register long x2 __asm__("x2")=c, x3 __asm__("x3")=d;
    register long x4 __asm__("x4")=e, x5 __asm__("x5")=f;
    __asm__ volatile("svc #0":"+r"(x0):"r"(x8),"r"(x1),"r"(x2),"r"(x3),"r"(x4),"r"(x5):"memory");
    return x0;
}
static size_t length(const char *s) {size_t n=0;while(s[n])n++;return n;}
static int same(const char *a,const char *b,size_t n) {while(n--)if(*a++!=*b++)return 0;return 1;}
static long logfd;
static void append(char **p,const char *s) {while(*s)*(*p)++=*s++;}
static void record(const char *name,const char *kind,long value) {
    char line[512],digits[32],*p=line,*q=digits+sizeof(digits);
    unsigned long v;
    append(&p,"<5>k618_load: external diagnostic ");append(&p,name);
    append(&p," ");append(&p,kind);append(&p,"=");
    *--q=0;
    if(value<0){*p++='-';v=(unsigned long)(-(value+1))+1;}else v=value;
    do{*--q='0'+v%10;v/=10;}while(v);
    append(&p,q);*p++='\n';
    call(64,logfd,(long)line,p-line,0,0,0);
}
static char cmdline[8192], params[4096];
static void arguments(const char *path) {
    char name[128];size_t n=0,start=0,total=0;
    for(size_t i=0;path[i];i++)if(path[i]=='/')start=i+1;
    while(path[start] && path[start]!='.' && n+2<sizeof(name)) {
        char c=path[start++];name[n++]=c=='-'?'_':c;
    }
    name[n++]='.';name[n]=0;params[0]=0;
    for(size_t i=0;cmdline[i];) {
        while(cmdline[i]==' ' || cmdline[i]=='\n')i++;
        size_t end=i;while(cmdline[end] && cmdline[end]!=' ' && cmdline[end]!='\n')end++;
        if(end-i>n && same(cmdline+i,name,n)) {
            size_t count=end-i-n;
            if(total+count+2>=sizeof(params)) {record(path,"parameter-buffer-overflow",-1);break;}
            if(total)params[total++]=' ';
            for(size_t j=0;j<count;j++)params[total++]=cmdline[i+n+j];
            params[total]=0;
        }
        i=end;
    }
}
#include "module-order.h"
__attribute__((noreturn)) void diag_main(void) {
    call(34,-100,(long)"/dev",0755,0,0,0);
    call(40,(long)"devtmpfs",(long)"/dev",(long)"devtmpfs",0,0,0);
    call(33,-100,(long)"/dev/kmsg",0020600,((1<<8)|11),0,0);
    logfd=call(56,-100,(long)"/dev/kmsg",1,0,0,0);
    record("startup","pid",call(172,0,0,0,0,0,0));
    call(34,-100,(long)"/proc",0755,0,0,0);
    call(40,(long)"proc",(long)"/proc",(long)"proc",0,0,0);
    call(34,-100,(long)"/sys",0755,0,0,0);
    call(40,(long)"sysfs",(long)"/sys",(long)"sysfs",0,0,0);
    long fd=call(56,-100,(long)"/proc/cmdline",0,0,0,0);
    long count=call(63,fd,(long)cmdline,sizeof(cmdline)-1,0,0,0);
    if(count>0)cmdline[count]=0;call(57,fd,0,0,0,0,0);
    for(size_t i=0;i<sizeof(module_order)/sizeof(module_order[0]);i++) {
        const char *path=module_order[i];arguments(path);
        record(path,"begin",(long)i);
        long child=call(220,17,0,0,0,0,0);
        if(child==0) {
            long m=call(56,-100,(long)path,0,0,0,0);
            long result=m<0?m:call(273,m,(long)params,0,0,0,0);
            record(path,"finit_module",result);
            if(m>=0)call(57,m,0,0,0,0,0);
            call(94,result==0?0:1,0,0,0,0,0);
            __builtin_unreachable();
        }
        if(child<0)record(path,"clone-error",child);
        else {
            int status=0;long waited;
            do{waited=call(260,child,(long)&status,0,0,0,0);}while(waited==-4);
            record(path,"wait-status",waited<0?waited:status);
        }
    }
    record("complete","diagnostic-handoff-to-original-init",1);
    /* Detach only the three pseudo-filesystems mounted by this diagnostic
     * entrypoint. The original first-stage init expects to mount them itself. */
    call(39,(long)"/sys",2,0,0,0,0);
    call(39,(long)"/proc",2,0,0,0,0);
    call(39,(long)"/dev",2,0,0,0,0);
    char *argv[]={"/init",0};
    char *envp[]={"HOME=/","TERM=linux",0};
    long failed=call(221,(long)"/init",(long)argv,(long)envp,0,0,0);
    record("original-init","exec-error",failed);
    for(;;) {long t[2]={1,0};call(101,(long)t,0,0,0,0,0);}
}
__attribute__((naked,noreturn)) void _start(void) {__asm__ volatile("b diag_main");}


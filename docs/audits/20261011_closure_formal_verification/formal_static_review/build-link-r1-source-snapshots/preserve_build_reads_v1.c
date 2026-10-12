#define _GNU_SOURCE
#include <dlfcn.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>
/* Audit instrumentation only. Capture bytes from successful read descriptors
 * in this build's output; no original file modification or syscall skipping. */
static __thread int busy;
static __thread unsigned long sequence;
static void retain_fd(int fd) {
    if (busy || fd < 0) return;
    busy=1;
    const char *base=getenv("TSBENCH_AUDIT_INPUT_ROOT");
    const char *destination=getenv("TSBENCH_AUDIT_CAPTURE_DIR");
    if (!base || !destination) goto done;
    char proc[64],original[8192],copied[8192],index[8192],line[17000];
    snprintf(proc,sizeof(proc),"/proc/self/fd/%d",fd);
    long n=syscall(SYS_readlinkat,AT_FDCWD,proc,original,sizeof(original)-1);
    if(n<=0) goto done;
    original[n]=0;
    if(strncmp(original,base,strlen(base)) && strncmp(original,"/tmp/cc",7)) goto done;
    if(strstr(original,"/read-capture/") || strstr(original,"/temporary-capture/") || strstr(original,"/trace/")) goto done;
    struct stat st;
    if(fstat(fd,&st) || !S_ISREG(st.st_mode)) goto done;
    /* Permanent compiled objects/archives are separately checkpointed before
     * ld/ar consumption; retaining them again would duplicate GiB of evidence. */
    size_t len=strlen(original);
    int permanent_binary=(len>2 && !strcmp(original+len-2,".o")) ||
                         (len>2 && !strcmp(original+len-2,".a")) ||
                         (len>3 && !strcmp(original+len-3,".so"));
    if(permanent_binary && !strstr(original,"/CMakeTmp/") && strncmp(original,"/tmp/cc",7)) goto done;
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME,&ts);
    snprintf(copied,sizeof(copied),"%s/preopen-%ld-%lu.bin",destination,(long)getpid(),++sequence);
    int out=syscall(SYS_openat,AT_FDCWD,copied,O_CREAT|O_EXCL|O_WRONLY|O_CLOEXEC,0600);
    if(out<0) goto done;
    char buffer[16384]; off_t offset=0; int failed=0;
    while(offset<st.st_size){
        ssize_t got=pread(fd,buffer,sizeof(buffer),offset);
        if(got<=0){failed=1;break;}
        ssize_t sent=0;
        while(sent<got){long count=syscall(SYS_write,out,buffer+sent,got-sent);if(count<=0){failed=1;break;}sent+=count;}
        if(failed)break;
        offset+=got;
    }
    syscall(SYS_close,out);
    snprintf(index,sizeof(index),"%s/preopen-%ld.tsv",destination,(long)getpid());
    int log=syscall(SYS_openat,AT_FDCWD,index,O_CREAT|O_APPEND|O_WRONLY|O_CLOEXEC,0600);
    if(log>=0){
        int length=snprintf(line,sizeof(line),"%lld.%09ld\t%s\t%s\t%lld\t%d\n",(long long)ts.tv_sec,ts.tv_nsec,original,copied,(long long)offset,failed);
        if(length>0 && length<(int)sizeof(line))syscall(SYS_write,log,line,length);
        syscall(SYS_close,log);
    }
done:busy=0;
}
#define OPEN_WRAPPER(name) \
int name(const char *path,int flags,...){ \
 static int (*real)(const char*,int,...); if(!real)real=dlsym(RTLD_NEXT,#name); \
 mode_t mode=0;if((flags&O_CREAT)||((flags&O_TMPFILE)==O_TMPFILE)){va_list ap;va_start(ap,flags);mode=va_arg(ap,int);va_end(ap);} \
 int fd=real(path,flags,mode);if((flags&O_ACCMODE)==O_RDONLY)retain_fd(fd);return fd; }
OPEN_WRAPPER(open)
OPEN_WRAPPER(open64)
#define OPENAT_WRAPPER(name) \
int name(int dir,const char *path,int flags,...){ \
 static int (*real)(int,const char*,int,...); if(!real)real=dlsym(RTLD_NEXT,#name); \
 mode_t mode=0;if((flags&O_CREAT)||((flags&O_TMPFILE)==O_TMPFILE)){va_list ap;va_start(ap,flags);mode=va_arg(ap,int);va_end(ap);} \
 int fd=real(dir,path,flags,mode);if((flags&O_ACCMODE)==O_RDONLY)retain_fd(fd);return fd; }
OPENAT_WRAPPER(openat)
OPENAT_WRAPPER(openat64)
#define FOPEN_WRAPPER(name) \
FILE *name(const char *path,const char *mode){ \
 static FILE *(*real)(const char*,const char*);if(!real)real=dlsym(RTLD_NEXT,#name); \
 FILE *file=real(path,mode);if(file && mode[0]=='r')retain_fd(fileno(file));return file; }
FOPEN_WRAPPER(fopen)
FOPEN_WRAPPER(fopen64)

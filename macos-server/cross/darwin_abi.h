/* Public Darwin C ABI used without an Apple SDK; no game implementation. */
#pragma once
#include <stddef.h>
#include <stdint.h>
#include <stdarg.h>
extern void *dlopen(const char *,int);
extern void *dlsym(void *,const char *);
extern char *realpath(const char *,char *);
extern size_t strlen(const char *);
extern char *strchr(const char *,int);
extern char *strrchr(const char *,int);
extern char *strstr(const char *,const char *);
extern int strcmp(const char *,const char *);
extern int strncmp(const char *,const char *,size_t);
extern void *memcpy(void *,const void *,size_t);
extern void *memset(void *,int,size_t);
extern void *malloc(size_t);
extern void *calloc(size_t,size_t);
extern void free(void *);
extern int snprintf(char *,size_t,const char *,...);
extern int _NSGetExecutablePath(char *,uint32_t *);
extern long read(int,void *,size_t);
extern long write(int,const void *,size_t);
extern int close(int);
extern int fcntl(int,int,...);
extern int *__error(void);
extern int getpid(void);
extern int kill(int,int);
extern int usleep(unsigned int);
#define RTLD_NOW 2
#define RTLD_GLOBAL 8
#define F_GETFL 3
#define F_SETFL 4
#define O_NONBLOCK 4
#define EAGAIN 35
int idoly_bundle_contents(char *,size_t);
int idoly_python_main(int,char **);
int idoly_app_main(int,char **);

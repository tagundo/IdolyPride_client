#include "darwin_abi.h"

int idoly_bundle_contents(char *out,size_t capacity) {
    char path[8192],canonical[8192];uint32_t size=sizeof(path);
    if(_NSGetExecutablePath(path,&size) || !realpath(path,canonical)) return 0;
    char *suffix=strstr(canonical,"/Contents/MacOS/");
    if(!suffix || strchr(suffix+16,'/')) return 0;
    size_t length=(size_t)(suffix-canonical)+9;
    if(length+1>capacity) return 0;
    memcpy(out,canonical,length);out[length]=0;return 1;
}

/* Encode filesystem bytes as a Python bytes literal; arbitrary UTF-8 paths
 * never become executable source or depend on a shell/locale quotation. */
static int literal(char *out,size_t capacity,const char *value) {
    static const char hex[]="0123456789abcdef";size_t length=strlen(value);
    if(length>(capacity-4)/4) return 0;
    size_t at=0;out[at++]='b';out[at++]='\'';
    for(size_t i=0;i<length;i++){unsigned char c=(unsigned char)value[i];out[at++]='\\';out[at++]='x';out[at++]=hex[c>>4];out[at++]=hex[c&15];}
    out[at++]='\'';out[at]=0;return 1;
}

int idoly_python_main(int argc,char **argv) {
    char contents[8192],library[9000],paths[30000],internal[9000],engine[9000];
    if(!idoly_bundle_contents(contents,sizeof(contents))) return 70;
    if(strchr(contents,':')) return 71;
    if(snprintf(internal,sizeof(internal),"%s/Resources/runtime/_internal",contents)>=(int)sizeof(internal)
       ||snprintf(library,sizeof(library),"%s/Python.framework/Versions/3.12/Python",internal)>=(int)sizeof(library)
       ||snprintf(engine,sizeof(engine),"%s/Resources/code/macos-server/engine.py",contents)>=(int)sizeof(engine)
       ||snprintf(paths,sizeof(paths),"%s/Resources/code/macos-server:%s/Resources/code/src:%s/base_library.zip:%s:%s/python3.12/lib-dynload",contents,contents,internal,internal,internal)>=(int)sizeof(paths))return 71;
    void *python=dlopen(library,RTLD_NOW|RTLD_GLOBAL);
    if(!python)return 72;
    wchar_t *(*decode)(const char *,size_t *)=(void*)dlsym(python,"Py_DecodeLocale");
    void (*setpath)(const wchar_t *)=(void*)dlsym(python,"Py_SetPath");
    void (*setprogram)(const wchar_t *)=(void*)dlsym(python,"Py_SetProgramName");
    void (*initialize)(void)=(void*)dlsym(python,"Py_Initialize");
    void (*setargv)(int,wchar_t **,int)=(void*)dlsym(python,"PySys_SetArgvEx");
    int (*execute)(const char *,void *)=(void*)dlsym(python,"PyRun_SimpleStringFlags");
    int (*finalize)(void)=(void*)dlsym(python,"Py_FinalizeEx");
    if(!decode||!setpath||!setprogram||!initialize||!setargv||!execute||!finalize)return 73;
    const char *flags[]={"Py_IsolatedFlag","Py_IgnoreEnvironmentFlag","Py_NoUserSiteDirectory","Py_NoSiteFlag","Py_DontWriteBytecodeFlag","Py_UTF8Mode"};
    for(size_t i=0;i<sizeof(flags)/sizeof(flags[0]);i++){int *flag=dlsym(python,flags[i]);if(flag)*flag=1;}
    wchar_t *widepaths=decode(paths,0),*program=decode(engine,0);
    if(!widepaths||!program)return 74;
    setpath(widepaths);setprogram(program);initialize();
    wchar_t **arguments=calloc((size_t)argc+1,sizeof(wchar_t *));
    if(!arguments)return 75;
    arguments[0]=program;
    for(int i=1;i<argc;i++){arguments[i]=decode(argv[i],0);if(!arguments[i])return 76;}
    setargv(argc,arguments,0);
    char internal_literal[37000],engine_literal[37000],source[76000];
    if(!literal(internal_literal,sizeof(internal_literal),internal)||!literal(engine_literal,sizeof(engine_literal),engine))return 77;
    if(snprintf(source,sizeof(source),"import sys, os\nsys.frozen=True\nsys._MEIPASS=os.fsdecode(%s)\nsys.prefix=sys.exec_prefix=sys.base_prefix=sys.base_exec_prefix=sys._MEIPASS\n__file__=os.fsdecode(%s)\n__name__='__main__'\n__package__=None\nexec(compile(open(__file__,'rb').read(),__file__,'exec'))\n",internal_literal,engine_literal)>=(int)sizeof(source))return 77;
    int result=execute(source,0);int ending=finalize();return result?1:(ending?120:0);
}

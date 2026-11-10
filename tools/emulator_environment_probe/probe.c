#include <jni.h>
#include <EGL/egl.h>
#include <GLES3/gl3.h>
#include <stdio.h>
#include <string.h>

extern float probe_fcvtzs(float input);
static void quote(char *out, size_t size, const char *value) {
    size_t n=0; if (size<3) return; out[n++]='"';
    for (; value && *value && n+7<size; value++) {
        unsigned char c=(unsigned char)*value;
        if (c=='"'||c=='\\') { out[n++]='\\';out[n++]=(char)c; }
        else if(c>=32&&c<127)out[n++]=(char)c;
        else out[n++]='?';
    }
    out[n++]='"';out[n]=0;
}
static GLuint compile(GLenum kind,const char* source,int* ok,char* log,size_t size){
    GLuint shader=glCreateShader(kind); glShaderSource(shader,1,&source,0);glCompileShader(shader);
    glGetShaderiv(shader,GL_COMPILE_STATUS,ok);GLsizei n=0;glGetShaderInfoLog(shader,(GLsizei)size-1,&n,log);log[n>=0?n:0]=0;return shader;
}
static void link_test(int vertex,char* output,size_t size){
    const char* vertex300="#version 300 es\nprecision highp float;uniform vec4 u[300];void main(){vec4 s=vec4(0.0);for(int i=0;i<300;i++){s+=u[i];}gl_Position=s;}";
    const char* fragment300="#version 300 es\nprecision highp float;uniform vec4 u[300];out vec4 c;void main(){vec4 s=vec4(0.0);for(int i=0;i<300;i++){s+=u[i];}c=s;}";
    const char* vertexBase="#version 300 es\nvoid main(){gl_Position=vec4(0.0,0.0,0.0,1.0);}";
    const char* fragmentBase="#version 300 es\nprecision highp float;out vec4 c;void main(){c=vec4(1.0);}";
    int vok=0,fok=0,linked=0,active=0,uniform_size=0;char vl[128]={0},fl[128]={0},ll[128]={0};
    GLuint vs=compile(GL_VERTEX_SHADER,vertex?vertex300:vertexBase,&vok,vl,sizeof(vl));
    GLuint fs=compile(GL_FRAGMENT_SHADER,vertex?fragmentBase:fragment300,&fok,fl,sizeof(fl));
    GLuint program=glCreateProgram();glAttachShader(program,vs);glAttachShader(program,fs);glLinkProgram(program);
    glGetProgramiv(program,GL_LINK_STATUS,&linked);GLsizei n=0;glGetProgramInfoLog(program,sizeof(ll)-1,&n,ll);ll[n>=0?n:0]=0;
    if(linked){glGetProgramiv(program,GL_ACTIVE_UNIFORMS,&active);for(int i=0;i<active;i++){char name[128];GLint count=0;GLenum type=0;glGetActiveUniform(program,(GLuint)i,sizeof(name),0,&count,&type,name);if(type==GL_FLOAT_VEC4&&count>uniform_size)uniform_size=count;}}
    char qvl[260],qfl[260],qll[260];quote(qvl,sizeof(qvl),vl);quote(qfl,sizeof(qfl),fl);quote(qll,sizeof(qll),ll);
    snprintf(output,size,"{\"vertex_compile\":%s,\"fragment_compile\":%s,\"link\":%s,\"active_vec4_array_size\":%d,\"vertex_log\":%s,\"fragment_log\":%s,\"link_log\":%s}",vok?"true":"false",fok?"true":"false",linked?"true":"false",uniform_size,qvl,qfl,qll);
    glDeleteProgram(program);glDeleteShader(vs);glDeleteShader(fs);
}
JNIEXPORT jstring JNICALL Java_org_idolypride_environmentprobe_ProbeActivity_nativeGraphics(JNIEnv* env,jclass cls){
    (void)cls;char result[25000];EGLDisplay display=eglGetDisplay(EGL_DEFAULT_DISPLAY);EGLContext context=EGL_NO_CONTEXT;EGLSurface surface=EGL_NO_SURFACE;
    EGLint major=0,minor=0,count=0;const char* stage="display";
    if(display==EGL_NO_DISPLAY)goto fail;
    stage="initialize";if(!eglInitialize(display,&major,&minor))goto fail;
    stage="bind_api";if(!eglBindAPI(EGL_OPENGL_ES_API))goto fail;
    EGLConfig config;EGLint attrs[]={EGL_SURFACE_TYPE,EGL_PBUFFER_BIT,EGL_RENDERABLE_TYPE,0x40,EGL_RED_SIZE,8,EGL_GREEN_SIZE,8,EGL_BLUE_SIZE,8,EGL_NONE};
    stage="choose_config";if(!eglChooseConfig(display,attrs,&config,1,&count)||!count)goto fail;
    EGLint ctxattrs[]={EGL_CONTEXT_CLIENT_VERSION,3,EGL_NONE};context=eglCreateContext(display,config,EGL_NO_CONTEXT,ctxattrs);
    stage="create_context";if(context==EGL_NO_CONTEXT)goto fail;
    EGLint pbattrs[]={EGL_WIDTH,16,EGL_HEIGHT,16,EGL_NONE};surface=eglCreatePbufferSurface(display,config,pbattrs);
    stage="create_pbuffer";if(surface==EGL_NO_SURFACE)goto fail;
    stage="make_current";if(!eglMakeCurrent(display,surface,surface,context))goto fail;
    GLint vertex=0,fragment=0;glGetIntegerv(GL_MAX_VERTEX_UNIFORM_VECTORS,&vertex);glGetIntegerv(GL_MAX_FRAGMENT_UNIFORM_VECTORS,&fragment);
    char vendor[260],renderer[260],version[260],vt[3000],ft[3000];quote(vendor,sizeof(vendor),(const char*)glGetString(GL_VENDOR));quote(renderer,sizeof(renderer),(const char*)glGetString(GL_RENDERER));quote(version,sizeof(version),(const char*)glGetString(GL_VERSION));
    link_test(1,vt,sizeof(vt));link_test(0,ft,sizeof(ft));
    snprintf(result,sizeof(result),"{\"ok\":true,\"egl_major\":%d,\"egl_minor\":%d,\"vendor\":%s,\"renderer\":%s,\"version\":%s,\"max_vertex_uniform_vectors\":%d,\"max_fragment_uniform_vectors\":%d,\"vertex_vec4_300\":%s,\"fragment_vec4_300\":%s}",major,minor,vendor,renderer,version,vertex,fragment,vt,ft);
    goto cleanup;
fail:
    snprintf(result,sizeof(result),"{\"ok\":false,\"stage\":\"%s\",\"egl_error\":%d}",stage,eglGetError());
cleanup:
    if(display!=EGL_NO_DISPLAY){eglMakeCurrent(display,EGL_NO_SURFACE,EGL_NO_SURFACE,EGL_NO_CONTEXT);if(surface!=EGL_NO_SURFACE)eglDestroySurface(display,surface);if(context!=EGL_NO_CONTEXT)eglDestroyContext(display,context);eglTerminate(display);}
    return (*env)->NewStringUTF(env,result);
}
JNIEXPORT jstring JNICALL Java_org_idolypride_environmentprobe_ProbeActivity_nativeConversion(JNIEnv* env,jclass cls){
    (void)cls;float positive=probe_fcvtzs(3.75f),negative=probe_fcvtzs(-3.75f);char result[512];
    snprintf(result,sizeof(result),"{\"ok\":%s,\"opcode\":\"5ea1b821\",\"instruction\":\"fcvtzs s1,s1\",\"positive_input\":3.75,\"positive_result\":%.9g,\"negative_input\":-3.75,\"negative_result\":%.9g}",(positive==3.0f&&negative==-3.0f)?"true":"false",(double)positive,(double)negative);
    return (*env)->NewStringUTF(env,result);
}
JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM* vm,void* reserved){(void)vm;(void)reserved;return JNI_VERSION_1_6;}

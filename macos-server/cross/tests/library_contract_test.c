#include <stdio.h>
#include <string.h>
#include "../library_contract.h"
static int checks;
#define CHECK(x) do { ++checks; if (!(x)) { fprintf(stderr,"library contract failed at %d\n",__LINE__); return 1; } } while(0)
int main(int argc,char **argv) {
    IDLibraryPrefs defaults=id_library_defaults(),value=defaults,decoded;
    char bytes[8193];
    CHECK(defaults.revision==0 && !defaults.hideVideo && defaults.mvSort==0 && defaults.outfitSort==0 && defaults.language==0);
    for (int mv=0;mv<4;++mv) for(int outfit=0;outfit<5;++outfit) for(int lang=0;lang<3;++lang) for(int hide=0;hide<2;++hide) {
        value.mvSort=mv;value.outfitSort=outfit;value.language=lang;value.hideVideo=hide;
        int n=id_library_encode(&value,bytes,sizeof bytes,0);
        CHECK(n > 0 && id_library_decode(bytes,(IDPSize)n,&decoded,0));
        CHECK(decoded.mvSort==mv && decoded.outfitSort==outfit && decoded.hideVideo==hide);
        n=id_library_encode(&value,bytes,sizeof bytes,1);
        CHECK(n > 0 && id_library_decode(bytes,(IDPSize)n,&decoded,1) && decoded.language==lang);
    }
    value=defaults;IDLibraryPrefs next;
    CHECK(id_library_next(&value,100,&next) && next.revision==100);
    CHECK(id_library_next(&next,100,&value) && value.revision==101);
    CHECK(id_library_next(&value,0,&next) && next.revision==102);
    value.revision=9223372036854775807LL;
    CHECK(id_library_encode(&value,bytes,sizeof bytes,0) && id_library_decode(bytes,strlen(bytes),&decoded,0));
    CHECK(decoded.revision==value.revision && !id_library_next(&value,1,&next));
    const char *bad[]={"{}","[]","null","{\"schema\":1,\"revision\":0,\"hide_video_mv\":false,\"mv_sort\":\"recent\",\"outfit_sort\":\"original\",\"schema\":1}",
        "{\"schema\":true,\"revision\":0,\"hide_video_mv\":false,\"mv_sort\":\"recent\",\"outfit_sort\":\"original\"}",
        "{\"schema\":1,\"revision\":-1,\"hide_video_mv\":false,\"mv_sort\":\"recent\",\"outfit_sort\":\"original\"}",
        "{\"schema\":1,\"revision\":0.0,\"hide_video_mv\":false,\"mv_sort\":\"recent\",\"outfit_sort\":\"original\"}",
        "{\"schema\":1,\"revision\":true,\"hide_video_mv\":false,\"mv_sort\":\"recent\",\"outfit_sort\":\"original\"}",
        "{\"schema\":1,\"revision\":0,\"hide_video_mv\":0,\"mv_sort\":\"recent\",\"outfit_sort\":\"original\"}",
        "{\"schema\":1,\"revision\":0,\"hide_video_mv\":false,\"mv_sort\":\"original\",\"outfit_sort\":\"original\"}",
        "{\"schema\":1,\"revision\":0,\"hide_video_mv\":false,\"mv_sort\":\"recent\",\"outfit_sort\":\"unknown\"}",
        "{\"schema\":1,\"revision\":9223372036854775808,\"hide_video_mv\":false,\"mv_sort\":\"recent\",\"outfit_sort\":\"original\"}",
        "{\"schema\":1,\"revision\":0,\"hide_video_mv\":false,\"mv_sort\":\"recent\",\"outfit_sort\":\"original\",}",
        "{\"schema\":1,\"revision\":0,\"hide_video_mv\":false,\"mv_sort\":\"recent\",\"outfit_sort\":\"original\"} trailing"};
    for (unsigned long i=0;i<sizeof bad/sizeof bad[0];++i) {
        decoded=value; CHECK(!id_library_decode(bad[i],strlen(bad[i]),&decoded,0) && decoded.revision==value.revision);
    }
    CHECK(id_library_encode(&defaults,bytes,sizeof bytes,0));
    IDPSize validLength=strlen(bytes);
    for (IDPSize i=0;i<validLength;++i) CHECK(!id_library_decode(bytes,i,&decoded,0));
    const char *badLanguage[]={"{}","{\"schema\":1,\"language\":\"kr\"}","{\"schema\":1,\"language\":false}",
        "{\"schema\":1,\"language\":\"en\",\"language\":\"ko\"}","{\"schema\":1,\"language\":\"ja\",\"revision\":0}",
        "{\"schema\":1,\"language\":\"en\",\"\\u0073chema\":1}"};
    for(unsigned long i=0;i<sizeof badLanguage/sizeof badLanguage[0];++i) CHECK(!id_library_decode(badLanguage[i],strlen(badLanguage[i]),&decoded,1));
    memset(bytes,' ',sizeof bytes); CHECK(!id_library_decode(bytes,sizeof bytes,&decoded,0));
    CHECK(!id_library_decode(0,0,&decoded,0));
    char tiny[5]={'x','x','x','x','S'};CHECK(!id_library_encode(&defaults,tiny,4,0) && tiny[4]=='S');
    value=defaults;value.language=3;CHECK(!id_library_encode(&value,bytes,sizeof bytes,1));
    CHECK(id_resource_active("preparing") && id_resource_active("running") && id_resource_active("export_ready") && id_resource_active("cancelling"));
    CHECK(!id_resource_active("completed") && !id_resource_active("partial") && !id_resource_active(0));
    CHECK(id_resource_job_valid("7e95d_8-A") && !id_resource_job_valid("bad\"id") && !id_resource_job_valid(""));
    char job[66];memset(job,'a',64);job[64]=0;CHECK(id_resource_job_valid(job));job[64]='b';job[65]=0;CHECK(!id_resource_job_valid(job));
    const char *actions[]={"resources_preview","resources_download","resources_export","resources_import","resources_cancel"};
    for(int i=0;i<5;++i) {
        int n=id_resource_command(actions[i],"ios",i==4 ? "0ab123" : i>=2 ? "/tmp/앨범\"\\\n.zip" : 0,bytes,sizeof bytes);
        CHECK(n > 0 && n <= 512 && bytes[n-1]=='\n' && !bytes[n]);
        if (argc==2 && !strcmp(argv[1],"--commands")) fputs(bytes,stdout);
    }
    CHECK(!id_resource_command("quit","ios",0,bytes,sizeof bytes));
    CHECK(!id_resource_command("resources_download","unknown",0,bytes,sizeof bytes));
    CHECK(!id_resource_command("resources_preview","ios","extra",bytes,sizeof bytes));
    CHECK(!id_resource_command("resources_export","ios","relative.zip",bytes,sizeof bytes));
    CHECK(!id_resource_command("resources_import","ios","/tmp/file.apk",bytes,sizeof bytes));
    CHECK(!id_resource_command("resources_cancel","ios","bad\"id",bytes,sizeof bytes));
    char largePath[600];memset(largePath,'a',sizeof largePath);largePath[0]='/';memcpy(largePath+595,".zip",5);
    CHECK(!id_resource_command("resources_export","ios",largePath,bytes,sizeof bytes));
    CHECK(!id_resource_command("resources_export","ios","/tmp/file.zip",tiny,4) && tiny[4]=='S');
    if(argc==2 && !strcmp(argv[1],"--commands")) return 0;
    CHECK(id_resources_in_downloads(0,0) && id_resources_in_downloads(0,1) && id_resources_in_downloads(1,1));
    CHECK(!id_resources_in_downloads(1,0));
    for(int live=0;live<2;++live)for(int media=0;media<2;++media)for(int download=0;download<2;++download) {
        int count=id_server_start_command(live,media,download,"/Users/local/Downloads/IdolyPride",bytes,sizeof bytes);
        CHECK(count > 0 && count <= 512 && bytes[count-1]=='\n' && !bytes[count]);
    }
    CHECK(id_server_start_command(0,1,1,0,bytes,sizeof bytes) && strstr(bytes,"\"resource_cache_dir\":null"));
    CHECK(!id_server_start_command(2,0,1,0,bytes,sizeof bytes));
    CHECK(!id_server_start_command(0,-1,1,0,bytes,sizeof bytes));
    CHECK(!id_server_start_command(0,0,2,0,bytes,sizeof bytes));
    CHECK(!id_server_start_command(0,0,1,"relative/directory",bytes,sizeof bytes));
    CHECK(!id_server_start_command(0,0,1,"",bytes,sizeof bytes));
    CHECK(!id_server_start_command(0,0,1,largePath,bytes,sizeof bytes));
    CHECK(!id_server_start_command(0,0,1,0,tiny,4) && tiny[4]=='S');
    if(argc==2 && !strcmp(argv[1],"--start-commands")) {
        CHECK(id_server_start_command(0,1,1,"/Users/테스트\"\\\n/Downloads/IdolyPride",bytes,sizeof bytes));fputs(bytes,stdout);
        CHECK(id_server_start_command(1,0,0,0,bytes,sizeof bytes));fputs(bytes,stdout);return 0;
    }
    if(argc==2 && !strcmp(argv[1],"--json")) {
        value=defaults;value.revision=102;value.hideVideo=1;value.mvSort=2;value.outfitSort=3;value.language=1;
        CHECK(id_library_encode(&value,bytes,sizeof bytes,0));puts(bytes);
        CHECK(id_library_encode(&value,bytes,sizeof bytes,1));puts(bytes);return 0;
    }
    printf("PASS: %d independent library preference/IPC checks\n",checks);return 0;
}

#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "../library_contract.h"

int main(void) {
    for (int flags=0;flags<64;++flags)
        assert(id_resource_location_change_allowed(flags&1,flags&2,flags&4,flags&8,flags&16,flags&32)==(flags==0));
    const char *path="/Volumes/보관 디스크/아이프라 \"공연\"\\ 자료";
    assert(id_resource_location_path_valid(path,strlen(path)));
    assert(!id_resource_location_path_valid("relative/path",13));
    assert(!id_resource_location_path_valid("/prefix\0suffix",14));
    assert(!id_resource_location_path_valid("/",4097));
    char command[513];
    assert(id_server_start_command(0,0,0,path,command,sizeof command));
    assert(strstr(command,"보관 디스크") && strstr(command,"\\\"공연\\\"") && strstr(command,"\\\\ 자료"));
    puts(command);
    assert(id_server_start_command(0,0,0,0,command,sizeof command));
    assert(strstr(command,"\"resource_cache_dir\":null"));
    puts(command);
    char longest[520];longest[0]='/';
    int exact=0;
    for (int n=1;n<519;++n) {
        if (n>1) longest[n-1]='x';
        longest[n]=0;
        int count=id_server_start_command(0,0,0,longest,command,sizeof command);
        if (count==512) {
            exact=1;longest[n]='x';longest[n+1]=0;
            assert(!id_server_start_command(0,0,0,longest,command,sizeof command));break;
        }
    }
    assert(exact);
    puts("RESOURCE_LOCATION_POLICY_PASS");
    return 0;
}

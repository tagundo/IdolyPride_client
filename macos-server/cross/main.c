#include "darwin_abi.h"
int main(int argc,char **argv) {
    if(argc>1 && !strcmp(argv[1],"--engine")) return idoly_python_main(argc-1,argv+1);
    return idoly_app_main(argc,argv);
}

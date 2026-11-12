// Bounded schema-1 settings decoder shared by host QA and the iOS poller.
#pragma once
namespace idoly::presentation {
inline void json_space(const char *&p) { while (*p==' ' || *p=='\n' || *p=='\r' || *p=='\t') ++p; }
inline bool decode_settings(const char *input, Config *out) {
    const char *keys[] = {"schema", "revision", "custom_graphics", "quality", "target_fps",
        "render_scale", "max_buffer_pixel", "anti_aliasing", "shadow_resolution", "expand_photography"};
    Config value; int schema = 0; unsigned seen = 0;
    const char *p=input; json_space(p); if (*p++!='{') return false;
    for (unsigned count=0; count<10; ++count) {
        json_space(p); if (*p++!='"') return false;
        char key[32]; unsigned n=0;
        while (*p && *p!='"' && n+1<sizeof key) { if (*p=='\\' || (unsigned char)*p<32) return false; key[n++]=*p++; }
        key[n]=0; if (*p++!='"') return false;
        int id=-1; for (int i=0;i<10;++i) if (!std::strcmp(key,keys[i])) id=i;
        if (id<0 || (seen & (1u<<id))) return false; seen|=1u<<id;
        json_space(p); if (*p++!=':') return false; json_space(p);
        if (id==2 || id==9) {
            bool flag;
            if (!strncmp(p,"true",4)) { flag=true; p+=4; }
            else if (!strncmp(p,"false",5)) { flag=false; p+=5; }
            else return false;
            if (id==2) value.custom_graphics=flag; else value.expand_photography=flag;
        } else {
            const char *begin=p; bool negative=*p=='-'; if (negative) ++p;
            if (*p=='0') { ++p; if (*p>='0' && *p<='9') return false; }
            else { if (*p<'1' || *p>'9') return false; while (*p>='0' && *p<='9') ++p; }
            bool fractional=false;
            if (*p=='.') { fractional=true; ++p; if (*p<'0'||*p>'9') return false; while (*p>='0'&&*p<='9') ++p; }
            if (*p=='e'||*p=='E') { fractional=true; ++p; if (*p=='+'||*p=='-') ++p;
                if (*p<'0'||*p>'9') return false; while (*p>='0'&&*p<='9') ++p; }
            const size_t size=p-begin; if (!size || size>=64) return false;
            char number[64]; std::memcpy(number,begin,size); number[size]=0;
            if (id==5) { char *end; double scale=strtod(number,&end);
                if (*end || !std::isfinite(scale) || scale<.25 || scale>2) return false;
                value.render_scale=static_cast<float>(scale);
            } else {
                if (fractional) return false;
                uint64_t integer=0; const char *digit=begin+(negative?1:0);
                while (digit<p) { unsigned d=*digit++-'0';
                    if (integer>922337203685477580ull || (integer==922337203685477580ull && d>7)) return false;
                    integer=integer*10+d;
                }
                if (id==1) { if (negative) return false; value.revision=static_cast<int64_t>(integer); }
                else { if (integer>2147483647) return false; int v=static_cast<int>(integer); if (negative) v=-v;
                    if (id==0) schema=v; else if (id==3) value.quality=v; else if (id==4) value.target_fps=v;
                    else if (id==6) value.max_buffer_pixel=v; else if (id==7) value.aa_mode=v;
                    else if (id==8) value.shadow_resolution=v;
                }
            }
        }
        json_space(p);
        if (count==9) { if (*p++!='}') return false; }
        else if (*p++!=',') return false;
    }
    json_space(p); if (*p || seen!=1023 || !config_valid(schema,value)) return false;
    *out=value; return true;
}
}

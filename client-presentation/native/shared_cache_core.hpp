#pragma once

// No Unity, Python, filesystem or allocation calls. The bridge serializes access.
namespace idoly::presentation::shared_cache {
inline constexpr size_t request_size = 80, response_size = 104;
inline constexpr size_t max_filename = 64, max_path = 2048, pending_limit = 64, cache_limit = 8192;
struct Key {
    uint8_t kind=0;
    uint32_t upload=0;
    uint64_t generation=0, size=0;
    char object[6]{};
    uint8_t md5[16]{};
    char filename[max_filename+1]{};
    bool valid() const {
        if ((kind!=1 && kind!=2) || !upload || upload>0x7fffffffu || !generation || !size || size>0x7fffffffu) return false;
        for (char c:object) if (!((c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9'))) return false;
        return true;
    }
    bool same(const Key &other) const {
        return kind==other.kind && upload==other.upload && generation==other.generation && size==other.size
            && !std::memcmp(object,other.object,6) && !std::memcmp(md5,other.md5,16)
            && !std::strcmp(filename,other.filename);
    }
    uint32_t hash() const {
        uint32_t value=2166136261u;
        for (uint8_t c:md5) value=(value^c)*16777619u;
        for (size_t i=0;filename[i];++i) value=(value^static_cast<uint8_t>(filename[i]))*16777619u;
        return value^upload^static_cast<uint32_t>(generation)^kind;
    }
};
inline void put(uint8_t *target,uint64_t value,size_t bytes) {
    for (size_t i=0;i<bytes;++i) { target[i]=static_cast<uint8_t>(value); value>>=8; }
}
inline uint64_t get(const uint8_t *source,size_t bytes) {
    uint64_t value=0;
    for (size_t i=bytes;i>0;--i) value=(value<<8)|source[i-1];
    return value;
}
inline bool filename_valid(const char *name,size_t length,const Key &key) {
    if (!name || length<32 || length>max_filename) return false;
    constexpr char hex[]="0123456789abcdef";
    for (size_t i=0;i<32;++i) if (name[i]!=hex[(key.md5[i/2]>>(i%2?0:4))&15]) return false;
    if (length==32) return true;
    if (name[32]!='.' || length==33 || length>49) return false;
    for (size_t i=33;i<length;++i) {
        char c=name[i];
        if (!((c>='a'&&c<='z')||(c>='0'&&c<='9'))) return false;
    }
    return key.kind==2;
}
inline bool encode_request(uint8_t *output,uint8_t platform,const Key &key,
        const uint8_t token[16],uint64_t epoch,const char *filename,size_t length) {
    if ((platform!=1&&platform!=2)||!epoch||epoch>9007199254740991ull||!key.valid()||!filename_valid(filename,length,key)) return false;
    for (size_t i=0;i<request_size;++i) output[i]=0;
    std::memcpy(output,"IDRSREQ1",8);put(output+8,1,2);output[10]=platform;output[11]=key.kind;
    std::memcpy(output+12,token,16);put(output+28,epoch,8);put(output+36,key.upload,4);
    put(output+40,key.generation,8);put(output+48,key.size,8);std::memcpy(output+56,key.object,6);
    put(output+62,length,2);std::memcpy(output+64,key.md5,16);std::memcpy(output+80,filename,length);
    return true;
}
struct Stamp {
    uint64_t device=0,inode=0,size=0;
    int64_t modified_ns=0,changed_ns=0;
    uint32_t mode=0,links=0;
};
struct Receipt:Stamp {char path[max_path+1]{};};
inline bool decode_response(const uint8_t *input,size_t length,const uint8_t token[16],
        uint64_t epoch,const Key &key,const char *directory,Receipt &receipt) {
    if (!input||length<response_size||std::memcmp(input,"IDRSRSP1",8)||get(input+8,2)!=1
            ||input[10]!=0||input[11]!=1||std::memcmp(input+12,token,16)||get(input+28,8)!=epoch
            ||std::memcmp(input+36,key.md5,16)||get(input+52,8)!=key.size||get(input+102,2)) return false;
    size_t count=static_cast<size_t>(get(input+100,2));
    if (!count||count>max_path||length!=response_size+count) return false;
    const char *path=reinterpret_cast<const char *>(input+response_size);
    const size_t prefix=std::strlen(directory);
    if (count<=prefix+7 || std::memcmp(path,directory,prefix)||std::memcmp(path+prefix,"/views/",7)) return false;
    // Paths are server-produced UTF-8, but reject separators/terminators which
    // could escape the private view. The canonical view may contain spaces.
    for (size_t i=0;i<count;++i) if (!path[i]||path[i]=='\n'||path[i]=='\r'||path[i]=='\\') return false;
    for (size_t i=prefix+7;i<count;++i)
        if (path[i]=='.' && (i==prefix+7||path[i-1]=='/')
                && (i+1==count||path[i+1]=='/'||(path[i+1]=='.'&&(i+2==count||path[i+2]=='/')))) return false;
    const uint32_t mode=static_cast<uint32_t>(get(input+92,4)), links=static_cast<uint32_t>(get(input+96,4));
    if ((mode&0170000u)!=0100000u || (mode&0222u)||links!=1) return false;
    receipt.device=get(input+60,8);receipt.inode=get(input+68,8);receipt.size=key.size;
    receipt.modified_ns=static_cast<int64_t>(get(input+76,8));receipt.changed_ns=static_cast<int64_t>(get(input+84,8));
    receipt.mode=mode;receipt.links=links;std::memcpy(receipt.path,path,count);receipt.path[count]=0;
    return receipt.inode!=0;
}
struct Arguments { uint32_t loader=0,name=0,complete=0,progress=0; const void *method=nullptr; bool auto_delete=false; };
enum class Stage:uint8_t { empty,queued,waiting,complete };
struct Pending {
    Stage stage=Stage::empty;
    uint64_t epoch=0,started_ms=0;
    Key key;
    Arguments arguments;
    uint8_t token[16]{};
    char filename[max_filename+1]{},basename[40]{};
    bool prepared=false;
};
struct Entry { bool occupied=false;uint64_t epoch=0;Key key;Stamp stamp;uint8_t prefix=0;char tail[96]{}; };
struct Index {
    Entry entries[cache_limit]{};
    char prefixes[32][max_path+1]{};
    size_t prefix_count=0,entry_count=0;
    bool insert(uint64_t epoch,const Key &key,const Receipt &receipt) {
        const size_t length=std::strlen(receipt.path);
        size_t split=length;unsigned separators=0;
        while (split && separators<2) if (receipt.path[--split]=='/') ++separators;
        if (separators!=2 || length-split>=sizeof entries[0].tail) return false;
        size_t prefix=0;
        for (;prefix<prefix_count;++prefix)
            if (std::strlen(prefixes[prefix])==split&&!std::memcmp(prefixes[prefix],receipt.path,split)) break;
        if (prefix==prefix_count) {
            if (prefix_count==32) return false;
            std::memcpy(prefixes[prefix],receipt.path,split);prefixes[prefix][split]=0;++prefix_count;
        }
        const size_t first=key.hash()%cache_limit;
        for (size_t i=0;i<cache_limit;++i) {
            const size_t at=(first+i)%cache_limit;
            auto &entry=entries[at];
            if (!entry.occupied || (entry.epoch==epoch&&entry.key.same(key))) {
                if (!entry.occupied) ++entry_count;
                entry.occupied=true;entry.epoch=epoch;entry.key=key;entry.stamp=receipt;
                entry.prefix=static_cast<uint8_t>(prefix);std::memcpy(entry.tail,receipt.path+split,length-split+1);
                return true;
            }
        }
        return false; // Never evict a path already advertised as Latest.
    }
    bool find(uint64_t epoch,const Key &key,Receipt &receipt,bool earlier_epoch=false) const {
        const size_t first=key.hash()%cache_limit;
        for (size_t i=0;i<cache_limit;++i) {
            const Entry &entry=entries[(first+i)%cache_limit];
            if (!entry.occupied) return false;
            if ((entry.epoch==epoch||earlier_epoch)&&entry.key.same(key)) {
                static_cast<Stamp &>(receipt)=entry.stamp;
                const int n=std::snprintf(receipt.path,sizeof receipt.path,"%s%s",prefixes[entry.prefix],entry.tail);
                return n>0&&static_cast<size_t>(n)<sizeof receipt.path;
            }
        }
        return false;
    }
};
} // namespace idoly::presentation::shared_cache

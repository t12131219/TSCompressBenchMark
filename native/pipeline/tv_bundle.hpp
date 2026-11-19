#pragma once
#include "plugin_loader.hpp"

#include <algorithm>
#include <array>
#include <cstring>
#include <string>
#include <vector>

namespace tsbench::tv {
using Bytes = std::vector<uint8_t>;
constexpr size_t max_rows=8192, max_columns=6, max_chunk=512, max_entries=256;
constexpr size_t max_frame=2*1024*1024, max_schema=65536;
constexpr size_t header=96, entry=40;
constexpr std::array<uint8_t,8> magic{'B','M','K','T','V','B',1,0};

inline void must(bool ok,const char *why,bmk_status code=BMK_CORRUPT) {
    if (!ok) throw PluginError(code,why);
}
inline void put(uint8_t *p,size_t n,uint64_t x) {
    for (size_t i=0;i<n;++i) p[i]=static_cast<uint8_t>(x>>(8*i));
}
inline uint64_t get(const uint8_t *p,size_t n) {
    uint64_t x=0;
    for (size_t i=0;i<n;++i) x|=uint64_t(p[i])<<(8*i);
    return x;
}
inline uint32_t crc32(const uint8_t *p,size_t n) {
    uint32_t x=0xffffffffU;
    for (size_t i=0;i<n;++i) {
        x^=p[i];
        for (int b=0;b<8;++b) x=(x>>1)^(0xedb88320U & (0U-(x&1U)));
    }
    return ~x;
}
struct Stride { size_t row,rows,first,columns,group; };
enum class Routing { pair, separate, grouped_limbs };
struct Layout {
    size_t rows, columns, chunk;
    std::string_view id;
    Routing routing;
    size_t groups;
    std::vector<Stride> slots;
    Layout(size_t r,size_t c,size_t k,std::string_view method,Routing route):rows(r),columns(c),chunk(k),id(method),routing(route),
        groups(route==Routing::pair ? 1 : route==Routing::grouped_limbs ? 2 : c) {
        const bool joint=routing==Routing::pair;
        must(rows<=max_rows && columns>=2 && columns<=max_columns && chunk>=1 && chunk<=max_chunk &&
             (!joint || columns==2) && id.size()==64 && id.find_first_not_of("0123456789abcdef")==std::string_view::npos,
             "invalid TV layout or method",BMK_BAD_INPUT);
        const size_t blocks=rows ? (rows+chunk-1)/chunk : 1;
        must(blocks<=max_entries/groups,"TV directory exceeds bound",BMK_RESOURCE_LIMIT);
        for (size_t i=0;i<blocks;++i)
            for (size_t group=0;group<groups;++group)
                slots.push_back({i*chunk,std::min(chunk,rows-i*chunk),joint ? 0 : group,
                                 joint ? 2U : routing==Routing::grouped_limbs && group==1 ? columns-1 : 1U,group});
    }
};
struct Slice { size_t offset,bytes; };
inline void begin(Bytes &frame,const Layout &layout,const Bytes &schema) {
    must(!schema.empty() && schema.size()<=max_schema,"invalid object schema",BMK_BAD_INPUT);
    frame.resize(header+entry*layout.slots.size()+schema.size());
    auto *p=frame.data();
    std::copy(magic.begin(),magic.end(),p);
    put(p+8,4,layout.rows); put(p+12,4,layout.columns); put(p+16,4,layout.chunk);
    put(p+20,4,layout.slots.size()); put(p+24,4,schema.size());
    put(p+28,4,crc32(schema.data(),schema.size()));
    std::memcpy(p+32,layout.id.data(),64);
    std::copy(schema.begin(),schema.end(),frame.begin()+header+entry*layout.slots.size());
}
inline void append(Bytes &frame,const Layout &layout,size_t i,const bmk_blob &blob) {
    must(blob.size && blob.size<=max_frame-frame.size(),"TV payload exceeds frame budget",BMK_RESOURCE_LIMIT);
    const auto &slot=layout.slots.at(i);
    auto *p=frame.data()+header+i*entry;
    put(p,4,slot.row); put(p+4,4,slot.rows); put(p+8,4,slot.first); put(p+12,4,slot.columns);
    put(p+16,8,frame.size()); put(p+24,8,blob.size); put(p+32,4,crc32(blob.data,blob.size));
    frame.insert(frame.end(),blob.data,blob.data+blob.size);
}
inline std::vector<Slice> read_bundle(const Bytes &wire,const Layout &layout,Bytes &schema) {
    const size_t boundary=header+entry*layout.slots.size();
    const auto *p=wire.data();
    must(wire.size()>=boundary && wire.size()<=max_frame && std::equal(magic.begin(),magic.end(),p),"invalid TV container header");
    const size_t scope=get(p+24,4);
    must(get(p+8,4)==layout.rows && get(p+12,4)==layout.columns && get(p+16,4)==layout.chunk &&
        get(p+20,4)==layout.slots.size() && scope && scope<=max_schema && scope<=wire.size()-boundary &&
        !std::memcmp(p+32,layout.id.data(),64),"TV method, layout or schema bound differs");
    must(crc32(p+boundary,scope)==get(p+28,4),"bad object schema CRC");
    auto offset=boundary+scope;
    std::vector<Slice> slices;
    for (size_t i=0;i<layout.slots.size();++i) {
        const auto &s=layout.slots[i];
        const auto *e=p+header+i*entry;
        const uint64_t n=get(e+24,8);
        must(get(e,4)==s.row && get(e+4,4)==s.rows && get(e+8,4)==s.first && get(e+12,4)==s.columns &&
             get(e+16,8)==offset && n && n<=wire.size()-offset && get(e+36,4)==0,"invalid/missing TV stream or row/column index");
        must(crc32(p+offset,n)==get(e+32,4),"TV payload CRC mismatch");
        slices.push_back({offset,static_cast<size_t>(n)});
        offset+=n;
    }
    must(offset==wire.size(),"trailing TV data");
    schema.assign(p+boundary,p+boundary+scope);
    return slices;
}
}

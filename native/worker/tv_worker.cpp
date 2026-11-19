#include "f64_limbs.hpp"

#include <charconv>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <utility>

namespace {
using namespace tsbench::tv;
constexpr std::string_view time_schema="{\"time_unit\":\"ms\"}", value_schema="{\"role\":\"value\",\"dtype\":\"f64\"}";
constexpr std::string_view limb_schema="{\"dtype\":\"u16\",\"layout\":\"f64-le-limbs-row-major\"}";
struct Branch { tsbench::Module module; std::string_view options; };
size_t number(std::string_view text) {
    size_t n=0;
    const auto rc=std::from_chars(text.data(),text.data()+text.size(),n);
    must(rc.ec==std::errc{} && rc.ptr==text.data()+text.size(),"invalid numeric parameter",BMK_BAD_INPUT);
    return n;
}
uint32_t dtype(size_t i) { return i==0 ? BMK_I64 : BMK_F64; }
Bytes load(const char *path,size_t cap) {
    must(std::filesystem::is_regular_file(path),"input is not a regular file",BMK_BAD_INPUT);
    std::ifstream f(path,std::ios::binary|std::ios::ate);
    const auto end=f.tellg();
    must(end>=0 && static_cast<uint64_t>(end)<=cap,"cannot read input within budget",BMK_RESOURCE_LIMIT);
    Bytes data(static_cast<size_t>(end));
    f.seekg(0);
    if (!data.empty()) f.read(reinterpret_cast<char *>(data.data()),end);
    must(bool(f) && f.peek()==EOF && !f.bad(),"input changed or read failed",BMK_BAD_INPUT);
    return data;
}
void save(const char *path,const Bytes &bytes) {
    must(!std::filesystem::exists(path),"output path already exists",BMK_BAD_INPUT);
    std::ofstream f(path,std::ios::binary);
    if (!bytes.empty()) f.write(reinterpret_cast<const char *>(bytes.data()),bytes.size());
    f.close();
    if (!f) throw std::runtime_error("failed to write TV output");
}
bmk_array_view input(const Bytes &data,uint32_t type,size_t offset,size_t count,uint32_t width) {
    bmk_array_view view{};
    view.struct_size=sizeof(view); view.dtype=type; view.rank=1;
    view.storage=data.data(); view.storage_bytes=data.size(); view.origin_offset=offset;
    view.shape[0]=count; view.strides_bytes[0]=width;
    return view;
}
const uint8_t *checked_output(const bmk_array_view &in,uint32_t type,size_t count,size_t width) {
    const auto n=count*width;
    must(in.struct_size>=sizeof(in) && in.dtype==type && in.rank==1 && !in.flags &&
        !in.validity && !in.validity_bytes && !in.validity_bit_offset && in.strides_bytes[0]==width && in.shape[0]==count &&
        in.origin_offset<=in.storage_bytes && n<=in.storage_bytes-in.origin_offset && in.origin_offset<=SIZE_MAX-n &&
        (!n || in.storage),"restored TV column layout differs");
    return n ? static_cast<const uint8_t *>(in.storage)+in.origin_offset : nullptr;
}
std::string observation(tsbench::Context &ctx) {
    const auto info=ctx.execution_info();
    const auto &r=info->get();
    must(r.data && r.size>=2 && r.size<=4096 && r.data[0]=='{' && r.data[r.size-1]=='}',"invalid branch execution metadata",BMK_INTERNAL);
    return std::string(reinterpret_cast<const char *>(r.data),r.size);
}
}

int main(int argc,char **argv) {
    if (argc<14) {
        std::cerr << "tv_worker encode|decode FRAME SCHEMA METHOD_SHA ROWS CHUNK pair|separate|grouped-limbs COLUMNS (DSO PLUGIN OPTIONS)+ (COLUMN_PATHS)+\n";
        return 2;
    }
    try {
        const std::string_view op=argv[1], kind=argv[7];
        const bool encode=op=="encode";
        must((encode || op=="decode") && (kind=="pair" || kind=="separate" || kind=="grouped-limbs"),
             "bad TV operation or layout",BMK_BAD_INPUT);
        const Layout layout(number(argv[5]),number(argv[8]),number(argv[6]),argv[4],
            kind=="pair" ? Routing::pair : kind=="separate" ? Routing::separate : Routing::grouped_limbs);
        const size_t ng=layout.groups;
        must(static_cast<size_t>(argc)==9+3*ng+layout.columns,"bad TV argument count",BMK_BAD_INPUT);
        std::vector<Branch> branches;
        std::vector<Bytes> columns;
        size_t at=9;
        for (size_t g=0;g<ng;++g,at+=3) {
            const std::string_view options=argv[at+2];
            must(options.size()<=max_schema,"TV options exceed bound",BMK_RESOURCE_LIMIT);
            branches.push_back({tsbench::PluginModule::load(argv[at],argv[at+1]),options});
        }
        for (size_t c=0;c<layout.columns;++c) {
            auto data=encode ? load(argv[at+c],layout.rows*8) : Bytes(layout.rows*8);
            must(data.size()==layout.rows*8,"TV source column row mismatch",BMK_BAD_INPUT);
            columns.push_back(std::move(data));
        }
        Bytes schema,frame;
        std::vector<Slice> slices;
        if (encode) { schema=load(argv[3],max_schema); begin(frame,layout,schema); }
        else { frame=load(argv[2],max_frame); slices=read_bundle(frame,layout,schema); }
        std::vector<std::string> facts;
        for (size_t i=0;i<layout.slots.size();++i) {
            const auto &slot=layout.slots[i];
            const auto &branch=branches[slot.group];
            const bool limbs=layout.routing==Routing::grouped_limbs && slot.first!=0;
            const auto sch=limbs ? limb_schema : slot.first==0 ? time_schema : value_schema;
            const size_t physical_columns=limbs ? 1 : slot.columns;
            tsbench::Context ctx(branch.module,branch.options);
            if (encode) {
                bmk_array_view views[2]{};
                Bytes packed;
                if (limbs) {
                    packed=pack_limbs(columns,slot);
                    views[0]=input(packed,BMK_U16,0,slot.rows*slot.columns*4,2);
                } else for (size_t c=0;c<slot.columns;++c) {
                    const auto j=slot.first+c;
                    views[c]=input(columns[j],dtype(j),slot.row*8,slot.rows,8);
                }
                bmk_object_view view{sizeof(view),static_cast<uint32_t>(physical_columns),views,
                    reinterpret_cast<const uint8_t *>(sch.data()),sch.size()};
                const auto stream=ctx.encode(view);
                append(frame,layout,i,stream->get());
            } else {
                const auto slice=slices.at(i);
                const auto restored=ctx.decode(frame.data()+slice.offset,slice.bytes);
                const auto &view=restored->get();
                must(view.column_count==physical_columns && view.columns && view.schema_json && view.schema_bytes==sch.size() &&
                    !std::memcmp(view.schema_json,sch.data(),sch.size()),"restored TV child schema differs");
                if (limbs) {
                    const auto *payload=checked_output(view.columns[0],BMK_U16,slot.rows*slot.columns*4,2);
                    unpack_limbs(payload,columns,slot);
                } else for (size_t c=0;c<slot.columns;++c) {
                    const size_t j=slot.first+c;
                    const auto *payload=checked_output(view.columns[c],dtype(j),slot.rows,8);
                    if (slot.rows) std::memcpy(columns[j].data()+slot.row*8,payload,slot.rows*8);
                }
            }
            facts.push_back(observation(ctx));
        }
        if (encode) save(argv[2],frame);
        else {
            for (size_t c=0;c<layout.columns;++c) save(argv[at+c],columns[c]);
            save(argv[3],schema);
        }
        std::cout << "{\"rows\":" << layout.rows << ",\"columns\":" << layout.columns << ",\"streams\":[";
        for (size_t i=0;i<facts.size();++i) std::cout << (i ? "," : "") << facts[i];
        std::cout << "]}\n";
        return 0;
    } catch (const tsbench::PluginError &e) {
        std::cerr << "plugin status " << e.status() << ": " << e.what() << '\n';
        return 3;
    } catch (const std::exception &e) {
        std::cerr << e.what() << '\n';
        return 4;
    }
}

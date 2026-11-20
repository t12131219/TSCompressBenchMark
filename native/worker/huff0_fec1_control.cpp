// Process batches of complete, unmodified Huff0 ABI frames. A batch is a
// scheduling unit: individual native inputs and decoder contexts stay separate.
#include "plugin_loader.hpp"

#include <algorithm>
#include <cstring>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <vector>

namespace {
using Bytes = std::vector<uint8_t>;
constexpr size_t unit = 65536, header = 32, schema_max = 256, batch_max = 4 << 20;
constexpr size_t frame_max = header + schema_max + 24 + 2*13 + unit;
constexpr const char *id = "huff0-reference";
void check(bool ok, const char *reason) {
    if (!ok) throw std::runtime_error(reason);
}
Bytes read(const char *path, size_t limit) {
    std::ifstream f(path, std::ios::binary | std::ios::ate);
    const auto end = f.tellg();
    check(end > 0 && uint64_t(end) <= limit, "invalid input extent");
    Bytes data(static_cast<size_t>(end));
    f.seekg(0);
    check(bool(f.read(reinterpret_cast<char *>(data.data()), data.size())), "input read failed");
    return data;
}
uint64_t le(const uint8_t *p, unsigned n) {
    uint64_t value = 0;
    for (unsigned i=0; i<n; ++i) value |= uint64_t(p[i]) << (8*i);
    return value;
}
void write(std::ofstream &out, const uint8_t *p, size_t n) {
    check(bool(out.write(reinterpret_cast<const char *>(p), n)), "output write failed");
}
}

int main(int argc, char **argv) {
    try {
        const std::string_view op = argc>1 ? argv[1] : "";
        const bool encode = op == "encode";
        check((encode && argc==6) || (op=="decode" && argc==5), "expected encode LIB VALUES SCHEMA OUT or decode LIB STREAM OUT");
        const auto module = tsbench::PluginModule::from_linked(argv[2], id, &bmk_get_plugin);
        const auto input = read(argv[3], encode ? batch_max : batch_max/unit*frame_max);
        const auto schema = encode ? read(argv[4], schema_max) : Bytes{};
        std::ofstream output(argv[encode ? 5 : 4], std::ios::binary | std::ios::trunc);
        check(bool(output), "output open failed");
        size_t pos=0, count=0, raw=0, wire=0;
        while (pos<input.size()) {
            tsbench::Context ctx(module, "{}");
            auto *data=input.data()+pos;
            const auto remaining=input.size()-pos;
            if (encode) {
                const auto n=std::min(remaining,unit);
                bmk_array_view column{};
                column.struct_size=sizeof(column); column.dtype=BMK_U8; column.rank=1;
                column.storage=data; column.storage_bytes=n; column.shape[0]=n; column.strides_bytes[0]=1;
                bmk_object_view object{sizeof(object),1,&column,schema.data(),schema.size()};
                const auto frame=ctx.encode(object);
                const auto &blob=frame->get();
                check(blob.data && blob.size>=header && blob.size<=frame_max,"invalid ABI frame extent");
                write(output,blob.data,blob.size);
                pos+=n; raw+=n; wire+=blob.size;
            } else {
                check(remaining>=header && std::memcmp(data,"BMKHUF\1\0",8)==0 && le(data+8,4)==BMK_U8,
                      "invalid Huff0 sequence header");
                const auto n=le(data+12,8), s=le(data+20,4), p=le(data+24,8);
                check(n>0 && n<=unit && s>0 && s<=schema_max && p>=24 && p<=frame_max-header-s &&
                      header+s+p<=remaining && (header+s+p==remaining || n==unit) && n<=batch_max-raw,
                      "invalid Huff0 sequence extent");
                const auto frame_n=header+s+p;
                const auto object=ctx.decode(data,frame_n);
                const auto &view=object->get();
                check(view.column_count==1 && view.columns && view.schema_json && view.schema_bytes==s &&
                      std::memcmp(view.schema_json,data+header,s)==0,"invalid restored schema");
                const auto &col=view.columns[0];
                check(col.struct_size>=sizeof(col) && col.dtype==BMK_U8 && col.rank==1 && !col.flags &&
                      !col.validity && !col.validity_bytes && !col.validity_bit_offset && col.shape[0]==n &&
                      col.strides_bytes[0]==1 && col.storage && col.origin_offset<=col.storage_bytes &&
                      n<=col.storage_bytes-col.origin_offset && col.origin_offset<=SIZE_MAX-n,"invalid restored bytes");
                write(output,static_cast<const uint8_t *>(col.storage)+col.origin_offset,n);
                pos+=frame_n; raw+=n; wire+=frame_n;
            }
            ++count;
        }
        output.close();
        check(bool(output), "output close failed");
        std::cout << "{\"frames\":" << count << ",\"input_bytes\":" << raw << ",\"frame_bytes\":" << wire << "}\n";
        return 0;
    } catch (const std::exception &exc) {
        std::cerr << exc.what() << '\n';
        return 1;
    }
}

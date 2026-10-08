// Test the shipped C ABI with independent wire helpers, never codec definitions.
#define main preserved_functional_smoke_main
#include "native_smoke.cpp"
#undef main
#include <sys/mman.h>
#include <unistd.h>
#include <functional>

namespace {
uint64_t malformed_cases = 0, descriptor_cases = 0, guard_cases = 0;
void put_le(unsigned char *p, uint64_t value, unsigned bytes) {
    for (unsigned i = 0; i < bytes; ++i) p[i] = static_cast<unsigned char>(value >> (i * 8));
}
void seal(std::vector<unsigned char>& frame) {
    check(frame.size() >= 40, "invalid test frame geometry");
    uint64_t hash = UINT64_C(14695981039346656037);
    for (size_t i = 0; i < frame.size() - 8; ++i)
        hash = (hash ^ frame[i]) * UINT64_C(1099511628211);
    put_le(frame.data() + frame.size() - 8, hash, 8);
}
std::vector<unsigned char> frame_for(const std::vector<uint32_t>& values, bool marked) {
    const auto words = oracle(values);
    std::vector<unsigned char> frame(40 + words.size() * 8 + (marked ? 4 : 0), 0);
    std::memcpy(frame.data(), "TSCB8BR1", 8);
    put_le(frame.data() + 8, values.size(), 4);
    put_le(frame.data() + 16, marked, 4);
    put_le(frame.data() + 20, words.size() * 2 + (marked ? 1 : 0), 4);
    if (marked) put_le(frame.data() + 32, values.size(), 4);
    for (size_t i = 0; i < words.size(); ++i)
        put_le(frame.data() + 32 + (marked ? 4 : 0) + i * 8, words[i], 8);
    seal(frame);
    return frame;
}
void reject(tscb_codec_handle_v1 *h, std::vector<unsigned char> frame,
            tscb_status_v1 expected = TSCB_STATUS_CODEC_ERROR_V1) {
    ok(tscb_reset(h, 0));
    std::vector<unsigned char> destination(4096 * 4, 0xa5);
    auto input = descriptor(frame.data(), frame.size(), frame.size(), false);
    auto output = descriptor(destination.data(), destination.size(), 0, true);
    const auto saved_frame = frame, saved_destination = destination;
    const auto saved_input = input, saved_output = output;
    check(tscb_decompress(h, &input, &output) == expected, "malformed status differs");
    check(frame == saved_frame && destination == saved_destination &&
          std::memcmp(&input, &saved_input, sizeof(input)) == 0 &&
          std::memcmp(&output, &saved_output, sizeof(output)) == 0,
          "malformed rejection is not atomic");
    const auto time = timing(h);
    check(time.native_encode_wall_ns == 0 && time.native_decode_wall_ns == 0,
          "rejected grammar invoked native source");
    // Every rejected frame must leave the decoder usable without reset.
    const auto valid = frame_for({1, UINT32_MAX}, true);
    input = descriptor(const_cast<unsigned char*>(valid.data()), valid.size(), valid.size(), false);
    output = descriptor(destination.data(), 8, 0, true);
    ok(tscb_decompress(h, &input, &output));
    check(little(destination.data(), 4) == 1 && little(destination.data() + 4, 4) == UINT32_MAX,
          "malformed failure damaged decoder");
    ++malformed_cases;
}
void malformed() {
    for (bool marked : {false, true}) {
        auto *h = create(!marked);
        for (unsigned width : {0,1,5,12,20,30,32})
            for (size_t n : {0,1,2,7,8,9,59,60,61,127,128,129,255,256,257}) {
                const auto valid = frame_for(pattern(n, width, unsigned(n % 6)), marked);
                for (size_t cut = 0; cut < valid.size(); ++cut)
                    reject(h, {valid.begin(), valid.begin() + cut});
                for (size_t at : {0,8,12,16,20,24,28}) {
                    auto bad = valid; bad[at] ^= 0x80;
                    if (at == 8) put_le(bad.data() + 8, 16777217, 4);
                    seal(bad); reject(h, bad);
                }
                auto bad = valid; bad.back() ^= 1; reject(h, bad);
                bad = valid; bad.push_back(0); reject(h, bad);
                if (marked) {
                    bad = valid; bad[32] ^= 1; seal(bad); reject(h, bad);
                }
                if (n) {
                    // An extra complete source word with consistent frame geometry.
                    bad = valid; bad.insert(bad.end() - 8, 8, 0);
                    put_le(bad.data() + 20, little(valid.data() + 20, 4) + 2, 4);
                    seal(bad); reject(h, bad);
                    // Remove half a source word, then repair geometry and checksum.
                    bad = valid; bad.erase(bad.end() - 12, bad.end() - 8);
                    put_le(bad.data() + 20, little(valid.data() + 20, 4) - 1, 4);
                    seal(bad); reject(h, bad);
                }
            }
        for (uint64_t word : {UINT64_C(0), UINT64_C(0xf000000000000001),
                              UINT64_C(0xf000000200000001), UINT64_C(0xf000000100000001),
                              UINT64_C(0xe000000100000001)}) {
            auto bad = frame_for({1}, marked);
            if (word == UINT64_C(0xf000000100000001)) {
                // Missing source payload, although the header still promises one value.
                bad.erase(bad.begin() + 32 + (marked ? 4 : 0), bad.end() - 8);
                put_le(bad.data() + 20, marked ? 1 : 0, 4);
            } else put_le(bad.data() + 32 + (marked ? 4 : 0), word, 8);
            seal(bad); reject(h, bad);
        }
        // Each fixed-width selector: valid value plus a nonzero unused tail bit.
        for (unsigned selector = 1; selector <= 14; ++selector) {
            auto bad = frame_for({1}, marked);
            const unsigned used_width = std::min(widths[selector], 32U);
            put_le(bad.data() + 32 + (marked ? 4 : 0),
                   (uint64_t(selector) << 60) | 1 | (uint64_t(1) << used_width), 8);
            seal(bad); reject(h, bad);
        }
        ok(tscb_destroy(h));
    }
}

struct Pages {
    size_t page, accessible, size;
    unsigned char *base, *data;
    Pages(size_t n, bool at_end, unsigned char fill) : size(n) {
        page = static_cast<size_t>(sysconf(_SC_PAGESIZE));
        accessible = std::max(page, ((n + page - 1) / page) * page);
        base = static_cast<unsigned char*>(mmap(nullptr, accessible + 2 * page,
                PROT_NONE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0));
        check(base != MAP_FAILED, "mmap failed");
        check(mprotect(base + page, accessible, PROT_READ | PROT_WRITE) == 0, "mprotect failed");
        std::memset(base + page, fill, accessible);
        data = base + page + (at_end ? accessible - n : 0);
    }
    void readonly() { check(mprotect(base + page, accessible, PROT_READ) == 0, "readonly failed"); }
    void outside_unchanged(unsigned char fill) {
        for (size_t i = 0; i < accessible; ++i) {
            const auto *p = base + page + i;
            if (p < data || p >= data + size) check(*p == fill, "guard canary changed");
        }
    }
    ~Pages() { munmap(base, accessible + 2 * page); }
    Pages(const Pages&) = delete;
    Pages& operator=(const Pages&) = delete;
};
void guard_matrix() {
    for (unsigned width = 0; width <= 32; ++width)
        for (size_t n : {0,1,2,7,8,9,59,60,61,127,128,129,255,256,257,4095,4096,4097})
            for (bool marked : {false,true}) for (bool at_end : {false,true}) {
                const auto values = pattern(n, width, unsigned(n % 6));
                const auto wire = frame_for(values, marked);
                auto *h = create(marked), *d = create(!marked);
                Pages source(n * 4, at_end, 0x5a), encoded(wire.size(), at_end, 0xa5);
                if (n) std::memcpy(source.data, values.data(), n * 4);
                source.readonly();
                auto input = descriptor(source.data, n * 4, n * 4, true);
                auto output = descriptor(encoded.data, wire.size() - 1, 0, false);
                const auto saved = output;
                check(tscb_compress(h, &input, &output) == TSCB_STATUS_DST_TOO_SMALL_V1 &&
                      std::memcmp(&output, &saved, sizeof(output)) == 0,
                      "guard encode capacity failure differs");
                for (size_t i = 0; i < encoded.accessible; ++i)
                    check(encoded.base[encoded.page + i] == 0xa5, "short guard encode changed bytes");
                output = descriptor(encoded.data, wire.size(), 0, false);
                ok(tscb_compress(h, &input, &output));
                check(std::memcmp(encoded.data, wire.data(), wire.size()) == 0, "guard wire differs");
                source.outside_unchanged(0x5a); encoded.outside_unchanged(0xa5);
                encoded.readonly();
                input = descriptor(encoded.data, wire.size(), wire.size(), false);
                Pages decoded(n * 4, at_end, 0xcc);
                output = descriptor(decoded.data, n * 4, 0, true);
                if (n) {
                    output = descriptor(decoded.data, (n - 1) * 4, 0, true);
                    const auto before = output;
                    check(tscb_decompress(d, &input, &output) == TSCB_STATUS_DST_TOO_SMALL_V1 &&
                          std::memcmp(&output, &before, sizeof(output)) == 0,
                          "guard decode capacity failure differs");
                    for (size_t i = 0; i < decoded.accessible; ++i)
                        check(decoded.base[decoded.page + i] == 0xcc, "short guard decode changed bytes");
                    check(timing(d).native_decode_wall_ns == 0, "short decode invoked native API");
                    output = descriptor(decoded.data, n * 4, 0, true);
                }
                ok(tscb_decompress(d, &input, &output));
                check(!n || std::memcmp(decoded.data, values.data(), n * 4) == 0, "guard inverse differs");
                decoded.outside_unchanged(0xcc);
                check(!n || std::memcmp(source.data, values.data(), n * 4) == 0, "readonly input differs");
                ok(tscb_destroy(h)); ok(tscb_destroy(d)); ++guard_cases;
            }
}

void descriptor_matrix() {
    using Mutation = std::function<void(tscb_buffer_v1&)>;
    const std::vector<Mutation> invalid = {
        [](auto& b){b.rank=0;}, [](auto& b){b.rank=2;}, [](auto& b){b.dtype=TSCB_DTYPE_F32_LE_V1;},
        [](auto& b){b.reserved=1;}, [](auto& b){b.ownership=3;}, [](auto& b){b.used_bytes=b.capacity_bytes+1;},
        [](auto& b){b.alignment_bytes=0;}, [](auto& b){b.alignment_bytes=3;},
        [](auto& b){b.shape[1]=1;}, [](auto& b){b.strides_bytes[1]=1;},
        [](auto& b){b.shape[0]+=1;}, [](auto& b){b.strides_bytes[0]+=1;},
        [](auto& b){b.data=nullptr;},
        [](auto& b){b.data=reinterpret_cast<void*>(UINTPTR_MAX-1);},
    };
    for (bool marked : {false,true}) {
        auto *h = create(marked);
        uint32_t value = 1;
        auto frame = frame_for({value}, marked);
        for (bool encode : {false,true}) for (bool change_input : {false,true})
            for (const auto& mutate : invalid) {
                ok(tscb_reset(h,0));
                std::vector<unsigned char> sink(128,0xa5);
                auto in = encode ? descriptor(&value,4,4,true)
                                 : descriptor(frame.data(),frame.size(),frame.size(),false);
                auto out = descriptor(sink.data(),encode?128:4,0,!encode);
                mutate(change_input?in:out);
                const auto before_in=in, before_out=out;
                const auto before_frame=frame;
                check((encode?tscb_compress(h,&in,&out):tscb_decompress(h,&in,&out)) ==
                      TSCB_STATUS_INVALID_ARGUMENT_V1, "invalid descriptor accepted");
                check(std::memcmp(&in,&before_in,sizeof(in))==0 &&
                      std::memcmp(&out,&before_out,sizeof(out))==0 && frame==before_frame && value==1 &&
                      std::all_of(sink.begin(),sink.end(),[](auto x){return x==0xa5;}),
                      "descriptor rejection not atomic");
                const auto time=timing(h);
                check(time.native_encode_wall_ns==0 && time.native_decode_wall_ns==0,
                      "invalid descriptor invoked source");
                ++descriptor_cases;
            }
        // Alias data with input, output, descriptors and the live opaque handle.
        for (bool encode : {false,true}) for (unsigned kind=0;kind<7;++kind) {
            ok(tscb_reset(h,0));
            alignas(16) unsigned char storage[256]{};
            std::memcpy(storage,frame.data(),frame.size());
            auto in=encode?descriptor(storage,4,4,true):descriptor(storage,frame.size(),frame.size(),false);
            auto out=descriptor(storage+128,encode?64:4,0,!encode);
            switch(kind) {
            case 0: out.data=in.data;break;
            case 1: out.data=&in;break;
            case 2: out.data=&out;break;
            case 3: out.data=h;break;
            case 4: in.data=&in;break;
            case 5: in.data=&out;break;
            default: in.data=h;break;
            }
            const auto before_in=in,before_out=out;
            unsigned char before[256];std::memcpy(before,storage,sizeof(storage));
            check((encode?tscb_compress(h,&in,&out):tscb_decompress(h,&in,&out))==
                  TSCB_STATUS_INVALID_ARGUMENT_V1,"alias accepted");
            check(std::memcmp(&in,&before_in,sizeof(in))==0 &&
                  std::memcmp(&out,&before_out,sizeof(out))==0 &&
                  std::memcmp(storage,before,sizeof(storage))==0,"alias rejection not atomic");
            check(timing(h).native_encode_wall_ns==0 && timing(h).native_decode_wall_ns==0,
                  "alias invoked source");++descriptor_cases;
        }
        uint64_t bound=991;
        auto large=descriptor(&value,UINT64_C(16777216)*4,UINT64_C(16777216)*4,true);
        ok(tscb_compress_bound(h,&large,&bound));
        check(bound==40+UINT64_C(16777216)*8+(marked?4:0),"maximum count bound differs");
        large=descriptor(&value,UINT64_C(16777217)*4,UINT64_C(16777217)*4,true);
        bound=991;
        check(tscb_compress_bound(h,&large,&bound)==TSCB_STATUS_UNSUPPORTED_V1 && bound==991,
              "resource bound changed on failure");
        unsigned char sink[64];std::memset(sink,0xa5,sizeof(sink));
        auto output=descriptor(sink,sizeof(sink),0,false);const auto before=output;
        check(tscb_compress(h,&large,&output)==TSCB_STATUS_UNSUPPORTED_V1 &&
              std::memcmp(&output,&before,sizeof(output))==0,"resource limit accepted");
        check(tscb_reset(h,1)==TSCB_STATUS_INVALID_ARGUMENT_V1,"unsupported reset mode accepted");
        ok(tscb_reset(h,0));
        auto final=descriptor(nullptr,0,0,false);
        check(tscb_finalize(h,&final)==TSCB_STATUS_FINALIZE_REQUIRED_V1,"empty lifecycle finalized");
        const char *json=nullptr;uint64_t size=0;
        check(tscb_get_accounting_json(h,&json,&size)==TSCB_STATUS_FINALIZE_REQUIRED_V1,
              "unfinalized accounting accepted");
        auto input=descriptor(&value,4,4,true);
        ok(tscb_compress(h,&input,&output));
        output.used_bytes=0;
        check(tscb_compress(h,&input,&output)==TSCB_STATUS_CODEC_ERROR_V1,"duplicate update accepted");
        ok(tscb_finalize(h,&final));
        check(tscb_compress(h,&input,&output)==TSCB_STATUS_CODEC_ERROR_V1,"finalized update accepted");
        ok(tscb_reset(h,0));ok(tscb_compress(h,&input,&output));
        ok(tscb_destroy(h));descriptor_cases+=9;
    }
}
} // namespace

int main() {
    try {
        uint64_t matrix_cases=0;
        std::vector<size_t> lengths;
        for(size_t n=0;n<=64;++n)lengths.push_back(n);
        for(size_t n:{65,66,67,119,120,121,127,128,129,179,180,181,239,240,241,
                      255,256,257,511,512,513,4095,4096,4097})lengths.push_back(n);
        for(unsigned width=0;width<=32;++width)for(size_t n:lengths)
            for(unsigned kind=0;kind<6;++kind)for(bool marked:{false,true}) {
                // Cycle offsets per pair; this is not a Cartesian offset expansion.
                one(pattern(n,width,kind),marked,unsigned((matrix_cases/2)%4));++matrix_cases;
            }
        malformed();descriptor_matrix();guard_matrix();
        check(matrix_cases==35244 && guard_cases==2376 && descriptor_cases==158,
              "native safety matrix cardinality differs");
        for(unsigned selector=1;selector<=15;++selector)
            check(seen[selector]!=0,"legal selector was not exercised");
        std::printf("{\"status\":\"PASS\",\"matrix_cases\":%llu,\"malformed_cases\":%llu,"
                    "\"descriptor_alias_lifecycle_checks\":%llu,\"guard_cases\":%llu,"
                    "\"cycled_input_offsets\":4,\"all_legal_selectors\":true,"
                    "\"readonly_exact_guard_pages\":true,\"atomic_recoverable_failures\":true}\n",
                    static_cast<unsigned long long>(matrix_cases),
                    static_cast<unsigned long long>(malformed_cases),
                    static_cast<unsigned long long>(descriptor_cases),
                    static_cast<unsigned long long>(guard_cases));
    } catch(const std::exception& error) {
        std::fprintf(stderr,"NATIVE_SAFETY_FAIL: %s\n",error.what());return 2;
    }
}

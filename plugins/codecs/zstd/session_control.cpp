// Bounded functional probe of the frozen native session API, never a timed sample.
#include "lzbench_extended.hpp"

#include <algorithm>
#include <array>
#include <fstream>
#include <iostream>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>

using namespace lzbench_native;
namespace {
void check(bool ok, const char *message) {
    if (!ok) throw std::logic_error(message);
}

template <class Fn> std::string reject(Fn action, const std::string &expected) {
    try { action(); }
    catch (const std::runtime_error &err) {
        check(std::string(err.what()) == expected, err.what());
        return err.what();
    }
    throw std::logic_error("expected rejection: " + expected);
}

configuration config(const std::string &codec) {
    configuration c;
    check(codec == "xz" || codec == "zstd", "unknown codec");
    if (codec == "xz") {
        c.codec = LN_XZ;
        c.level = 1;
        c.parameters = {{"block_size",32768},{"check",4},{"filter0",3},{"filter0_distance",4},
                        {"memory_limit",64 << 20},{"threads",1}};
    } else {
        c.codec = LN_ZSTD;
        c.level = -1;
        c.parameters = {{"workers",0},{"checksum",1}};
    }
    return c;
}

constexpr size_t original_size[] = {136013,7919};
constexpr size_t slack = 65536;
bytes read(const std::string &path, size_t ceiling) {
    std::ifstream in(path,std::ios::binary | std::ios::ate);
    const auto size = in.tellg();
    check(in && size > 0 && size <= static_cast<std::streamoff>(ceiling),"session input extent");
    bytes data(static_cast<size_t>(size));
    in.seekg(0);
    in.read(reinterpret_cast<char *>(data.data()),size);
    check(bool(in),"session input read failed");
    return data;
}
void save(const char *name, const bytes &data) {
    std::ofstream out(name,std::ios::binary);
    out.write(reinterpret_cast<const char *>(data.data()),data.size());
    out.close();
    check(bool(out),"session output write failed");
}

struct transfer {
    bytes data;
    std::vector<std::array<size_t,5>> calls;
};
transfer process(session &s, bool encode, const bytes &input, size_t quota, size_t in_cap, size_t out_cap) {
    transfer r;
    bytes out(out_cap);
    size_t offset = 0, end = std::min(in_cap,input.size()), idle = 0;
    while (true) {
        const bool finish = end == input.size();
        const auto step = s.process(encode,input.data()+offset,end-offset,out.data(),out.size(),finish);
        check(r.calls.size() < 4096,"session call limit");
        check(step.consumed <= end-offset && step.produced <= out.size() && step.produced <= quota-r.data.size(),
              "session span bounds or output quota");
        r.calls.push_back({end-offset,step.consumed,step.produced,finish,step.finished});
        offset += step.consumed;
        r.data.insert(r.data.end(),out.begin(),out.begin()+step.produced);
        if (step.finished) {
            check(offset == input.size(),"unconsumed input after finish");
            return r;
        }
        idle = step.consumed || step.produced ? 0 : idle+1;
        check(idle < 10000,"session stalled");
        if (offset == end) end += std::min(in_cap,input.size()-end);
    }
}
void calls(const transfer &r) {
    std::cout << '[';
    bool comma = false;
    for (const auto &c : r.calls) {
        if (comma) std::cout << ',';
        comma = true;
        std::cout << '[' << c[0] << ',' << c[1] << ',' << c[2] << ',' << c[3] << ',' << c[4] << ']';
    }
    std::cout << ']';
}

void exercise(const configuration &c) {
    const auto first = read("/inputs/first",original_size[0]);
    const auto second = read("/inputs/second",original_size[1]);
    check(first.size() == original_size[0] && second.size() == original_size[1],"session workload size");
    std::map<std::string,std::string> guards;
    auto invalid = c;
    invalid.parameters["tsbench_invalid"] = 1;
    guards["unknown"] = reject([&] { session ignored(invalid); },"unsupported parameter: tsbench_invalid");
    if (c.codec == LN_XZ) {
        invalid = c;
        invalid.dictionary = {1};
        guards["dictionary"] = reject([&] { session ignored(invalid); },"backend has no external dictionary in selected format");
        invalid = c;
        invalid.parameters["filter0"] = 127;
        guards["filter"] = reject([&] { session ignored(invalid); },"XZ BCJ filter id");
        invalid = c;
        invalid.parameters["memory_limit"] = 1;
        guards["encode-budget"] = reject([&] { session ignored(invalid); },"XZ encoder memory/configuration limit");
        session limited(c);
        const auto wire = read("/inputs/budget",255);
        guards["decode-budget"] = reject([&] { process(limited,false,wire,1,17,7); },"XZ code: 6");
    } else {
        invalid = c;
        invalid.parameters["pledged_size"] = -2;
        session pledged(invalid);
        guards["pledged-size"] = reject([&] { pledged.reset(true); },"pledged size");
    }
    session s(c);
    check(s.streaming(),"not a native byte session");
    unsigned char b = 0;
    const std::string bad_span = "stream spans/capacity/overlap";
    guards["overlap"] = reject([&] { s.process(true,&b,1,&b,1,false); },bad_span);
    guards["zero-capacity"] = reject([&] { s.process(true,nullptr,0,&b,0,false); },bad_span);
    guards["batch-encode"] = reject([&] { s.compress_block(&b,1); },"use process for native stream/frame");
    guards["batch-decode"] = reject([&] { s.decompress_block(&b,1,1); },"use process for stream/frame");
    s.reset(true);
    const auto a = process(s,true,first,first.size()+slack,4093,7);
    guards["after-finish"] = reject([&] { s.process(true,nullptr,0,&b,1,true); },"reset required after stream end");
    s.reset(true);
    const auto d = process(s,true,second,second.size()+slack,947,11);
    session fresh(c);
    const auto fresh_second = process(fresh,false,d.data,second.size(),17,113);
    const auto decoded = process(s,false,a.data,first.size(),19,127);
    s.reset(false);
    const auto reset = process(s,false,d.data,second.size(),13,251);
    s.reset(false);
    auto truncated = d.data;
    truncated.pop_back();
    guards["truncated"] = reject([&] { process(s,false,truncated,second.size(),17,71); },"truncated stream");
    guards["after-failure"] = reject([&] { s.process(false,nullptr,0,&b,1,true); },"reset required after failure");
    s.reset(false);
    const auto recovered = process(s,false,d.data,second.size(),17,71);
    check(decoded.data == first && fresh_second.data == second && reset.data == second && recovered.data == second,
          "native session byte roundtrip differs");
    save("first",a.data);
    save("second",d.data);
    std::cout << "{\"level\":" << c.level << ",\"parameters\":{";
    bool comma = false;
    for (const auto &[key,value] : c.parameters) {
        if (comma) std::cout << ',';
        comma = true;
        std::cout << '"' << key << "\":" << value;
    }
    std::cout << "},\"guards\":{";
    comma = false;
    for (const auto &[key,message] : guards) {
        if (comma) std::cout << ',';
        comma = true;
        // reject() only returns an exact, hard-coded message without JSON metacharacters.
        std::cout << '"' << key << "\":\"" << message << '"';
    }
    std::cout << "},\"calls\":{";
    comma = false;
    for (const auto &item : {std::make_pair("encode-first",&a),std::make_pair("encode-second-after-reset",&d),
          std::make_pair("decode-second-fresh",&fresh_second),std::make_pair("decode-first",&decoded),
          std::make_pair("decode-second-after-reset",&reset),std::make_pair("decode-second-after-failure-and-reset",&recovered)}) {
        if (comma) std::cout << ',';
        comma = true;
        std::cout << '"' << item.first << "\":";
        calls(*item.second);
    }
    std::cout << "}}\n";
}
} // namespace

int main(int argc, char **argv) {
    try {
        check(argc >= 3,"expected exercise|restore zstd|xz [first|second]");
        const auto c = config(argv[2]);
        const std::string op = argv[1];
        if (op == "exercise" && argc == 3) exercise(c);
        else if (op == "restore" && argc == 4) {
            const std::string part = argv[3];
            check(part == "first" || part == "second","unknown session part");
            const size_t n = original_size[part == "second"];
            const auto frame = read("/inputs/frame",n+slack);
            session s(c);
            const auto r = process(s,false,frame,n,17,127);
            check(r.data.size() == n,"independent session restore extent");
            save("raw",r.data);
            calls(r);
            std::cout << '\n';
        } else check(false,"unknown session operation");
        return 0;
    } catch (const std::exception &err) {
        std::cerr << err.what() << '\n';
        return 2;
    }
}

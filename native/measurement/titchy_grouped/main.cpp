// A bounded file-direction process. Never carries codec state across units.
#include <charconv>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sched.h>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

int tsbench_titchy_stream_unit(int argc, char **argv);
int tsbench_titchy_access_unit(int argc, char **argv);

namespace {
using Entry = int (*)(int,char**);
void need(bool condition,const char *message) {
    if (!condition) throw std::runtime_error(message);
}
size_t bounded(std::string_view s,size_t max) {
    size_t n{};
    const auto end=s.data()+s.size();
    const auto r=std::from_chars(s.data(),end,n);
    need(r.ec==std::errc{} && r.ptr==end && n && n<=max,"invalid grouped Titchy extent");
    return n;
}
void unit(Entry entry,std::vector<std::string> args) {
    std::vector<char*> argv;
    argv.reserve(args.size()+1);
    for (auto &s:args) argv.push_back(s.data());
    argv.push_back(nullptr);
    need(entry(static_cast<int>(args.size()),argv.data())==0,"Titchy unit rejected; no measurements admitted");
}
std::string basename(size_t i) {
    std::ostringstream out;
    out<<'u'<<std::setfill('0')<<std::setw(4)<<i;
    return out.str();
}
}

int main(int argc,char **argv) {
    try {
        need(argc==4,"expected ROUTE encode|decode UNIT_COUNT");
        const std::string route=argv[1], op=argv[2];
        const bool stream=route=="packet-stream", encode=op=="encode";
        need((stream || route=="loaded-file-access" || route=="batch-range") && (encode || op=="decode"),
             "unbound grouped Titchy route or direction");
        const size_t count=bounded(argv[3],1024);
        std::vector<std::string> rows;
        if (!stream && !encode) {
            std::ifstream manifest("/inputs/rows");
            for (size_t i=0;i<count;++i) {
                std::string row;
                need(bool(std::getline(manifest,row)) && row.size()<=5,"missing Titchy access extent");
                (void)bounded(row,65536);
                rows.push_back(row);
            }
            need(manifest.peek()==EOF && !manifest.bad(),"unexpected Titchy access extent");
        }
        const int cpu_before=sched_getcpu();
        for (size_t i=0;i<count;++i) {
            const auto in="/inputs/"+basename(i), out="/out/"+basename(i);
            if (stream) {
                if (encode) unit(tsbench_titchy_stream_unit,{"stream","encode",in+".raw",out+".wire",out+".config"});
                else unit(tsbench_titchy_stream_unit,{"stream","decode",in+".wire",in+".config",out+".raw"});
            } else if (encode) {
                unit(tsbench_titchy_access_unit,{"access","encode",in+".raw",out+".wire"});
            } else {
                unit(tsbench_titchy_access_unit,{"access",route,in+".wire",rows[i],out+".raw"});
            }
        }
        std::cout<<"{\"units\":"<<count<<",\"cpu_endpoints\":["<<cpu_before<<','<<sched_getcpu()<<"]}\n";
        return std::cout.good()?0:2;
    } catch(const std::exception &error) {
        std::cerr<<"grouped Titchy: "<<error.what()<<'\n';
        return 1;
    }
}

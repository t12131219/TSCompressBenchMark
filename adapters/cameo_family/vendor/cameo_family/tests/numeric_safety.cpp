// SPDX-License-Identifier: Apache-2.0
#include "../src/internal.hpp"
#include <future>
#include <iostream>
namespace cameo_family { double reference_lstsq_error(const Values &, I, I); }
using namespace cameo_family;
void check(bool yes) { if (!yes) throw std::runtime_error("numeric safety/parity"); }
int main() {
    std::size_t checks = 0;
    for (std::size_t n : {3,4,7,8,15,16,17,31,32,33,63,64,65,127,128,129,255,256,257,512,1024,4097}) {
        Values y(n);
        for (std::size_t i=0;i<n;++i) y[i] = 1 + double(i)*.125;
        check(reference_lstsq_error(y,0,I(n)-1) < 1e-15 * double(n));
        for (std::size_t i=0;i<n;++i) y[i] += .1*std::sin(double(i)*.49);
        auto saved = y;
        double a=reference_lstsq_error(y,0,I(n)-1);
        check(a>=0 && std::isfinite(a) && y==saved);
        if (n<=257) {
            Config c; c.algorithm=Algorithm::SWAB; c.python_bottom_up=true; c.error_bound=.01;
            auto bytes=encode(y,c);
            auto stage=analyze(y,c); auto restored=decode(bytes.data(),bytes.size());
            check(stage.reconstructed==restored && y==saved);
        }
        ++checks;
    }
    // Simultaneous first/use and repeated calls exercise library initialization,
    // workspace ownership and its single-threaded USE_LOCKING configuration.
    std::vector<std::future<void>> jobs;
    for (int t=0;t<4;++t) jobs.push_back(std::async(std::launch::async,[t] {
        for (int r=0;r<20;++r) {
            Values y(65+std::size_t(t));
            for(std::size_t i=0;i<y.size();++i)y[i]=3+std::sin(double(i)*.49);
            Config c;c.algorithm=Algorithm::SWAB;c.python_bottom_up=true;c.error_bound=.1;
            auto expected=encode(y,c), actual=encode(y,c);
            check(expected==actual);
            check(decode(actual.data(),actual.size()).size()==y.size());
        }
    }));
    for(auto &job:jobs)job.get();
    std::cout<<"PASS numerical dependency: "<<checks<<" lengths, 80 concurrent Python-SWAB calls; "<<numeric_backend()<<'\n';
}

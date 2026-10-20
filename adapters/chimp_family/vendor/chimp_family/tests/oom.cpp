// SPDX-License-Identifier: LicenseRef-Local-Research
#include "chimp_family.hpp"
#include <new>
#include <cstdlib>
#include <iostream>
static long budget=-1;
void* operator new(std::size_t n){if(budget==0)throw std::bad_alloc();if(budget>0)--budget;void* p=std::malloc(n?n:1);if(!p)throw std::bad_alloc();return p;}
void* operator new[](std::size_t n){return ::operator new(n);}
void operator delete(void* p)noexcept{std::free(p);}void operator delete[](void* p)noexcept{std::free(p);}void operator delete(void* p,std::size_t)noexcept{std::free(p);}void operator delete[](void* p,std::size_t)noexcept{std::free(p);}
void check(bool b){if(!b)throw std::runtime_error("OOM transaction assertion");}
int main(){unsigned injected=0;for(unsigned m=1;m<=5;++m){chimp::Config c{chimp::Method(m),128,.1f};for(long fail=0;fail<8;++fail){chimp::ChimpEncoder e(c);e.add(42);auto expected=e;budget=fail;try{e.add(87);budget=-1;}catch(const std::bad_alloc&){budget=-1;++injected;check(e.finalize().bytes==expected.finalize().bytes);}}
 for(long fail=0;fail<8;++fail){chimp::ChimpEncoder e(c);e.add(42);auto expected=e;budget=fail;try{e.finalize();budget=-1;}catch(const std::bad_alloc&){budget=-1;++injected;e.add(87);expected.add(87);check(e.finalize().bytes==expected.finalize().bytes);}}}
 for(long fail=0;fail<8;++fail){chimp::Fpc f,expected;std::vector<std::uint64_t> in={42,87,11};budget=fail;try{f.encode(in);budget=-1;}catch(const std::bad_alloc&){budget=-1;++injected;check(f.encode(in)==expected.encode(in));}}
 check(injected>10);std::cout<<"PASS OOM injected failures="<<injected<<'\n';}

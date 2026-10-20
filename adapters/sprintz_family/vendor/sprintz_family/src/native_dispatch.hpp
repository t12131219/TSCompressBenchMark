#pragma once
#include <cstddef>
#include <cstdint>
int64_t port_native_encode(int,int,int,const void*,size_t,void*,int);
int64_t port_native_decode(int,int,int,const void*,void*);

#include "native_dispatch.hpp"
#include "native_bridge.hpp"
int64_t port_native_encode(int b,int f,int p,const void*in,size_t n,void*out,int d){return native_encode(b,f,p,in,n,out,d);}
int64_t port_native_decode(int b,int f,int p,const void*in,void*out){return native_decode(b,f,p,in,out);}

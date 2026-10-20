#pragma once
#include "sprintz.h"
#include "sprintz_delta.h"
#include "sprintz_xff.h"
#include <cstddef>
// Experimental legacy xff implementation only defines the 8-bit names below.
int64_t compress8b_rowmajor_xff(const uint8_t*,uint64_t,int8_t*,uint16_t,bool);
int64_t decompress8b_rowmajor_xff(const int8_t*,uint8_t*);
inline int64_t native_encode(int bits,int fire,int path,const void* in,size_t n,void* out,int d) {
using F8=int64_t(*)(const uint8_t*,uint32_t,int8_t*,uint16_t,bool);
 using F16=int64_t(*)(const uint16_t*,uint32_t,int16_t*,uint16_t,bool);
#define CALL8(D,X) return (fire ? static_cast<F8>(X) : static_cast<F8>(D))((const uint8_t*)in,n,(int8_t*)out,d,true)
#define CALL16(D,X) return (fire ? static_cast<F16>(X) : static_cast<F16>(D))((const uint16_t*)in,n,(int16_t*)out,d,true)
 if(bits==8){
  if(path==0){CALL8(sprintz_compress_delta_8b,sprintz_compress_xff_8b);}
  if(path==1){CALL8(compress_rowmajor_delta_rle_8b,compress_rowmajor_xff_rle_8b);}
  if(path==2){CALL8(compress_rowmajor_delta_rle_lowdim_8b,compress_rowmajor_xff_rle_lowdim_8b);}
  if(path==3)return compress_rowmajor_8b((const uint8_t*)in,n,(int8_t*)out,d,true);
  if(path==4)return compress_rowmajor_delta_8b((const uint8_t*)in,n,(int8_t*)out,d,true);
  if(path==5)return compress8b_rowmajor_xff((const uint8_t*)in,n,(int8_t*)out,d,true);
 }else{
  if(path==0){CALL16(sprintz_compress_delta_16b,sprintz_compress_xff_16b);}
  if(path==1){CALL16(compress_rowmajor_delta_rle_16b,compress_rowmajor_xff_rle_16b);}
  if(path==2){CALL16(compress_rowmajor_delta_rle_lowdim_16b,compress_rowmajor_xff_rle_lowdim_16b);}
  if(path==3)return compress_rowmajor_16b((const uint16_t*)in,n,(int16_t*)out,d,true);
  if(path==4)return compress_rowmajor_delta_16b((const uint16_t*)in,n,(int16_t*)out,d,true);
 }
 return -1;
#undef CALL8
#undef CALL16
}
inline int64_t native_decode(int bits,int fire,int path,const void* in,void* out){
using F8=int64_t(*)(const int8_t*,uint8_t*);
 using F16=int64_t(*)(const int16_t*,uint16_t*);
#define CALL8(D,X) return (fire ? static_cast<F8>(X) : static_cast<F8>(D))((const int8_t*)in,(uint8_t*)out)
#define CALL16(D,X) return (fire ? static_cast<F16>(X) : static_cast<F16>(D))((const int16_t*)in,(uint16_t*)out)
 if(bits==8){
  if(path==0){CALL8(sprintz_decompress_delta_8b,sprintz_decompress_xff_8b);}
  if(path==1){CALL8(decompress_rowmajor_delta_rle_8b,decompress_rowmajor_xff_rle_8b);}
  if(path==2){CALL8(decompress_rowmajor_delta_rle_lowdim_8b,decompress_rowmajor_xff_rle_lowdim_8b);}
  if(path==3)return decompress_rowmajor_8b((const int8_t*)in,(uint8_t*)out);
  if(path==4)return decompress_rowmajor_delta_8b((const int8_t*)in,(uint8_t*)out);
  if(path==5)return decompress8b_rowmajor_xff((const int8_t*)in,(uint8_t*)out);
 }else{
  if(path==0){CALL16(sprintz_decompress_delta_16b,sprintz_decompress_xff_16b);}
  if(path==1){CALL16(decompress_rowmajor_delta_rle_16b,decompress_rowmajor_xff_rle_16b);}
  if(path==2){CALL16(decompress_rowmajor_delta_rle_lowdim_16b,decompress_rowmajor_xff_rle_lowdim_16b);}
  if(path==3)return decompress_rowmajor_16b((const int16_t*)in,(uint16_t*)out);
  if(path==4)return decompress_rowmajor_delta_16b((const int16_t*)in,(uint16_t*)out);
 }
 return -1;
#undef CALL8
#undef CALL16
}

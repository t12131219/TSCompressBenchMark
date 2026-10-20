from pathlib import Path
import re,difflib,shutil,json,hashlib
p=Path(__file__).resolve().parents[1];s=p.parent.parent/'Source/sprintz-family/upstream/core'
changes=[]
for src in sorted(s.iterdir()):
 if src.suffix not in ['.cpp','.h','.hpp']:continue
 old=src.read_text();new=old
 # GNU/Clang one-byte-aligned may-alias scalar views for native packed loads.
 for typ in ['uint16_t','int16_t','uint32_t','int32_t','uint64_t','int64_t']:
  new=re.sub(r'\((const\s+)?'+typ+r'\s*\*\)',lambda m:'('+('const ' if m[1] else '')+'sz_'+typ+'*)',new)
 # checked tracked native allocation, exception-safe cleanup at ABI boundary.
 new=re.sub(r'\bcalloc\s*\(',r'sz_mem::alloc(',new)
 # append zero-init selector to calloc requires balanced-paren walk
 # perform this transform from old-compatible result: find each alloc closing bracket.
 start=0
 while True:
  at=new.find('sz_mem::alloc(',start)
  if at<0:break
  op=at+len('sz_mem::alloc');i=op+1;level=1
  while level:
   if new[i]=='(':level+=1
   elif new[i]==')':level-=1
   i+=1
  new=new[:i-1]+', true'+new[i-1:];start=i+6
 new=re.sub(r'\bmalloc\s*\(',r'sz_native_malloc(',new)
 new=re.sub(r'\bfree\s*\(',r'sz_mem::release(',new)
 if src.name in ['sprintz_delta_lowdim.cpp','sprintz_xff_lowdim.cpp']:
  new=new.replace('sz_mem::alloc(1, total_header_bytes, true)','sz_mem::alloc(1, nheader_stripes * 8, true)')
 new=new.replace('((x) << 1)', '((uint64_t)(x) << 1)')
 new=new.replace('(x << 1)', '((uint32_t)x << 1)')
 new=new.replace('>> (learning_shift + 4)) << 4', '>> (learning_shift + 4)) * 16')
 new=new.replace(') << shft', ') * (1 << shft)')
 new=new.replace(') << quantize_shft', ') * (1 << quantize_shft)')
 if src.name!='sprintz_xff.cpp':new=new.replace('sz_mem::alloc(1, group_header_sz, true)', 'sz_mem::alloc(1, group_header_sz * elem_sz, true)')
 new=re.sub(r'\(\(\((?:counter_t|int32_t)\)(prev_delta\d?)\) \* (coef\d?)\)',r'sz_mul_wrap32(\1, \2)',new)
 new=new.replace('needed_nbits_i8x8(const int8_t* x) {\n    __m128i v = _mm_loadu_si128((__m128i*)x);', 'needed_nbits_i8x8(const int8_t* x) {\n    __m128i v = _mm_loadl_epi64((const __m128i*)x);')
 if src.name=='univariate_8b.cpp':new=re.sub(r'\((deltas\d?|errs) << shift\) >> \(64 - (nbits\d?)\)',r'sz_extract_signed(\1, shift, \2)',new)
 if new!=old:
  new='#include "native_compat.hpp"\n'+new
  changes.extend(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/'+src.name,tofile='b/'+src.name))
 (p/'vendor/core'/src.name).write_text(new)
(p/'patches/native-safety.patch').write_text(''.join(changes))

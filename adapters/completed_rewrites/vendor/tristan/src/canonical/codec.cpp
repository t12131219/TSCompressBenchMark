// SPDX-License-Identifier: NOASSERTION
#include "tristan.hpp"
#include "numerical_internal.hpp"
#include <algorithm>
#include <cfenv>
#include <cmath>
#include <cstring>
#include <limits>

namespace tristan {
namespace {
std::uint64_t add(std::uint64_t a,std::uint64_t b){if(b>UINT64_MAX-a)throw Error(Code::ResourceLimit,"Size addition overflow");return a+b;}
std::uint64_t mul(std::uint64_t a,std::uint64_t b){if(a&&b>UINT64_MAX/a)throw Error(Code::ResourceLimit,"Size product overflow");return a*b;}
void check(bool ok,Code c,const char* s){if(!ok)throw Error(c,s);}
void config(std::uint64_t rows,std::uint32_t channels,const Config& c,Code code){
    check(c.length>0&&c.length<=4096&&c.atoms>0&&c.atoms<=4096&&c.nonzeros>0&&c.nonzeros<=c.atoms&&static_cast<std::uint32_t>(c.solver)<=4&&std::isfinite(c.alpha)&&c.alpha>=0.,code,"Invalid configuration");
    check(rows>=c.length&&rows<=1048576&&channels>0&&channels<=256,code,"Invalid input shape");
}
void fp(){check(std::fegetround()==FE_TONEAREST,Code::Unsupported,"Requires nearest-even floating environment");volatile double v=std::numeric_limits<double>::min(),half=.5;
    check(v*half!=0.,Code::Unsupported,"Requires gradual underflow");}
void put(std::vector<std::uint8_t>& b,std::uint64_t x,std::size_t n){for(std::size_t i=0;i<n;++i)b.push_back(static_cast<std::uint8_t>(x>>(8*i)));}
void patch(std::vector<std::uint8_t>& b,std::size_t p,std::uint64_t x,std::size_t n){for(std::size_t i=0;i<n;++i)b[p+i]=static_cast<std::uint8_t>(x>>(8*i));}
void real(std::vector<std::uint8_t>& b,double x){std::uint64_t bits;static_assert(sizeof x==sizeof bits,"Binary64 required");std::memcpy(&bits,&x,8);put(b,bits,8);}
std::uint32_t crc(const std::uint8_t* data,std::size_t n){std::uint32_t value=UINT32_MAX;for(std::size_t i=0;i<n;++i){value^=(i>=88&&i<92)?0:data[i];for(int j=0;j<8;++j)value=(value>>1)^(0xedb88320U&(0U-(value&1U)));}return ~value;}
struct Reader {
    const std::uint8_t* data;std::size_t size,pos=0;
    std::uint64_t get(std::size_t n){check(n<=size-pos,Code::CorruptStream,"Truncated frame");std::uint64_t x=0;for(std::size_t i=0;i<n;++i)x|=static_cast<std::uint64_t>(data[pos++])<<(8*i);return x;}
    std::uint32_t u32(){return static_cast<std::uint32_t>(get(4));}
    double number(){auto x=get(8);double v;std::memcpy(&v,&x,8);check(std::isfinite(v),Code::CorruptStream,"Nonfinite frame number");return v;}
};
}
std::uint64_t Accounting::physical_bytes()const{return add(add(add(header_bytes,normalization_bytes),add(dictionary_bytes,count_bytes)),add(index_bytes,coefficient_bytes));}
std::uint64_t Accounting::final_bits()const{return mul(physical_bytes(),8);}
std::uint64_t workspace_bound(std::uint64_t rows,std::uint32_t channels,const Config& c){
    config(rows,channels,c,Code::InvalidArgument);
    std::uint64_t w=rows/c.length,a=c.atoms,l=c.length;
    // Conservative all-stage upper bound, including SVD and solver copies.
    auto samples=w*(channels>1?std::min<std::uint32_t>(channels-1,7):1),r=std::min(samples,l);
    auto svd=add(add(mul(4,mul(samples,l)),mul(samples,r)),add(mul(r,l),add(mul(8,mul(r,r)),mul(8,r))));
    return mul(8,add(svd,add(add(mul(4,mul(rows,channels)),mul(12,mul(a,a))),add(mul(8,mul(w*channels,a)),mul(32,mul(a,l))))));
}
std::uint64_t compress_bound(std::uint64_t rows,std::uint32_t channels,const Config& c,const Limits& limits){
    config(rows,channels,c,Code::InvalidArgument);check(mul(mul(rows,channels),8)<=limits.input_bytes,Code::ResourceLimit,"Input limit exceeded");
    check(workspace_bound(rows,channels,c)<=limits.workspace_bytes,Code::ResourceLimit,"Workspace limit exceeded");
    auto size=add(add(96,mul(16,channels)),add(mul(8,mul(c.atoms,c.length)),mul(mul(channels,rows/c.length),add(4,mul(12,c.atoms)))));
    check(size<=limits.output_bytes&&size<=std::numeric_limits<std::size_t>::max(),Code::ResourceLimit,"Frame bound exceeds output limit");return size;
}
std::vector<std::uint8_t> encode(const double* input,std::uint64_t rows,std::uint32_t channels,const Config& c,const Limits& limits,Trace* trace)try{
    const auto bound=compress_bound(rows,channels,c,limits);fp();check(input!=nullptr,Code::InvalidArgument,"Null input");
    check(reinterpret_cast<std::uintptr_t>(input)%alignof(double)==0,Code::InvalidArgument,"Unaligned double input");
    auto n=static_cast<std::size_t>(rows),d=static_cast<std::size_t>(channels),l=static_cast<std::size_t>(c.length),a=static_cast<std::size_t>(c.atoms),w=n/l;
    std::vector<double> means(d),scales(d),z(n*d),tricklets(d*w*l);
    std::vector<bool> constant(d,true);
    // NumPy axis0 reduction over row-major multi-channel arrays is sequential.
    for(std::size_t i=0;i<n;++i)for(std::size_t j=0;j<d;++j){double v=input[i*d+j];check(std::isfinite(v),Code::InvalidArgument,"Nonfinite input");means[j]+=v;constant[j]=constant[j]&&(v==input[j]);}
    for(bool value:constant){check(!value,Code::InvalidArgument,"Constant column");}
    if(d==1){means[0]=detail::numpy_sum(input,n);}
    for(auto& v:means)v/=static_cast<double>(n);
    for(std::size_t i=0;i<n;++i)for(std::size_t j=0;j<d;++j){double v=input[i*d+j]-means[j];scales[j]+=v*v;}
    if(d==1){std::vector<double> squares(n);for(std::size_t i=0;i<n;++i){double v=input[i]-means[0];squares[i]=v*v;}scales[0]=detail::numpy_sum(squares.data(),n);}
    for(auto& v:scales){v=std::sqrt(v/static_cast<double>(n));check(std::isfinite(v)&&v>0.,Code::InvalidArgument,"Invalid population standard deviation");}
    for(std::size_t i=0;i<n;++i)for(std::size_t j=0;j<d;++j){double v=(input[i*d+j]-means[j])/scales[j];check(std::isfinite(v),Code::InvalidArgument,"Nonfinite normalized input");z[i*d+j]=v;
        if(i<w*l)tricklets[j*w*l+i]=v;}
    auto first=d>1?std::size_t{1}:std::size_t{0},last=d>1?std::min(d,std::size_t{8}):std::size_t{1};
    std::vector<double> training(tricklets.begin()+static_cast<std::ptrdiff_t>(first*w*l),tricklets.begin()+static_cast<std::ptrdiff_t>(last*w*l));std::vector<double> costs;
    auto dict=train(training,(last-first)*w,c,&costs,trace?&trace->learning_snapshots:nullptr);std::vector<double> coefficients;
    coefficients.reserve(d*w*a);
    for(std::size_t channel=0;channel<d;++channel){
        std::vector<double> part(tricklets.begin()+static_cast<std::ptrdiff_t>(channel*w*l),tricklets.begin()+static_cast<std::ptrdiff_t>((channel+1)*w*l));
        auto codes=sparse(part,w,dict,c);coefficients.insert(coefficients.end(),codes.begin(),codes.end());
    }
    std::vector<std::uint8_t> frame;frame.reserve(static_cast<std::size_t>(bound));const char magic[]="TRISTAN1";
    for(std::size_t i=0;i<8;++i){frame.push_back(static_cast<std::uint8_t>(magic[i]));}
    put(frame,1,4);put(frame,96,4);put(frame,0,4);put(frame,static_cast<std::uint32_t>(c.solver),4);put(frame,rows,8);
    put(frame,channels,4);put(frame,c.length,4);put(frame,c.atoms,4);put(frame,c.nonzeros,4);put(frame,c.seed,4);put(frame,c.requested_n_iter,4);real(frame,c.alpha);
    put(frame,w,8);put(frame,0,8);put(frame,0,8);put(frame,0,4);put(frame,0,4);
    for(std::size_t j=0;j<d;++j){real(frame,means[j]);real(frame,scales[j]);}for(double v:dict)real(frame,v);
    for(std::size_t i=0;i<d*w;++i){auto count_pos=frame.size();put(frame,0,4);std::uint32_t count=0;
        for(std::size_t j=0;j<a;++j){double v=coefficients[i*a+j];check(std::isfinite(v),Code::NumericalFailure,"Nonfinite sparse coefficient");if(v!=0.){put(frame,j,4);real(frame,v);++count;}}patch(frame,count_pos,count,4);}
    patch(frame,72,frame.size()-96,8);patch(frame,88,crc(frame.data(),frame.size()),4);
    if(trace){trace->normalized=std::move(z);trace->means=std::move(means);trace->scales=std::move(scales);trace->dictionary=std::move(dict);trace->coefficients=std::move(coefficients);trace->costs=std::move(costs);trace->rows=rows;trace->windows=w;trace->channels=channels;}
    return frame;
}catch(const std::bad_alloc&){throw Error(Code::ResourceLimit,"Encoder allocation failed");}
std::size_t compress(const double* input,std::uint64_t rows,std::uint32_t channels,const Config& c,std::uint8_t* output,std::size_t capacity,const Limits& limits){
    auto bound=compress_bound(rows,channels,c,limits);check(capacity>=bound,Code::OutputTooSmall,"Destination smaller than full compress_bound");check(output!=nullptr,Code::InvalidArgument,"Null destination");
    auto input_address=reinterpret_cast<std::uintptr_t>(input),output_address=reinterpret_cast<std::uintptr_t>(output);
    auto input_bytes=mul(mul(rows,channels),8);
    check(input_address<=UINTPTR_MAX-input_bytes&&output_address<=UINTPTR_MAX-capacity,Code::InvalidArgument,"Buffer address range overflow");
    check(input_address+input_bytes<=output_address||output_address+capacity<=input_address,Code::InvalidArgument,"Overlapping input and output buffers");
    auto result=encode(input,rows,channels,c,limits);std::memcpy(output,result.data(),result.size());return result.size();
}
Decoded decode(const std::uint8_t* frame,std::size_t size,const Limits& limits)try{
    fp();check(frame!=nullptr&&size>=96,Code::CorruptStream,"Missing frame header");check(size<=limits.output_bytes,Code::ResourceLimit,"Frame limit exceeded");
    check(std::memcmp(frame,"TRISTAN1",8)==0,Code::CorruptStream,"Bad frame magic");Reader r{frame,size,8};
    check(r.u32()==1&&r.u32()==96&&r.u32()==0,Code::CorruptStream,"Unsupported version/header/flags");Decoded out;out.config.solver=static_cast<Solver>(r.u32());out.original_rows=r.get(8);out.channels=r.u32();out.config.length=r.u32();out.config.atoms=r.u32();out.config.nonzeros=r.u32();out.config.seed=r.u32();out.config.requested_n_iter=r.u32();out.config.alpha=r.number();out.windows=r.get(8);
    auto payload=r.get(8);check(r.get(8)==0,Code::CorruptStream,"Nonzero reserved bits");auto checksum=r.u32();check(r.u32()==0,Code::CorruptStream,"Nonzero reserved field");
    config(out.original_rows,out.channels,out.config,Code::CorruptStream);check(out.windows==out.original_rows/out.config.length&&payload==size-96,Code::CorruptStream,"Frame length/shape mismatch");
    auto d=static_cast<std::size_t>(out.channels),a=static_cast<std::size_t>(out.config.atoms),l=static_cast<std::size_t>(out.config.length),w=static_cast<std::size_t>(out.windows);
    auto elements=mul(mul(d,w),l);check(mul(elements,8)<=limits.output_bytes,Code::ResourceLimit,"Decoded output exceeds limit");
    auto min_payload=add(mul(16,d),add(mul(8,mul(a,l)),mul(4,mul(d,w))));check(payload>=min_payload,Code::CorruptStream,"Missing dictionary/row counts");
    check(add(mul(8,mul(a,l)),mul(8,elements))<=limits.workspace_bytes,Code::ResourceLimit,"Decoder workspace exceeds limit");check(crc(frame,size)==checksum,Code::CorruptStream,"CRC32 mismatch");
    out.means.resize(d);out.scales.resize(d);for(std::size_t j=0;j<d;++j){out.means[j]=r.number();out.scales[j]=r.number();check(out.scales[j]>0.,Code::CorruptStream,"Invalid scale");}
    std::vector<double> dict(a*l);for(auto& v:dict)v=r.number();out.values.resize(static_cast<std::size_t>(elements));std::uint64_t nonzero=0;
    for(std::size_t i=0;i<d*w;++i){auto count=r.u32();check(count<=a&&mul(count,12)<=r.size-r.pos,Code::CorruptStream,"Invalid sparse row count");std::uint32_t prev=0;
        for(std::uint32_t k=0;k<count;++k){auto id=r.u32();double coefficient=r.number();check(id<a&&(k==0||id>prev)&&coefficient!=0.,Code::CorruptStream,"Invalid atom index/coefficient");prev=id;
            for(std::size_t j=0;j<l;++j){auto& v=out.values[i*l+j];v+=dict[static_cast<std::size_t>(id)*l+j]*coefficient;check(std::isfinite(v),Code::CorruptStream,"Reconstruction overflow");}}nonzero=add(nonzero,count);}
    check(r.pos==size,Code::CorruptStream,"Trailing frame bytes");out.accounting.normalization_bytes=mul(16,d);out.accounting.dictionary_bytes=mul(8,mul(a,l));out.accounting.count_bytes=mul(4,mul(d,w));out.accounting.index_bytes=mul(4,nonzero);out.accounting.coefficient_bytes=mul(8,nonzero);
    check(out.accounting.physical_bytes()==size,Code::CorruptStream,"Accounting mismatch");return out;
}catch(const std::bad_alloc&){throw Error(Code::ResourceLimit,"Decoder allocation failed");}
} // namespace tristan

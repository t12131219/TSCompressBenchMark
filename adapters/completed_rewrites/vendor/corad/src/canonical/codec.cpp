// SPDX-License-Identifier: NOASSERTION
// CORAD source orchestration/protocol; pinned TRISTAN numerical implementation.
#include "corad.hpp"
#include "numerical_internal.hpp"
#include <algorithm>
#include <cmath>
#include <cfenv>
#include <cstring>
#include <limits>
extern "C" int corad_rank_descending(const double*,std::size_t,std::uint32_t*);
namespace corad {
namespace {
void check(bool v,Code c,const char* message){if(!v)throw Error(c,message);}
std::uint64_t add(std::uint64_t a,std::uint64_t b){check(b<=UINT64_MAX-a,Code::ResourceLimit,"Size sum overflow");return a+b;}
std::uint64_t mul(std::uint64_t a,std::uint64_t b){check(!a||b<=UINT64_MAX/a,Code::ResourceLimit,"Size product overflow");return a*b;}
void fp(){check(std::fegetround()==FE_TONEAREST,Code::Unsupported,"Nearest-even required");volatile double v=std::numeric_limits<double>::min(),half=.5;check(v*half!=0.,Code::Unsupported,"Gradual underflow required");}
void config(std::uint64_t rows,std::uint32_t d,const Config& c,Code code){
    check(c.length>0&&c.length<=4096&&c.atoms>0&&c.atoms<=4096&&c.nonzeros>0&&c.nonzeros<=c.atoms&&static_cast<std::uint32_t>(c.solver)<=4&&std::isfinite(c.alpha)&&c.alpha>=0.&&std::isfinite(c.threshold),code,"Invalid configuration");
    check(rows>=c.length&&rows<=1048576&&d>0&&d<=256,code,"Invalid input shape");
}
void put(std::vector<std::uint8_t>& b,std::uint64_t x,std::size_t n){for(std::size_t i=0;i<n;++i)b.push_back(static_cast<std::uint8_t>(x>>(8*i)));}
void patch(std::vector<std::uint8_t>& b,std::size_t off,std::uint64_t x,std::size_t n){for(std::size_t i=0;i<n;++i)b[off+i]=static_cast<std::uint8_t>(x>>(8*i));}
void real(std::vector<std::uint8_t>& b,double v){std::uint64_t bits;static_assert(sizeof(v)==8,"Binary64 required");std::memcpy(&bits,&v,8);put(b,bits,8);}
std::uint32_t crc(const std::uint8_t* p,std::size_t n){std::uint32_t c=UINT32_MAX;for(std::size_t i=0;i<n;++i){c^=i>=88&&i<92?0:p[i];for(int k=0;k<8;++k)c=(c>>1)^(0xedb88320U&(0U-(c&1U)));}return ~c;}
struct Reader {const std::uint8_t* p;std::size_t size,pos;
    std::uint64_t get(std::size_t n){check(n<=size-pos,Code::CorruptStream,"Truncated frame");std::uint64_t x=0;for(std::size_t i=0;i<n;++i)x|=static_cast<std::uint64_t>(p[pos++])<<(8*i);return x;}
    std::uint32_t u32(){return static_cast<std::uint32_t>(get(4));}
    double number(){auto x=get(8);double v;std::memcpy(&v,&x,8);check(std::isfinite(v),Code::CorruptStream,"Nonfinite frame value");return v;}
};
}
std::uint64_t Accounting::physical_bytes()const{return add(add(add(header_bytes,normalization_bytes),add(dictionary_bytes,tag_bytes)),add(add(index_bytes,coefficient_bytes),reference_bytes));}
std::uint64_t Accounting::final_bits()const{return mul(physical_bytes(),8);}
std::uint64_t workspace_bound(std::uint64_t rows,std::uint32_t channels,const Config& c){
    config(rows,channels,c,Code::InvalidArgument);std::uint64_t w=rows/c.length,d=channels,a=c.atoms,l=c.length,m=w*(channels>1?std::min(channels-1,7U):1U),r=std::min(m,l);
    auto svd=add(add(mul(4,mul(m,l)),mul(m,r)),add(mul(r,l),add(mul(8,mul(r,r)),mul(8,r))));
    auto numerical=add(add(mul(4,mul(rows,d)),mul(12,mul(a,a))),add(mul(8,mul(w*d,a)),mul(32,mul(a,l))));
    return mul(8,add(add(svd,numerical),add(mul(4,mul(w,mul(d,d))),mul(8,w*d))));
}
std::uint64_t compress_bound(std::uint64_t rows,std::uint32_t d,const Config& c,const Limits& limits){
    config(rows,d,c,Code::InvalidArgument);check(mul(mul(rows,d),8)<=limits.input_bytes,Code::ResourceLimit,"Input limit exceeded");check(workspace_bound(rows,d,c)<=limits.workspace_bytes,Code::ResourceLimit,"Workspace limit exceeded");
    auto bound=add(add(104,mul(16,d)),add(mul(8,mul(c.atoms,c.length)),mul(mul(d,rows/c.length),add(4,mul(12,c.atoms)))));
    check(bound<=limits.output_bytes&&bound<=std::numeric_limits<std::size_t>::max(),Code::ResourceLimit,"Frame limit exceeded");return bound;
}
Selection correlate(const double* z,std::uint64_t rows,std::uint32_t channels,std::uint32_t length,double threshold,const Limits& limits)try{
    Config c;c.length=length;c.threshold=threshold;config(rows,channels,c,Code::InvalidArgument);fp();check(z&&reinterpret_cast<std::uintptr_t>(z)%alignof(double)==0,Code::InvalidArgument,"Null/unaligned Pearson input");
    check(mul(mul(rows,channels),8)<=limits.input_bytes,Code::ResourceLimit,"Pearson input limit exceeded");
    auto w=static_cast<std::size_t>(rows/length),d=static_cast<std::size_t>(channels),l=static_cast<std::size_t>(length);
    check(mul(8,add(mul(w,mul(d,d)),mul(3,w*d)))<=limits.workspace_bytes,Code::ResourceLimit,"Pearson workspace exceeded");
    for(std::uint64_t i=0;i<rows*channels;++i)check(std::isfinite(z[i]),Code::InvalidArgument,"Nonfinite Pearson input");
    Selection out;out.correlations.resize(w*d*d);out.order.resize(w*d);out.references.assign(w*d,-1);
    for(std::size_t window=0;window<w;++window){auto* matrix=out.correlations.data()+window*d*d;
        for(std::size_t x=0;x<d;++x)for(std::size_t y=0;y<=x;++y){double mx=0.,my=0.,sx=0.,sy=0.,cov=0.;
            for(std::size_t i=0;i<l;++i){auto off=(window*l+i)*d;double vx=z[off+x],vy=z[off+y],dx=vx-mx,dy=vy-my,reciprocal=1./static_cast<double>(i+1);
                mx+=reciprocal*dx;my+=reciprocal*dy;sx+=(vx-mx)*dx;sy+=(vy-my)*dy;cov+=(vx-mx)*dy;}
            double divisor=std::sqrt(sx*sy),value=divisor!=0.?cov/divisor:std::numeric_limits<double>::quiet_NaN();matrix[x*d+y]=matrix[y*d+x]=value;
        }
        std::vector<double> sums(d);for(std::size_t x=0;x<d;++x)for(std::size_t y=0;y<d;++y)sums[x]+=matrix[x*d+y];
        auto* order=out.order.data()+window*d;check(corad_rank_descending(sums.data(),d,order)==0,Code::NumericalFailure,"Stable rank failed");
        std::vector<bool> stored(d,false);
        for(std::size_t rank=0;rank<d;++rank){auto k=static_cast<std::size_t>(order[rank]);std::int32_t best=-1;double maximum=-std::numeric_limits<double>::infinity();
            for(std::size_t i=0;i<d;++i){auto value=matrix[k*d+i];if(stored[i]&&i!=k&&value>=threshold&&(best<0||value>maximum)){best=static_cast<std::int32_t>(i);maximum=value;}}
            out.references[k*w+window]=best;if(best<0)stored[k]=true;
        }
    }
    return out;
}catch(const std::bad_alloc&){throw Error(Code::ResourceLimit,"Pearson allocation failed");}
std::vector<std::uint8_t> encode(const double* input,std::uint64_t rows,std::uint32_t channels,const Config& c,const Limits& limits,Trace* trace)try{
    auto bound=compress_bound(rows,channels,c,limits);fp();check(input&&reinterpret_cast<std::uintptr_t>(input)%alignof(double)==0,Code::InvalidArgument,"Null/unaligned input");
    auto n=static_cast<std::size_t>(rows),d=static_cast<std::size_t>(channels),a=static_cast<std::size_t>(c.atoms),l=static_cast<std::size_t>(c.length),w=n/l;
    std::vector<double> z(n*d),means(d),scales(d),tricklets(d*w*l);std::vector<bool> constant(d,true);
    for(std::size_t i=0;i<n;++i)for(std::size_t j=0;j<d;++j){double v=input[i*d+j];check(std::isfinite(v),Code::InvalidArgument,"Nonfinite input");means[j]+=v;constant[j]=constant[j]&&(v==input[j]);}
    for(bool v:constant)check(!v,Code::InvalidArgument,"Constant column");
    if(d==1){means[0]=tristan::detail::numpy_sum(input,n);}for(auto& v:means)v/=static_cast<double>(n);
    for(std::size_t i=0;i<n;++i)for(std::size_t j=0;j<d;++j){double v=input[i*d+j]-means[j];scales[j]+=v*v;}
    if(d==1){std::vector<double> squares(n);for(std::size_t i=0;i<n;++i){double v=input[i]-means[0];squares[i]=v*v;}scales[0]=tristan::detail::numpy_sum(squares.data(),n);}
    for(auto& v:scales){v=std::sqrt(v/static_cast<double>(n));check(std::isfinite(v)&&v>0.,Code::InvalidArgument,"Invalid population scale");}
    for(std::size_t i=0;i<n;++i)for(std::size_t j=0;j<d;++j){double v=(input[i*d+j]-means[j])/scales[j];check(std::isfinite(v),Code::InvalidArgument,"Nonfinite normalized input");z[i*d+j]=v;if(i<w*l)tricklets[j*w*l+i]=v;}
    auto first=d>1?std::size_t{1}:std::size_t{0},last=d>1?std::min(d,std::size_t{8}):std::size_t{1};
    std::vector<double> training(tricklets.begin()+static_cast<std::ptrdiff_t>(first*w*l),tricklets.begin()+static_cast<std::ptrdiff_t>(last*w*l)),costs;
    auto dictionary=tristan::train(training,(last-first)*w,c,&costs,trace?&trace->learning_snapshots:nullptr);std::vector<double> coefficients;coefficients.reserve(d*w*a);
    for(std::size_t channel=0;channel<d;++channel){std::vector<double> part(tricklets.begin()+static_cast<std::ptrdiff_t>(channel*w*l),tricklets.begin()+static_cast<std::ptrdiff_t>((channel+1)*w*l));auto cc=tristan::sparse(part,w,dictionary,c);coefficients.insert(coefficients.end(),cc.begin(),cc.end());}
    auto selection=correlate(z.data(),rows,channels,c.length,c.threshold,limits);
    std::vector<std::uint8_t> frame;frame.reserve(static_cast<std::size_t>(bound));for(char v:std::string("CORAD001"))frame.push_back(static_cast<std::uint8_t>(v));
    put(frame,1,4);put(frame,104,4);put(frame,0,4);put(frame,static_cast<std::uint32_t>(c.solver),4);put(frame,rows,8);put(frame,channels,4);put(frame,c.length,4);put(frame,c.atoms,4);put(frame,c.nonzeros,4);put(frame,c.seed,4);put(frame,c.requested_n_iter,4);real(frame,c.alpha);put(frame,w,8);put(frame,0,8);put(frame,0,8);put(frame,0,4);put(frame,0,4);real(frame,c.threshold);
    for(std::size_t j=0;j<d;++j){real(frame,means[j]);real(frame,scales[j]);}for(double v:dictionary)real(frame,v);
    for(std::size_t i=0;i<d*w;++i){auto ref=selection.references[i];if(ref>=0){put(frame,UINT32_MAX,4);put(frame,static_cast<std::uint32_t>(ref),4);}else{
            auto offset=frame.size();put(frame,0,4);std::uint32_t count=0;
            for(std::size_t j=0;j<a;++j){double v=coefficients[i*a+j];check(std::isfinite(v),Code::NumericalFailure,"Nonfinite coefficient");if(v!=0.){put(frame,j,4);real(frame,v);++count;}}patch(frame,offset,count,4);}}
    patch(frame,72,frame.size()-104,8);patch(frame,88,crc(frame.data(),frame.size()),4);
    if(trace){trace->rows=rows;trace->channels=channels;trace->windows=w;trace->normalized=std::move(z);trace->dictionary=std::move(dictionary);trace->coefficients=std::move(coefficients);trace->means=std::move(means);trace->scales=std::move(scales);trace->costs=std::move(costs);trace->selection=std::move(selection);}
    return frame;
}catch(const std::bad_alloc&){throw Error(Code::ResourceLimit,"Encoder allocation failed");}
std::size_t compress(const double* input,std::uint64_t rows,std::uint32_t d,const Config& c,std::uint8_t* out,std::size_t capacity,const Limits& limits){
    auto bound=compress_bound(rows,d,c,limits);check(capacity>=bound,Code::OutputTooSmall,"Destination smaller than full bound");check(out!=nullptr,Code::InvalidArgument,"Null destination");auto a=reinterpret_cast<std::uintptr_t>(input),b=reinterpret_cast<std::uintptr_t>(out),bytes=mul(mul(rows,d),8);
    check(a<=UINTPTR_MAX-bytes&&b<=UINTPTR_MAX-capacity,Code::InvalidArgument,"Buffer range overflow");check(a+bytes<=b||b+capacity<=a,Code::InvalidArgument,"Overlapping buffers");auto frame=encode(input,rows,d,c,limits);std::memcpy(out,frame.data(),frame.size());return frame.size();
}
Decoded decode(const std::uint8_t* frame,std::size_t size,const Limits& limits)try{
    fp();check(frame&&size>=104,Code::CorruptStream,"Missing header");check(size<=limits.output_bytes,Code::ResourceLimit,"Frame limit exceeded");check(std::memcmp(frame,"CORAD001",8)==0,Code::CorruptStream,"Invalid magic");Reader r{frame,size,8};
    check(r.u32()==1&&r.u32()==104&&r.u32()==0,Code::CorruptStream,"Invalid version/header/flags");Decoded out;out.config.solver=static_cast<Solver>(r.u32());out.original_rows=r.get(8);out.channels=r.u32();out.config.length=r.u32();out.config.atoms=r.u32();out.config.nonzeros=r.u32();out.config.seed=r.u32();out.config.requested_n_iter=r.u32();out.config.alpha=r.number();out.windows=r.get(8);auto payload=r.get(8);check(r.get(8)==0,Code::CorruptStream,"Reserved bits");auto checksum=r.u32();check(r.u32()==0,Code::CorruptStream,"Reserved field");out.config.threshold=r.number();config(out.original_rows,out.channels,out.config,Code::CorruptStream);
    if(out.config.length==0||out.windows==0){throw Error(Code::CorruptStream,"Zero length/window count");}
    check(out.windows==out.original_rows/out.config.length&&payload==size-104,Code::CorruptStream,"Invalid window/payload size");
    auto d=static_cast<std::size_t>(out.channels),w=static_cast<std::size_t>(out.windows),l=static_cast<std::size_t>(out.config.length),a=static_cast<std::size_t>(out.config.atoms),elements=mul(mul(d,w),l);
    check(mul(elements,8)<=limits.output_bytes,Code::ResourceLimit,"Decoded output limit exceeded");check(payload>=add(mul(16,d),add(mul(8,mul(a,l)),mul(4,d*w))),Code::CorruptStream,"Missing dictionary/row tags");
    check(add(mul(8,add(a*l,elements)),add(mul(16,d),mul(4,d*w)))<=limits.workspace_bytes,Code::ResourceLimit,"Decoder workspace exceeded");check(crc(frame,size)==checksum,Code::CorruptStream,"CRC mismatch");
    out.means.resize(d);out.scales.resize(d);for(std::size_t j=0;j<d;++j){out.means[j]=r.number();out.scales[j]=r.number();check(out.scales[j]>0.,Code::CorruptStream,"Invalid scale");}
    std::vector<double> dictionary(a*l);for(auto& v:dictionary)v=r.number();out.values.resize(static_cast<std::size_t>(elements));std::vector<std::int32_t> refs(d*w,-1);std::uint64_t nnz=0,references=0;
    for(std::size_t i=0;i<d*w;++i){auto tag=r.u32();if(tag==UINT32_MAX){auto target=r.u32();check(target<d&&target!=i/w,Code::CorruptStream,"Invalid reference ID");refs[i]=static_cast<std::int32_t>(target);++references;}else{
            check(tag<=a&&mul(tag,12)<=r.size-r.pos,Code::CorruptStream,"Invalid atom count");std::uint32_t prev=0;
            for(std::uint32_t k=0;k<tag;++k){auto id=r.u32();double v=r.number();check(id<a&&(k==0||id>prev)&&v!=0.,Code::CorruptStream,"Invalid atom ID/coefficient");prev=id;
                for(std::size_t j=0;j<l;++j){auto& x=out.values[i*l+j];x+=dictionary[static_cast<std::size_t>(id)*l+j]*v;check(std::isfinite(x),Code::CorruptStream,"Reconstruction overflow");}}
            nnz=add(nnz,tag);}}
    check(r.pos==size,Code::CorruptStream,"Trailing frame bytes");
    for(std::size_t i=0;i<refs.size();++i)if(refs[i]>=0){auto target=static_cast<std::size_t>(refs[i])*w+i%w;check(refs[target]<0,Code::CorruptStream,"Reference target must be atom-coded");std::copy_n(out.values.data()+target*l,l,out.values.data()+i*l);}
    out.accounting.normalization_bytes=mul(16,d);out.accounting.dictionary_bytes=mul(8,a*l);out.accounting.tag_bytes=mul(4,d*w);out.accounting.index_bytes=mul(4,nnz);out.accounting.coefficient_bytes=mul(8,nnz);out.accounting.reference_bytes=mul(4,references);
    check(out.accounting.physical_bytes()==size,Code::CorruptStream,"Accounting mismatch");return out;
}catch(const std::bad_alloc&){throw Error(Code::ResourceLimit,"Decoder allocation failed");}
}

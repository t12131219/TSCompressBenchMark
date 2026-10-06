// SPDX-License-Identifier: BSD-3-Clause
// Copyright (c) 2007-2023 The scikit-learn developers.
// C++ translation of sklearn 1.3.0 dictionary learning, LARS, OMP and CD.
// License text: LICENSES/BSD-3-Clause-scikit-learn.txt.
#include "tristan.hpp"
#include "numerical_internal.hpp"
#include <algorithm>
#include <cfenv>
#include <cmath>
#include <limits>
#include <numeric>
#include <random>

extern "C" {
void cblas_dgemm(int,int,int,int,int,int,double,const double*,int,const double*,int,double,double*,int);
void cblas_dsyrk(int,int,int,int,int,double,const double*,int,double,double*,int);
void cblas_dgemv(int,int,int,int,double,const double*,int,const double*,int,double,double*,int);
double cblas_ddot(int,const double*,int,const double*,int);
double cblas_dnrm2(int,const double*,int);
double cblas_dasum(int,const double*,int);
void cblas_daxpy(int,double,const double*,int,double*,int);
void cblas_dtrsv(int,int,int,int,int,const double*,int,double*,int);
void cblas_drotg(double*,double*,double*,double*);
void cblas_drot(int,double*,int,double*,int,double,double);
void dpotrs_(const char*,const int*,const int*,const double*,const int*,double*,const int*,int*);
void dtrtrs_(const char*,const char*,const char*,const int*,const int*,const double*,const int*,double*,const int*,int*);
void dgesdd_(const char*,const int*,const int*,double*,const int*,double*,double*,const int*,double*,const int*,double*,const int*,int*,int*);
int MKL_Set_Num_Threads_Local(int);
int MKL_Get_Max_Threads();
void MKL_Get_Version_String(char*,int);
}

namespace tristan {
namespace {
constexpr int Row=101, No=111, Trans=112;
constexpr double eps=std::numeric_limits<double>::epsilon();
constexpr double equality=0x1p-23, tiny=0x1p-126;
struct Threads {
    int old=MKL_Set_Num_Threads_Local(1);
    ~Threads(){MKL_Set_Num_Threads_Local(old);}
};
void require(bool ok,const char* msg){if(!ok)throw Error(Code::InvalidArgument,msg);}
int integer(std::size_t x){require(x<=static_cast<std::size_t>(std::numeric_limits<int>::max()),"BLAS dimension exceeds int32");return static_cast<int>(x);}
void stage_limits(std::size_t m,const Config& c){
    require(m>0&&m<=7U*1048576U&&c.length>0&&c.length<=4096&&c.atoms>0&&c.atoms<=4096,"Numerical stage dimensions out of range");
    require(c.nonzeros>0&&c.nonzeros<=c.atoms&&static_cast<std::uint32_t>(c.solver)<=4,"Invalid numerical stage configuration");
    std::uint64_t a=c.atoms,l=c.length,samples=m,r=std::min(samples,l);
    if(8*samples*l>256ULL*1024*1024||8*(12*a*a+8*samples*a+32*a*l+4*samples*l+samples*r+r*l+8*r*r+8*r)>1ULL*1024*1024*1024){throw Error(Code::ResourceLimit,"Numerical stage resource limit exceeded");}
    if(std::fegetround()!=FE_TONEAREST){throw Error(Code::Unsupported,"Numerical stage requires nearest-even");}
    volatile double normal=std::numeric_limits<double>::min(),half=.5;
    if(normal*half==0.){throw Error(Code::Unsupported,"Numerical stage requires gradual underflow");}
}
double dot(const double* a,const double* b,std::size_t n){return cblas_ddot(integer(n),a,1,b,1);}
double norm(const double* a,std::size_t n){return cblas_dnrm2(integer(n),a,1);}
double sign(double x){return (x>0.)?1.:(x<0.?-1.:0.);}
// NumPy's pairwise sum for contiguous binary64 arrays (block size 128).
double sum(const double* a,std::size_t n){
    if(n<8){double r=-0.;for(std::size_t i=0;i<n;++i)r+=a[i];return r;}
    if(n<=128){double r[8];std::copy_n(a,8,r);std::size_t i=8;
        for(;i+7<n;i+=8)for(std::size_t k=0;k<8;++k)r[k]+=a[i+k];
        double s=((r[0]+r[1])+(r[2]+r[3]))+((r[4]+r[5])+(r[6]+r[7]));
        for(;i<n;++i){s+=a[i];}
        return s;}
    auto n2=(n/2)/8*8;return sum(a,n2)+sum(a+n2,n-n2);
}
struct Random {
    std::mt19937 mt; bool cached=false;double gaussian=0.;
    explicit Random(std::uint32_t s):mt(s){}
    std::uint32_t choice(std::uint32_t n){if(n==1){return 0;}std::uint32_t mask=n-1;mask|=mask>>1;mask|=mask>>2;mask|=mask>>4;mask|=mask>>8;mask|=mask>>16;
        std::uint32_t x;do{x=static_cast<std::uint32_t>(mt())&mask;}while(x>=n);return x;}
    double uniform(){auto a=mt()>>5,b=mt()>>6;return (static_cast<double>(a)*67108864.+static_cast<double>(b))/9007199254740992.;}
    double normal(){if(cached){cached=false;return gaussian;}double x,y,r;do{x=2.*uniform()-1.;y=2.*uniform()-1.;r=x*x+y*y;}while(r>=1.||r==0.);
        double f=std::sqrt(-2.*std::log(r)/r);gaussian=f*x;cached=true;return f*y;}
};
std::vector<double> fortran_dictionary(const std::vector<double>& d,std::size_t a,std::size_t l){
    std::vector<double> col(a*l);for(std::size_t i=0;i<a;++i)for(std::size_t j=0;j<l;++j)col[j*a+i]=d[i*l+j];return col;
}
std::vector<double> gram(const std::vector<double>& d,std::size_t a,std::size_t l){
    auto col=fortran_dictionary(d,a,l);std::vector<double> g(a*a);
    cblas_dsyrk(Row,121,Trans,integer(a),integer(l),1.,col.data(),integer(a),0.,g.data(),integer(a));
    for(std::size_t i=0;i<a;++i){for(std::size_t j=i+1;j<a;++j){g[j*a+i]=g[i*a+j];}}
    return g;
}
void swap_gram(std::vector<double>& g,std::size_t p,std::size_t q,std::size_t n){
    if(p==q){return;}
    for(std::size_t i=0;i<n;++i){std::swap(g[p*n+i],g[q*n+i]);}
    for(std::size_t i=0;i<n;++i){std::swap(g[i*n+p],g[i*n+q]);}
}
std::vector<double> solve(const std::vector<double>& L,std::size_t stride,std::size_t n,const double* rhs){
    std::vector<double> x(rhs,rhs+n),col(n*n);int ni=integer(n),one=1,info=0;char u='L';
    for(std::size_t i=0;i<n;++i)for(std::size_t j=0;j<=i;++j)col[j*n+i]=L[i*stride+j];
    dpotrs_(&u,&ni,&one,col.data(),&ni,x.data(),&ni,&info);
    if(info){throw Error(Code::NumericalFailure,"POTRS failed");}
    return x;
}
void triangular(const std::vector<double>& L,std::size_t stride,std::size_t n,double* rhs){
    // scipy.solve_triangular transposes a C-order factor and solves U^T.
    std::vector<double> col(n*n);int ni=integer(n),one=1,info=0;char lower='U',trans='T',nonunit='N';
    for(std::size_t i=0;i<n;++i)for(std::size_t j=0;j<=i;++j)col[i*n+j]=L[i*stride+j];
    dtrtrs_(&lower,&trans,&nonunit,&ni,&one,col.data(),&ni,rhs,&ni,&info);
    if(info)throw Error(Code::NumericalFailure,"TRTRS failed");
}
void delete_cholesky(std::vector<double>& L,std::size_t stride,std::size_t n,std::size_t out){
    for(std::size_t i=out;i+1<n;++i)std::copy_n(L.data()+(i+1)*stride,i+2,L.data()+i*stride);
    for(std::size_t i=out;i+1<n;++i){double c,s;cblas_drotg(&L[i*stride+i],&L[i*stride+i+1],&c,&s);
        if(L[i*stride+i]<0){L[i*stride+i]=std::abs(L[i*stride+i]);c=-c;s=-s;}L[i*stride+i+1]=0.;
        if(i+2<n)cblas_drot(integer(n-i-2),L.data()+(i+1)*stride+i,integer(stride),L.data()+(i+1)*stride+i+1,integer(stride),c,s);}
}
std::vector<double> omp(std::vector<double> g,std::vector<double> xy,std::size_t k){
    auto a=xy.size();std::vector<std::size_t> ids(a);std::iota(ids.begin(),ids.end(),0);
    std::vector<double> L(k*k),alpha=xy,beta(a),gamma,result(a);std::size_t active=0;
    for(std::size_t iter=0;iter<k;++iter){std::size_t lam=0;for(std::size_t i=1;i<a;++i)if(std::abs(alpha[i])>std::abs(alpha[lam]))lam=i;
        if(lam<active||alpha[lam]*alpha[lam]<eps)break;
        if(active){for(std::size_t j=0;j<active;++j)L[active*k+j]=g[lam*a+j];
            triangular(L,k,active,L.data()+active*k);
            double v=norm(L.data()+active*k,active);double pivot=g[lam*a+lam]-v*v;if(pivot<=eps)break;L[active*k+active]=std::sqrt(pivot);
        }else L[0]=std::sqrt(g[lam*a+lam]);
        swap_gram(g,active,lam,a);std::swap(ids[active],ids[lam]);std::swap(xy[active],xy[lam]);++active;
        gamma=solve(L,k,active,xy.data());cblas_dgemv(Row,No,integer(a),integer(active),1.,g.data(),integer(a),gamma.data(),1,0.,beta.data(),1);
        for(std::size_t i=0;i<a;++i)alpha[i]=xy[i]-beta[i];
    }
    for(std::size_t i=0;i<active;++i){result[ids[i]]=gamma[i];}
    return result;
}
std::vector<double> lars(const std::vector<double>& initial_g,const std::vector<double>& xy,std::size_t length,std::size_t max_iter,double alpha_min,bool lasso,std::vector<std::vector<double>>* debug=nullptr){
    const auto a=xy.size(),cap=std::min(max_iter,a);auto g=initial_g,cov=xy;
    std::vector<std::size_t> ids(a),active;std::iota(ids.begin(),ids.end(),0);
    std::vector<double> L(cap*cap),signs(cap),coef(a),prev(a);double previous_alpha=0.;bool drop=false;
    std::size_t iter=0,retries=0;
    for(;;){auto na=active.size();std::size_t selected=0;for(std::size_t j=1;j<cov.size();++j)if(std::abs(cov[j])>std::abs(cov[selected]))selected=j;
        double C_=cov.empty()?0.:cov[selected],C=std::abs(C_),alpha=C/static_cast<double>(length);
        if(alpha<=alpha_min+equality){if(std::abs(alpha-alpha_min)>equality&&iter){double ss=(previous_alpha-alpha_min)/(previous_alpha-alpha);
                for(std::size_t i=0;i<a;++i)coef[i]=prev[i]+ss*(coef[i]-prev[i]);}break;}
        if(iter>=max_iter||na>=a)break;
        if(!drop){signs[na]=sign(C_);auto n=selected+na;std::swap(cov[selected],cov[0]);std::swap(ids[n],ids[na]);
            double saved=cov[0];cov.erase(cov.begin());swap_gram(g,na,n,a);
            for(std::size_t j=0;j<na;++j)L[na*cap+j]=g[na*a+j];
            if(na)triangular(L,cap,na,L.data()+na*cap);
            double v=dot(L.data()+na*cap,L.data()+na*cap,na);double pivot=std::max(std::sqrt(std::abs(g[na*a+na]-v)),eps);L[na*cap+na]=pivot;
            if(pivot<1e-7){cov.insert(cov.begin(),saved);cov[0]=0.;std::swap(cov[selected],cov[0]);
                if(++retries>1000){throw Error(Code::NumericalFailure,"Degenerate LARS retries exhausted");}
                continue;}
            active.push_back(ids[na]);++na;
        }
        if(lasso&&iter&&previous_alpha<alpha)break;
        auto ls=solve(L,cap,na,signs.data());double AA;
        if(ls.size()==1&&ls[0]==0.){ls[0]=1.;AA=1.;}
        else{std::vector<double> prod(na);for(std::size_t j=0;j<na;++j)prod[j]=ls[j]*signs[j];AA=1./std::sqrt(sum(prod.data(),na));
            if(!std::isfinite(AA)){auto regular=L;for(std::size_t retry=0;!std::isfinite(AA);++retry){
                    if(retry>60)throw Error(Code::NumericalFailure,"Ill-conditioned LARS factor");
                    for(std::size_t j=0;j<na;++j)regular[j*cap+j]+=std::ldexp(eps,static_cast<int>(retry));
                    ls=solve(regular,cap,na,signs.data());for(std::size_t j=0;j<na;++j)prod[j]=ls[j]*signs[j];AA=1./std::sqrt(std::max(sum(prod.data(),na),eps));}}
            for(auto& x:ls)x*=AA;
        }
        std::vector<double> corr(a-na);
        if(!corr.empty()){
            // NumPy copies this noncontiguous transposed Gram view to C order.
            std::vector<double> packed((a-na)*na);
            for(std::size_t i=0;i<a-na;++i)for(std::size_t j=0;j<na;++j)packed[i*na+j]=g[j*a+na+i];
            cblas_dgemv(Row,No,integer(a-na),integer(na),1.,packed.data(),integer(na),ls.data(),1,0.,corr.data(),1);
        }
        double gamma=C/AA;for(std::size_t j=0;j<corr.size();++j){corr[j]=std::nearbyint(corr[j]*1e15)/1e15;
            double g1=(C-cov[j])/(AA-corr[j]+tiny),g2=(C+cov[j])/(AA+corr[j]+tiny);if(g1>0.)gamma=std::min(gamma,g1);if(g2>0.)gamma=std::min(gamma,g2);}
        drop=false;double zpos=std::numeric_limits<double>::max();std::vector<double> z(na);
        for(std::size_t j=0;j<na;++j){z[j]=-coef[active[j]]/(ls[j]+tiny);if(z[j]>0.)zpos=std::min(zpos,z[j]);}
        std::vector<std::size_t> dropped;
        if(zpos<gamma){for(std::size_t j=na;j-->0;)if(z[j]==zpos){dropped.push_back(j);signs[j]=-signs[j];}if(lasso)gamma=zpos;drop=true;}
        ++iter;prev=coef;previous_alpha=alpha;std::fill(coef.begin(),coef.end(),0.);
        for(std::size_t j=0;j<na;++j)coef[active[j]]=prev[active[j]]+gamma*ls[j];
        for(std::size_t j=0;j<cov.size();++j)cov[j]-=gamma*corr[j];
        if(debug){std::vector<double> record={C,AA,gamma,static_cast<double>(na)};record.insert(record.end(),coef.begin(),coef.end());
            record.insert(record.end(),cov.begin(),cov.end());record.resize(4+2*a,0.);
            for(std::size_t i=0;i<a;++i)for(std::size_t j=0;j<a;++j)record.push_back(i<na&&j<=i?L[i*cap+j]:0.);
            for(std::size_t i=0;i<a;++i)record.push_back(i<na?ls[i]:0.);
            debug->push_back(std::move(record));}
        if(drop&&lasso){std::vector<std::size_t> drop_ids;
            for(auto ii:dropped){delete_cholesky(L,cap,na,ii);drop_ids.push_back(active[ii]);active.erase(active.begin()+static_cast<std::ptrdiff_t>(ii));}
            --na; // Preserve upstream 1.3.0 multiple-drop behavior.
            for(auto ii:dropped){for(std::size_t j=ii;j<na;++j){std::swap(ids[j],ids[j+1]);swap_gram(g,j,j+1,a);}signs.erase(signs.begin()+static_cast<std::ptrdiff_t>(ii));signs.push_back(0.);}
            std::vector<double> temp;for(auto id:drop_ids)temp.push_back(xy[id]-dot(initial_g.data()+id*a,coef.data(),a));
            cov.insert(cov.begin(),temp.begin(),temp.end());
        }
    }
    return coef;
}
std::vector<double> cd(const std::vector<double>& g,const std::vector<double>& q,double y_norm){
    auto a=q.size();std::vector<double> w(a),H(a);const double tol=1e-4*y_norm;
    for(std::size_t iter=0;iter<1000;++iter){double wm=0.,dw=0.;
        for(std::size_t j=0;j<a;++j){double diagonal=g[j*a+j];if(diagonal==0.)continue;double old=w[j];
            if(old!=0.)cblas_daxpy(integer(a),-old,g.data()+j*a,1,H.data(),1);
            double t=q[j]-H[j];w[j]=sign(t)*std::max(std::abs(t)-1.,0.)/diagonal;
            if(w[j]!=0.)cblas_daxpy(integer(a),w[j],g.data()+j*a,1,H.data(),1);
            dw=std::max(dw,std::abs(w[j]-old));wm=std::max(wm,std::abs(w[j]));}
        if(wm==0.||dw/wm<1e-4||iter==999){double qw=dot(w.data(),q.data(),a),tmp=0.,dual=0.;for(std::size_t j=0;j<a;++j){tmp+=w[j]*H[j];dual=std::max(dual,std::abs(q[j]-H[j]));}
            double rn=y_norm+tmp-2.*qw,c=dual>1.?1./dual:1.;double gap=dual>1.?0.5*(rn+rn*c*c):rn;
            gap+=cblas_dasum(integer(a),w.data(),1)-c*y_norm+c*qw;if(gap<tol)break;}
    }
    return w;
}
std::vector<double> sparse_impl(const std::vector<double>& x,std::size_t m,const std::vector<double>& d,const Config& cfg,double regularization){
    stage_limits(m,cfg);
    auto a=static_cast<std::size_t>(cfg.atoms),l=static_cast<std::size_t>(cfg.length);
    require(a&&l&&m&&d.size()==a*l&&x.size()==m*l,"Invalid sparse matrix shape");require(cfg.nonzeros>0&&cfg.nonzeros<=a,"Invalid requested sparsity");
    for(double v:x){require(std::isfinite(v),"Nonfinite sparse input");}
    for(double v:d){require(std::isfinite(v),"Nonfinite dictionary");}
    auto g=gram(d,a,l);std::vector<double> cov(a*m),out(m*a);
    auto column_dictionary=fortran_dictionary(d,a,l);
    cblas_dgemm(Row,Trans,Trans,integer(a),integer(m),integer(l),1.,column_dictionary.data(),integer(a),x.data(),integer(l),0.,cov.data(),integer(m));
    for(std::size_t row=0;row<m;++row){std::vector<double> q(a),code;for(std::size_t j=0;j<a;++j)q[j]=cov[j*m+row];
        switch(cfg.solver){case Solver::Omp:code=omp(g,q,cfg.nonzeros);break;
        case Solver::Lars:code=lars(g,q,l,cfg.nonzeros,0.,false);break;
        case Solver::LassoLars:code=lars(g,q,l,1000,regularization/static_cast<double>(l),true);break;
        case Solver::LassoCd:code=cd(g,q,dot(x.data()+row*l,x.data()+row*l,l));break;
        case Solver::Threshold:code=q;for(auto& v:code)v=sign(v)*std::max(std::abs(v)-regularization,0.);break;
        default:throw Error(Code::InvalidArgument,"Unknown sparse solver");}
        std::copy(code.begin(),code.end(),out.begin()+static_cast<std::ptrdiff_t>(row*a));}
    return out;
}
} // namespace

double detail::numpy_sum(const double* values,std::size_t count){return sum(values,count);}

std::vector<double> rng_trace(std::uint32_t seed){Random r(seed);std::vector<double> out;for(int i=0;i<12;++i)out.push_back(r.uniform());for(int i=0;i<12;++i)out.push_back(r.choice(60));for(int i=0;i<16;++i)out.push_back(r.normal());return out;}
std::string backend_info(){Threads threads;char version[256]={};MKL_Get_Version_String(version,256);return std::string(version)+"; threads_requested=1; threads_used="+std::to_string(MKL_Get_Max_Threads())+"; ISA=MKL_runtime_dispatch";}
std::vector<double> debug_lars(const std::vector<double>& g,const std::vector<double>& q,std::uint32_t length,std::vector<std::vector<double>>& records){
    require(length>0&&length<=4096&&q.size()>0&&q.size()<=4096&&g.size()==q.size()*q.size(),"Invalid diagnostic LARS shape");
    Config c;c.length=length;c.atoms=static_cast<std::uint32_t>(q.size());c.nonzeros=1;stage_limits(1,c);
    for(double v:g){require(std::isfinite(v),"Nonfinite diagnostic Gram matrix");}
    for(double v:q){require(std::isfinite(v),"Nonfinite diagnostic covariance");}
    Threads threads;return lars(g,q,length,1000,1./length,true,&records);
}
std::vector<double> sparse(const std::vector<double>& x,std::size_t m,const std::vector<double>& d,const Config& c)try{Threads threads;return sparse_impl(x,m,d,c,1.);}catch(const std::bad_alloc&){throw Error(Code::ResourceLimit,"Sparse allocation failed");}
std::vector<double> train(const std::vector<double>& x,std::size_t samples,const Config& cfg,std::vector<double>* costs,std::vector<std::vector<double>>* snapshots)try{
    stage_limits(samples,cfg);
    Threads threads;auto l=static_cast<std::size_t>(cfg.length),a=static_cast<std::size_t>(cfg.atoms);require(l&&a&&samples&&x.size()==samples*l,"Invalid training shape");
    for(double v:x){require(std::isfinite(v),"Nonfinite training input");}
    require(std::isfinite(cfg.alpha)&&cfg.alpha>=0.,"Invalid learning alpha");
    int m=integer(samples),n=integer(l),r=std::min(m,n),lda=m,ldu=m,ldvt=r,info=0,workn=-1;char job='S';
    std::vector<double> col(samples*l),sing(static_cast<std::size_t>(r)),U(samples*static_cast<std::size_t>(r)),VT(static_cast<std::size_t>(r)*l);
    for(std::size_t i=0;i<samples;++i)for(std::size_t j=0;j<l;++j)col[j*samples+i]=x[i*l+j];
    std::vector<int> iwork(static_cast<std::size_t>(8*r));double query=0.;
    dgesdd_(&job,&m,&n,col.data(),&lda,sing.data(),U.data(),&ldu,VT.data(),&ldvt,&query,&workn,iwork.data(),&info);
    if(info||!std::isfinite(query)||query>std::numeric_limits<int>::max()){throw Error(Code::NumericalFailure,"SVD workspace query failed");}
    workn=static_cast<int>(query);std::vector<double> work(static_cast<std::size_t>(workn));
    dgesdd_(&job,&m,&n,col.data(),&lda,sing.data(),U.data(),&ldu,VT.data(),&ldvt,work.data(),&workn,iwork.data(),&info);
    if(info)throw Error(Code::NumericalFailure,"Dictionary SVD failed");
    std::vector<double> d(a*l);for(std::size_t k=0;k<std::min(a,static_cast<std::size_t>(r));++k){auto uc=U.data()+k*samples;auto i=std::size_t{0};for(std::size_t j=1;j<samples;++j)if(std::abs(uc[j])>std::abs(uc[i]))i=j;
        auto s=sign(uc[i]);for(std::size_t j=0;j<l;++j)d[k*l+j]=sing[k]*(VT[j*static_cast<std::size_t>(r)+k]*s);}
    Random rng(cfg.seed);Config fit=cfg;fit.solver=Solver::LassoLars;double prev_cost=0.;if(costs)costs->clear();
    if(snapshots){snapshots->clear();snapshots->push_back(d);}
    for(std::size_t iteration=0;iteration<10;++iteration){auto codes=sparse_impl(x,samples,d,fit,cfg.alpha);std::vector<double> A(a*a),B(l*a);
        cblas_dsyrk(Row,121,Trans,integer(a),m,1.,codes.data(),integer(a),0.,A.data(),integer(a));
        for(std::size_t i=0;i<a;++i)for(std::size_t j=i+1;j<a;++j)A[j*a+i]=A[i*a+j];
        cblas_dgemm(Row,Trans,No,n,integer(a),m,1.,x.data(),n,codes.data(),integer(a),0.,B.data(),integer(a));
        for(std::size_t k=0;k<a;++k){if(A[k*a+k]>1e-6){std::vector<double> product(l);auto col_d=fortran_dictionary(d,a,l);cblas_dgemv(Row,No,n,integer(a),1.,col_d.data(),integer(a),A.data()+k*a,1,0.,product.data(),1);
                for(std::size_t j=0;j<l;++j)d[k*l+j]+=(B[j*a+k]-product[j])/A[k*a+k];
            }else{auto row=static_cast<std::size_t>(rng.choice(static_cast<std::uint32_t>(samples)));auto newd=x.data()+row*l;
                double mean=sum(newd,l)/static_cast<double>(l);std::vector<double> variance(l);for(std::size_t j=0;j<l;++j){double v=newd[j]-mean;variance[j]=v*v;}
                double stddev=std::sqrt(sum(variance.data(),l)/static_cast<double>(l));double noise=.01*(stddev==0.?1.:stddev);
                for(std::size_t j=0;j<l;++j){d[k*l+j]=newd[j]+noise*rng.normal();}
                for(std::size_t i=0;i<samples;++i){codes[i*a+k]=0.;}}
            double denominator=std::max(norm(d.data()+k*l,l),1.);for(std::size_t j=0;j<l;++j)d[k*l+j]/=denominator;}
        if(snapshots)snapshots->push_back(d);
        std::vector<double> residual(samples*l),absolute(codes.size());
        auto col_d=fortran_dictionary(d,a,l);
        cblas_dgemm(Row,No,Trans,m,n,integer(a),1.,codes.data(),integer(a),col_d.data(),integer(a),0.,residual.data(),n);
        for(std::size_t i=0;i<residual.size();++i){double v=x[i]-residual[i];residual[i]=v*v;}for(std::size_t i=0;i<codes.size();++i)absolute[i]=std::abs(codes[i]);
        double cost=.5*sum(residual.data(),residual.size())+cfg.alpha*sum(absolute.data(),absolute.size());if(costs)costs->push_back(cost);
        if(iteration&&prev_cost-cost<1e-8*cost){break;}
        prev_cost=cost;
    }
    for(double v:d){if(!std::isfinite(v)){throw Error(Code::NumericalFailure,"Nonfinite learned dictionary");}}
    return d;
}catch(const std::bad_alloc&){throw Error(Code::ResourceLimit,"Training allocation failed");}
} // namespace tristan

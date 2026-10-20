#pragma once
#include "tsbench_core.h"
#include "tscb_adapter_v1.h"
#include <cctype>
#include <cmath>
#include <cstring>
#include <limits>
#include <map>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace tsbench_core {
struct Unsupported : std::runtime_error { using std::runtime_error::runtime_error; };
struct Capacity : std::runtime_error { using std::runtime_error::runtime_error; };
struct State { std::string error; virtual ~State() = default; };
inline std::string& last_error() { static thread_local std::string value; return value; }
template<class F> int guard(State* state, F function) noexcept {
    try { function(); return 0; }
    catch (const Unsupported& e) { last_error()=e.what(); if(state)state->error=e.what(); return 2; }
    catch (const Capacity& e) { last_error()=e.what(); if(state)state->error=e.what(); return 3; }
    catch (const std::exception& e) { last_error()=e.what(); if(state)state->error=e.what(); return 1; }
    catch (...) { last_error()="unknown direct codec error"; if(state)state->error=last_error(); return 1; }
}
inline void require(bool condition, const char* error) { if(!condition)throw std::invalid_argument(error); }
inline size_t add(size_t a,size_t b) { if(b>SIZE_MAX-a)throw Capacity("direct size overflow");return a+b; }
inline size_t multiply(size_t a,size_t b) { if(a&&b>SIZE_MAX/a)throw Capacity("direct size overflow");return a*b; }
inline size_t width(uint32_t code) {
    static const size_t widths[]={0,1,1,2,2,4,4,8,8,4,8,1};
    require(code>0&&code<12,"invalid direct dtype");return widths[code];
}
inline size_t elements(const tsbench_core_config& config) {
    require(config.version==1&&config.rank>0&&config.rank<=8&&config.order<=1,"invalid direct configuration geometry");
    size_t result=1;for(uint32_t i=0;i<config.rank;++i)result=multiply(result,config.shape[i]);return result;
}
inline size_t input_bytes(const tsbench_core_config& config) { return multiply(elements(config),width(config.dtype)); }

/* Flat JSON is emitted by Python's canonical encoder. No external parser or
 * shell evaluation is used. Reject duplicated keys, unknown syntax and NaN.
 */
class Parameters {
    std::map<std::string,std::string> values_;
    std::map<std::string,bool> strings_;
public:
    explicit Parameters(const char* source) {
        std::string text=source?source:"{}";size_t at=0;
        auto space=[&]{while(at<text.size()&&std::isspace(static_cast<unsigned char>(text[at])))++at;};
        auto ch=[&](char value){space();require(at<text.size()&&text[at++]==value,"invalid direct parameter JSON");};
        auto quoted=[&](){ch('"');std::string result;bool done=false;while(at<text.size()){
            char c=text[at++];if(c=='"'){done=true;break;}if(c=='\\'){
                require(at<text.size(),"truncated direct parameter escape");c=text[at++];
                require(c=='"'||c=='\\'||c=='/',"unsupported direct parameter escape");
            }require(static_cast<unsigned char>(c)>=32,"invalid direct parameter string");result+=c;
        }require(done,"unterminated direct parameter string");return result;};
        ch('{');space();
        if(at<text.size()&&text[at]!='}') {
          for(;;){
            std::string key=quoted();ch(':');space();bool string=at<text.size()&&text[at]=='"';std::string value;
            if(string)value=quoted();else{size_t start=at;while(at<text.size()&&text[at]!=','&&text[at]!='}'&&!std::isspace(static_cast<unsigned char>(text[at])))++at;value=text.substr(start,at-start);require(!value.empty(),"empty direct parameter");}
            require(values_.emplace(key,value).second,"duplicate direct parameter");strings_[key]=string;space();
            require(at<text.size(),"truncated direct parameter JSON");if(text[at]!=',')break;++at;
          }
        }
        ch('}');space();require(at==text.size(),"trailing direct parameter JSON");
    }
    bool contains(const std::string& key)const{return values_.count(key)!=0;}
    bool empty()const{return values_.empty();}
    std::string string(const std::string& key)const{require(strings_.at(key),"direct parameter must be a string");return values_.at(key);}
    long long integer(const std::string& key,long long minimum=std::numeric_limits<long long>::min(),long long maximum=std::numeric_limits<long long>::max())const{
        const auto& value=values_.at(key);require(!strings_.at(key),"direct integer must be numeric");size_t used=0;long long result=std::stoll(value,&used);
        require(used==value.size()&&result>=minimum&&result<=maximum,"direct integer parameter out of range");return result;
    }
    double real(const std::string& key)const{
        const auto& value=values_.at(key);size_t used=0;double result=std::stod(value,&used);
        require(used==value.size()&&std::isfinite(result),"invalid direct real parameter");return result;
    }
    bool boolean(const std::string& key)const{const auto& value=values_.at(key);require(!strings_.at(key)&&(value=="true"||value=="false"),"invalid direct bool parameter");return value=="true";}
};

struct Owner { virtual ~Owner()=default; };
template<class T>struct VectorOwner final:Owner { std::vector<T> values;explicit VectorOwner(std::vector<T>&& v):values(std::move(v)){} };
template<class T>void vector_result(std::vector<T>&& values,tsbench_core_result* result) {
    require(result,"null direct result");auto owner=new VectorOwner<T>(std::move(values));
    result->data=reinterpret_cast<const uint8_t*>(owner->values.data());result->size=owner->values.size()*sizeof(T);
    result->capacity=owner->values.capacity()*sizeof(T);result->owner=owner;
}
inline void caller_result(uint8_t* data,size_t used,size_t capacity,tsbench_core_result* result) {
    require(result&&used<=capacity,"invalid direct caller result");*result={data,used,capacity,nullptr};
}
inline void release(tsbench_core_result* result)noexcept{if(result){delete static_cast<Owner*>(result->owner);*result={};}}
} // namespace tsbench_core

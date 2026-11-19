#pragma once
#include "tv_bundle.hpp"

namespace tsbench::tv {
// Canonical files are little-endian. The eight bytes of each f64 already are
// its four consecutive low-to-high u16 limbs; transpose only, no FP operation.
inline Bytes pack_limbs(const std::vector<Bytes> &columns,const Stride &s) {
    Bytes packed(s.rows*s.columns*8);
    for (size_t r=0;r<s.rows;++r)
        for (size_t j=0;j<s.columns;++j)
            std::memcpy(packed.data()+8*(r*s.columns+j),columns[s.first+j].data()+8*(s.row+r),8);
    return packed;
}
inline void unpack_limbs(const uint8_t *packed,std::vector<Bytes> &columns,const Stride &s) {
    for (size_t r=0;r<s.rows;++r)
        for (size_t j=0;j<s.columns;++j)
            std::memcpy(columns[s.first+j].data()+8*(s.row+r),packed+8*(r*s.columns+j),8);
}
}

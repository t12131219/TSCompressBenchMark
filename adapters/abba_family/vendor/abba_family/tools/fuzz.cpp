// SPDX-License-Identifier: MIT
#include "abba_family.hpp"
#include "abba_family_c.h"
#include <cstdint>
#include <vector>
#include <zlib.h>
extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, std::size_t size) {
  if (size < 1 || size > 65536)
    return 0;
  try {
    if (data[0] % 3 < 2) {
      std::vector<uint8_t> b(data + 1, data + size);
      if (data[0] % 3 == 0 && b.size() >= 24) {
        auto crc = crc32(0, b.data(), uInt(b.size() - 4));
        for (unsigned i = 0; i < 4; ++i)
          b[b.size() - 4 + i] = uint8_t(crc >> (8 * i));
      }
      abba_family::decode(b.data(), b.size());
    } else {
      std::size_t n, need;
      char out[8192];
      af_execute_v1(reinterpret_cast<const char *>(data + 1), size - 1, out,
                    sizeof out, &n, &need);
    }
  } catch (const std::exception &) {
  }
  return 0;
}

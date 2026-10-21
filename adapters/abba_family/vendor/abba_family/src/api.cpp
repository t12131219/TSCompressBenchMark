// SPDX-License-Identifier: MIT AND BSD-3-Clause
#include "abba_family_c.h"
#include "internal.hpp"
#include <cstring>
#include <new>
extern "C" unsigned af_api_version_v1(void) { return 1; }
extern "C" int af_execute_v1(const char *request, std::size_t n, char *out,
                             std::size_t cap, std::size_t *made,
                             std::size_t *required) {
  if (made)
    *made = 0;
  if (required)
    *required = 0;
  if (!made || !required || !request || n == 0 || n > 16777216 || (!out && cap))
    return AF_INVALID;
  try {
    auto j = abba_family::parse_request(std::string(request, n));
    auto result = abba_family::execute(j);
    std::string text = result.dump();
    *required = text.size();
    if (cap < text.size() || !out)
      return AF_CAPACITY;
    std::memmove(out, text.data(), text.size());
    *made = text.size();
    return AF_OK;
  } catch (const std::bad_alloc &) {
    return AF_NOMEM;
  } catch (const std::invalid_argument &) {
    return AF_INVALID;
  } catch (const nlohmann::json::exception &) {
    return AF_INVALID;
  } catch (...) {
    return AF_INTERNAL;
  }
}

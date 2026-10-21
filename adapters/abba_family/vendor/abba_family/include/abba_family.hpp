// SPDX-License-Identifier: MIT
#pragma once
#include "af_json.hpp"
#include <cstdint>
#include <string>
#include <vector>
namespace abba_family {
using Json = nlohmann::json;
// Native C++ value API. Model tokens contain every state item needed for reuse.
// Throws std::exception on invalid requests/resources. No input is modified.
Json execute(const Json &request);
// Bounded UTF-8 JSON parser for untrusted textual requests.
Json parse_request(const std::string &text);
std::vector<std::uint8_t> encode(const Json &request);
Json decode(const std::uint8_t *data, std::size_t bytes);
} // namespace abba_family

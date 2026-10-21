// SPDX-License-Identifier: MIT AND BSD-3-Clause
#include "internal.hpp"
#include <algorithm>
#include <cstring>
#include <zlib.h>
namespace abba_family {
namespace {
void append(std::vector<std::uint8_t> &out, std::uint64_t x, unsigned w) {
  for (unsigned i = 0; i < w; ++i)
    out.push_back(std::uint8_t(x >> (8 * i)));
}
std::uint64_t read(const std::uint8_t *p, std::size_t n, std::size_t &at,
                   unsigned w) {
  require(at <= n && w <= n - at, "truncated frame");
  std::uint64_t x = 0;
  for (unsigned i = 0; i < w; ++i)
    x |= std::uint64_t(p[at++]) << (8 * i);
  return x;
}
void json_guard(const std::string &s) {
  require(s.size() <= 16777216, "JSON byte limit");
  int depth = 0;
  std::size_t nodes = 0;
  bool quoted = false, escape = false;
  for (char ch : s) {
    if (quoted) {
      if (escape)
        escape = false;
      else if (ch == '\\')
        escape = true;
      else if (ch == '"')
        quoted = false;
    } else if (ch == '"')
      quoted = true;
    else if (ch == '{' || ch == '[') {
      require(++depth <= 64, "JSON depth limit");
      ++nodes;
    } else if (ch == '}' || ch == ']') {
      require(--depth >= 0, "JSON balance");
    } else if (ch == ',' || ch == ':')
      ++nodes;
  }
  require(!quoted && depth == 0 && nodes <= 2000000, "JSON structure limit");
}
} // namespace
Json parse_request(const std::string &text) {
  json_guard(text);
  return Json::parse(text);
}
std::string hex(const std::vector<std::uint8_t> &bytes) {
  static const char *table = "0123456789abcdef";
  std::string out;
  out.reserve(bytes.size() * 2);
  for (auto b : bytes) {
    out += table[b >> 4];
    out += table[b & 15];
  }
  return out;
}
std::vector<std::uint8_t> unhex(const std::string &s) {
  require(s.size() % 2 == 0 && s.size() / 2 <= MAX_FRAME, "invalid hex size");
  std::vector<std::uint8_t> out;
  out.reserve(s.size() / 2);
  auto digit = [](char c) {
    if (c >= '0' && c <= '9')
      return c - '0';
    if (c >= 'a' && c <= 'f')
      return c - 'a' + 10;
    if (c >= 'A' && c <= 'F')
      return c - 'A' + 10;
    throw std::invalid_argument("invalid hex character");
  };
  for (std::size_t i = 0; i < s.size(); i += 2)
    out.push_back(std::uint8_t((digit(s[i]) << 4) | digit(s[i + 1])));
  return out;
}
std::vector<std::uint8_t> encode(const Json &request) {
  auto result =
      request.value("image", false) ? image_fit(request) : fit(request);
  Json model = result.at("model");
  auto symbols = model.at("symbols");
  model.erase("symbols");
  Json seq = Json::array();
  if (model.at("single").get<bool>())
    seq.push_back(symbols);
  else
    seq = symbols;
  model["streams"] = Json::array();
  std::vector<std::uint8_t> payload;
  std::string codec = model.at("config").value(
      "symbol_codec",
      model.at("algorithm").get_ref<const std::string &>() == "qabba"
          ? "none"
          : "fixed");
  for (auto &s : seq) {
    auto ids = symbol_ids(s, model.at("alphabet"));
    Json meta;
    auto data = symbol_pack(ids, model.at("alphabet").size(), codec, meta);
    model["streams"].push_back([&]() {
      Json result_object = Json::object();
      result_object["count"] = ids.size();
      result_object["bytes"] = data.size();
      result_object["codec"] = codec;
      result_object["metadata"] = meta;
      return result_object;
    }());
    payload.insert(payload.end(), data.begin(), data.end());
  }
  std::string text = model.dump();
  json_guard(text);
  require(text.size() <= MAX_FRAME - 24 &&
              payload.size() <= MAX_FRAME - 24 - text.size(),
          "frame size limit");
  std::vector<std::uint8_t> out{'A', 'F', 'S', '1'};
  append(out, 1, 4);
  append(out, text.size(), 4);
  append(out, payload.size(), 8);
  out.insert(out.end(), text.begin(), text.end());
  out.insert(out.end(), payload.begin(), payload.end());
  append(out, crc32(0, out.data(), uInt(out.size())), 4);
  return out;
}
Json decode(const std::uint8_t *p, std::size_t n) {
  require(p && n >= 24 && n <= MAX_FRAME, "frame size limit");
  require(std::memcmp(p, "AFS1", 4) == 0, "frame magic");
  std::size_t at = 4;
  require(read(p, n, at, 4) == 1, "frame version");
  auto jsonsize = read(p, n, at, 4), payloadsize = read(p, n, at, 8);
  require(jsonsize <= 16777216 && jsonsize <= n - 24 &&
              payloadsize == n - 24 - jsonsize,
          "frame length accounting");
  std::size_t tail = n - 4;
  auto crc = read(p, n, tail, 4);
  require(crc32(0, p, uInt(n - 4)) == crc, "frame CRC");
  std::string text(reinterpret_cast<const char *>(p + at),
                   std::size_t(jsonsize));
  json_guard(text);
  Json model = Json::parse(text);
  at += std::size_t(jsonsize);
  require(model.is_object() && model.contains("streams"), "frame model");
  auto streams = model.at("streams");
  require(streams.is_array() && !streams.empty() && streams.size() <= 4096,
          "stream count");
  require(model.at("starts").is_array() &&
              model.at("starts").size() == streams.size(),
          "start count");
  auto alph = model.at("alphabet");
  require(alph.is_array() && !alph.empty() && alph.size() <= MAX_CENTERS,
          "frame alphabet");
  Json seq = Json::array();
  std::size_t count = 0;
  for (auto &s : streams) {
    auto size = s.at("bytes").get<std::uint64_t>(),
         items = s.at("count").get<std::uint64_t>();
    require(size <= n - 4 - at && items <= MAX_SAMPLES - count,
            "stream length");
    std::vector<std::uint8_t> data(p + at, p + at + std::size_t(size));
    at += std::size_t(size);
    count += std::size_t(items);
    auto ids = symbol_unpack(data, std::size_t(items), alph.size(),
                             s.at("codec"), s.at("metadata"));
    seq.push_back(symbolic(ids, alph));
  }
  require(at == n - 4, "trailing frame bytes");
  bool single = model.at("single").get<bool>();
  require(!single || seq.size() == 1, "single series count");
  model["symbols"] = single ? seq[0] : seq;
  model.erase("streams");
  auto rec = inverse(model, model.at("symbols"), model.at("starts"));
  Json out = [&]() {
    Json result_object = Json::object();
    result_object["algorithm"] = model.at("algorithm");
    result_object["model"] = model;
    result_object["symbols"] = model.at("symbols");
    result_object["reconstructed"] = rec;
    result_object["physical_bytes"] = n;
    result_object["final_bits"] = n * 8;
    result_object["external_side_information_bits"] = 0;
    return result_object;
  }();
  if (model.contains("image"))
    out["image"] = image_restore(model, rec);
  return out;
}
} // namespace abba_family

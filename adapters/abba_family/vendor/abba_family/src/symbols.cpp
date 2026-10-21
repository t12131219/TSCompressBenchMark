// SPDX-License-Identifier: MIT AND BSD-3-Clause
// QABBA source symbol statistics plus package-owned reversible symbol streams.
#include "internal.hpp"
#include <algorithm>
#include <bzlib.h>
#include <lzma.h>
#include <map>
#include <numeric>
#include <queue>
#include <zlib.h>
#include <zstd.h>
namespace abba_family {
namespace {
unsigned width(std::size_t n) {
  unsigned w = 1;
  while (n > 2) {
    ++w;
    n = (n + 1) / 2;
  }
  return w;
}
struct Bits {
  std::vector<std::uint8_t> bytes;
  std::size_t n = 0;
  void put(std::uint64_t x, unsigned w) {
    require(w <= 63, "bit width");
    for (unsigned k = w; k > 0; --k) {
      if (n % 8 == 0)
        bytes.push_back(0);
      bytes.back() |= std::uint8_t(((x >> (k - 1)) & 1) << (7 - n % 8));
      ++n;
    }
  }
};
struct Reader {
  const std::vector<std::uint8_t> &b;
  std::size_t n = 0, limit;
  std::uint64_t get(unsigned w) {
    require(w <= 63 && n <= limit && w <= limit - n, "truncated symbol stream");
    std::uint64_t v = 0;
    for (unsigned i = 0; i < w; ++i) {
      v = (v << 1) | ((b[n / 8] >> (7 - n % 8)) & 1);
      ++n;
    }
    return v;
  }
};
std::map<std::size_t, unsigned> lengths(const Ids &ids) {
  struct Node {
    std::size_t f, order, id;
    int l = -1, r = -1;
  };
  std::map<std::size_t, std::size_t> counts;
  Ids first;
  for (auto id : ids) {
    if (!counts.count(id))
      first.push_back(id);
    ++counts[id];
  }
  std::vector<Node> nodes;
  auto cmp = [&](int a, int b) {
    return nodes[a].f == nodes[b].f ? nodes[a].order > nodes[b].order
                                    : nodes[a].f > nodes[b].f;
  };
  std::priority_queue<int, std::vector<int>, decltype(cmp)> heap(cmp);
  for (auto id : first) {
    nodes.push_back({counts[id], nodes.size(), id});
    heap.push(int(nodes.size() - 1));
  }
  std::map<std::size_t, unsigned> out;
  if (heap.empty())
    return out;
  while (heap.size() > 1) {
    int a = heap.top();
    heap.pop();
    int b = heap.top();
    heap.pop();
    nodes.push_back({nodes[a].f + nodes[b].f, nodes.size(), 0, a, b});
    heap.push(int(nodes.size() - 1));
  }
  std::vector<std::pair<int, unsigned>> stack{{heap.top(), 0}};
  while (!stack.empty()) {
    auto [i, d] = stack.back();
    stack.pop_back();
    if (nodes[i].l < 0)
      out[nodes[i].id] = std::max(1U, d);
    else {
      stack.push_back({nodes[i].l, d + 1});
      stack.push_back({nodes[i].r, d + 1});
    }
  }
  return out;
}
Json length_json(const std::map<std::size_t, unsigned> &l) {
  Json j = Json::array();
  for (auto [id, n] : l)
    j.push_back(make_array(id, n));
  return j;
}
std::map<std::size_t, unsigned> parse_lengths(const Json &j, std::size_t k) {
  require(j.is_array() && j.size() <= k, "Huffman table size");
  std::map<std::size_t, unsigned> out;
  for (auto &row : j) {
    require(row.is_array() && row.size() == 2, "Huffman row");
    auto id = row[0].get<std::size_t>();
    require(row[1].is_number_integer(), "integer Huffman length");
    auto wide = row[1].get<std::uint64_t>();
    require(wide <= 63, "Huffman width range");
    auto w = unsigned(wide);
    require(id < k && w >= 1 && w <= 63 && out.emplace(id, w).second,
            "Huffman table");
  }
  return out;
}
using Codes = std::map<std::size_t, std::pair<std::uint64_t, unsigned>>;
Codes codes(const std::map<std::size_t, unsigned> &len) {
  std::vector<std::pair<unsigned, std::size_t>> order;
  for (auto [id, l] : len)
    order.push_back({l, id});
  std::sort(order.begin(), order.end());
  Codes out;
  std::uint64_t code = 0;
  unsigned prev = 0;
  for (auto [l, id] : order) {
    require(l <= 63 && l >= prev, "Huffman code length");
    code <<= l - prev;
    require(code < (1ULL << l), "oversubscribed Huffman");
    out[id] = {code, l};
    ++code;
    prev = l;
  }
  return out;
}
void put_code(Bits &b, const Codes &c, std::size_t id) {
  auto it = c.find(id);
  require(it != c.end(), "missing Huffman code");
  b.put(it->second.first, it->second.second);
}
struct Decoder {
  std::map<std::pair<unsigned, std::uint64_t>, std::size_t> table;
  unsigned max_width = 0;
  explicit Decoder(const Codes &c) {
    for (auto [id, code] : c) {
      table.emplace(std::make_pair(code.second, code.first), id);
      max_width = std::max(max_width, code.second);
    }
  }
  std::size_t get(Reader &r) const {
    std::uint64_t value = 0;
    for (unsigned w = 1; w <= max_width; ++w) {
      value = (value << 1) | r.get(1);
      auto it = table.find({w, value});
      if (it != table.end())
        return it->second;
    }
    throw std::invalid_argument("invalid Huffman code");
  }
};
std::pair<std::size_t, Ids> lzw_codes(const Ids &ids, std::size_t k) {
  std::map<Ids, std::size_t> dict;
  for (std::size_t i = 0; i < k; ++i)
    dict[{i}] = i;
  std::size_t next = k, total = 0, stored = k;
  Ids out;
  if (ids.empty())
    return {0, out};
  Ids w{ids[0]};
  for (std::size_t i = 1; i < ids.size(); ++i) {
    Ids wk = w;
    wk.push_back(ids[i]);
    if (dict.count(wk))
      w = std::move(wk);
    else {
      out.push_back(dict.at(w));
      total += width(next);
      require(wk.size() <= 4194304 - stored, "LZW dictionary memory limit");
      stored += wk.size();
      dict.emplace(std::move(wk), next++);
      w = {ids[i]};
    }
  }
  out.push_back(dict.at(w));
  total += width(next);
  return {total, out};
}
std::size_t modelbits(const std::map<std::size_t, unsigned> &l, std::size_t k) {
  unsigned max = 0;
  for (auto [id, n] : l) {
    (void)id;
    max = std::max(max, n);
  }
  return l.empty() ? 0 : k * width(max + 1);
}
Ids flatten(const Json &symbols, const Json &alphabet, std::vector<Ids> &seq) {
  bool single =
      symbols.is_string() || symbols.empty() || symbols[0].is_string();
  if (single)
    seq.push_back(symbol_ids(symbols, alphabet));
  else {
    require(symbols.is_array() && symbols.size() <= 4096,
            "symbol sequence shape");
    for (auto &row : symbols)
      seq.push_back(symbol_ids(row, alphabet));
  }
  Ids ids;
  for (auto &s : seq)
    ids.insert(ids.end(), s.begin(), s.end());
  require(ids.size() <= MAX_SAMPLES, "symbol limit");
  return ids;
}
} // namespace
std::vector<std::uint8_t> bytes_compress(const std::vector<std::uint8_t> &src,
                                         const std::string &codec) {
  require(src.size() <= MAX_FRAME, "byte input limit");
  std::vector<std::uint8_t> out;
  if (codec == "zlib" || codec == "gzip") {
    z_stream z{};
    require(deflateInit2(&z, 9, Z_DEFLATED, codec == "gzip" ? 31 : 15, 8,
                         Z_DEFAULT_STRATEGY) == Z_OK,
            "deflate init");
    struct EndDeflate {
      z_stream *stream;
      ~EndDeflate() { deflateEnd(stream); }
    } cleanup{&z};
    out.resize(deflateBound(&z, uLong(src.size())));
    z.next_in = const_cast<Bytef *>(src.data());
    z.avail_in = uInt(src.size());
    z.next_out = out.data();
    z.avail_out = uInt(out.size());
    int rc = deflate(&z, Z_FINISH);
    auto n = z.total_out;
    require(rc == Z_STREAM_END, "deflate failure");
    out.resize(n);
  } else if (codec == "bz2") {
    out.resize(src.size() + src.size() / 100 + 601);
    unsigned n = unsigned(out.size());
    int rc = BZ2_bzBuffToBuffCompress(
        reinterpret_cast<char *>(out.data()), &n,
        const_cast<char *>(reinterpret_cast<const char *>(src.data())),
        unsigned(src.size()), 9, 0, 30);
    require(rc == BZ_OK, "bz2 compression");
    out.resize(n);
  } else if (codec == "lzma") {
    out.resize(lzma_stream_buffer_bound(src.size()));
    std::size_t pos = 0;
    auto rc = lzma_easy_buffer_encode(9, LZMA_CHECK_CRC64, nullptr, src.data(),
                                      src.size(), out.data(), &pos, out.size());
    require(rc == LZMA_OK, "LZMA compression");
    out.resize(pos);
  } else if (codec == "zstd") {
    out.resize(ZSTD_compressBound(src.size()));
    auto n = ZSTD_compress(out.data(), out.size(), src.data(), src.size(), 19);
    require(!ZSTD_isError(n), "Zstd compression");
    out.resize(n);
  } else
    throw std::invalid_argument("unknown byte codec");
  return out;
}
std::vector<std::uint8_t> bytes_decompress(const std::vector<std::uint8_t> &src,
                                           const std::string &codec,
                                           std::size_t n) {
  require(n <= MAX_FRAME, "decoded byte limit");
  std::vector<std::uint8_t> out(n);
  if (codec == "zlib" || codec == "gzip") {
    z_stream z{};
    require(inflateInit2(&z, codec == "gzip" ? 31 : 15) == Z_OK,
            "inflate init");
    z.next_in = const_cast<Bytef *>(src.data());
    z.avail_in = uInt(src.size());
    z.next_out = out.data();
    z.avail_out = uInt(out.size());
    int rc = inflate(&z, Z_FINISH);
    auto used = z.total_in, got = z.total_out;
    inflateEnd(&z);
    require(rc == Z_STREAM_END && used == src.size() && got == n,
            "invalid deflate payload");
  } else if (codec == "bz2") {
    bz_stream z{};
    require(BZ2_bzDecompressInit(&z, 0, 0) == BZ_OK, "bz2 init");
    z.next_in = const_cast<char *>(reinterpret_cast<const char *>(src.data()));
    z.avail_in = unsigned(src.size());
    z.next_out = reinterpret_cast<char *>(out.data());
    z.avail_out = unsigned(n);
    int rc = BZ2_bzDecompress(&z);
    auto used = z.total_in_lo32, got = z.total_out_lo32;
    BZ2_bzDecompressEnd(&z);
    require(rc == BZ_STREAM_END && used == src.size() && got == n,
            "invalid bz2 payload");
  } else if (codec == "lzma") {
    std::uint64_t mem = 1ULL << 28;
    std::size_t inpos = 0, outpos = 0;
    auto rc = lzma_stream_buffer_decode(&mem, 0, nullptr, src.data(), &inpos,
                                        src.size(), out.data(), &outpos, n);
    require(rc == LZMA_OK && inpos == src.size() && outpos == n,
            "invalid LZMA payload");
  } else if (codec == "zstd") {
    auto rc = ZSTD_decompress(out.data(), n, src.data(), src.size());
    require(!ZSTD_isError(rc) && rc == n &&
                ZSTD_findFrameCompressedSize(src.data(), src.size()) ==
                    src.size(),
            "invalid Zstd payload");
  } else
    throw std::invalid_argument("unknown byte codec");
  return out;
}
Json symbol_stats(const Json &symbols, const Json &alph,
                  const std::string &codec, bool include) {
  std::vector<Ids> seq;
  Ids ids = flatten(symbols, alph, seq);
  std::size_t k = alph.size(), payload = 0, model = 0;
  if (!ids.empty()) {
    if (codec == "none")
      payload = ids.size() * (k <= 256 ? 8 : width(k));
    else if (codec == "fixed")
      payload = ids.size() * width(k);
    else if (codec == "huffman") {
      auto l = lengths(ids);
      for (auto i : ids)
        payload += l.at(i);
      model = include ? modelbits(l, k) : 0;
    } else if (codec == "huffman1") {
      std::map<std::size_t, Ids> contexts;
      for (auto &s : seq) {
        if (!s.empty())
          payload += width(k);
        for (std::size_t i = 1; i < s.size(); ++i)
          contexts[s[i - 1]].push_back(s[i]);
      }
      for (auto &[context, v] : contexts) {
        (void)context;
        auto l = lengths(v);
        for (auto i : v)
          payload += l.at(i);
        if (include)
          model += width(k) + modelbits(l, k);
      }
    } else if (codec == "lzw")
      payload = lzw_codes(ids, k).first;
    else {
      std::vector<std::uint8_t> raw;
      unsigned n = k <= 256 ? 1 : (k <= 65536 ? 2 : 4);
      for (auto id : ids)
        for (unsigned b = 0; b < n; ++b)
          raw.push_back(std::uint8_t(id >> (b * 8)));
      payload = bytes_compress(raw, codec).size() * 8;
    }
  }
  return [&]() {
    Json result_object = Json::object();
    result_object["codec"] = codec;
    result_object["n_symbols"] = ids.size();
    result_object["alphabet_size"] = k;
    result_object["payload_bits"] = payload;
    result_object["model_bits"] = model;
    result_object["total_bits"] = payload + model;
    result_object["bits_per_symbol"] =
        ids.empty() ? 0. : double(payload + model) / double(ids.size());
    return result_object;
  }();
}
std::vector<std::uint8_t> symbol_pack(const Ids &ids, std::size_t k,
                                      const std::string &codec, Json &meta) {
  Bits b;
  meta = Json::object();
  if (codec == "none" || codec == "fixed") {
    unsigned w = codec == "none" && k <= 256 ? 8 : width(k);
    for (auto i : ids)
      b.put(i, w);
  } else if (codec == "huffman" || codec == "huffman1") {
    if (codec == "huffman") {
      auto l = lengths(ids);
      meta["lengths"] = length_json(l);
      auto c = codes(l);
      for (auto i : ids)
        put_code(b, c, i);
    } else {
      std::map<std::size_t, Ids> contexts;
      for (std::size_t i = 1; i < ids.size(); ++i)
        contexts[ids[i - 1]].push_back(ids[i]);
      std::map<std::size_t, Codes> books;
      meta["contexts"] = Json::array();
      for (auto &[context, v] : contexts) {
        auto l = lengths(v);
        books[context] = codes(l);
        meta["contexts"].push_back(make_array(context, length_json(l)));
      }
      if (!ids.empty())
        b.put(ids[0], width(k));
      for (std::size_t i = 1; i < ids.size(); ++i)
        put_code(b, books.at(ids[i - 1]), ids[i]);
    }
  } else if (codec == "lzw") {
    auto [bits, c] = lzw_codes(ids, k);
    (void)bits;
    for (std::size_t i = 0; i < c.size(); ++i)
      b.put(c[i], width(k + i));
  } else {
    std::vector<std::uint8_t> raw;
    unsigned n = k <= 256 ? 1 : 2;
    for (auto id : ids)
      for (unsigned i = 0; i < n; ++i)
        raw.push_back(std::uint8_t(id >> (8 * i)));
    meta["raw_bytes"] = raw.size();
    return bytes_compress(raw, codec);
  }
  meta["bits"] = b.n;
  return b.bytes;
}
Ids symbol_unpack(const std::vector<std::uint8_t> &bytes, std::size_t n,
                  std::size_t k, const std::string &codec, const Json &meta) {
  require(n <= MAX_SAMPLES && k > 0 && k <= MAX_CENTERS,
          "symbol decode limits");
  Ids ids;
  if (codec != "none" && codec != "fixed" && codec != "huffman" &&
      codec != "huffman1" && codec != "lzw") {
    unsigned w = k <= 256 ? 1 : 2;
    require(meta.at("raw_bytes") == n * w, "byte symbol size");
    auto raw = bytes_decompress(bytes, codec, n * w);
    for (std::size_t i = 0; i < n; ++i) {
      std::size_t id = 0;
      for (unsigned j = 0; j < w; ++j)
        id |= std::size_t(raw[i * w + j]) << (j * 8);
      ids.push_back(id);
    }
  } else {
    std::size_t bits = meta.at("bits");
    require(bits <= bytes.size() * 8 && bytes.size() == (bits + 7) / 8,
            "symbol bit size");
    Reader r{bytes, 0, bits};
    if (bits % 8)
      require((bytes.back() & ((1U << (8 - bits % 8)) - 1)) == 0,
              "nonzero symbol padding");
    if (codec == "none" || codec == "fixed") {
      unsigned w = codec == "none" && k <= 256 ? 8 : width(k);
      for (std::size_t i = 0; i < n; ++i)
        ids.push_back(std::size_t(r.get(w)));
    } else if (codec == "huffman") {
      Decoder c(codes(parse_lengths(meta.at("lengths"), k)));
      for (std::size_t i = 0; i < n; ++i)
        ids.push_back(c.get(r));
    } else if (codec == "huffman1") {
      std::map<std::size_t, Decoder> books;
      require(meta.at("contexts").size() <= k, "context count");
      std::size_t table_entries = 0;
      for (auto &row : meta.at("contexts")) {
        require(row.is_array() && row.size() == 2, "context shape");
        table_entries += row[1].size();
        require(table_entries <= MAX_SAMPLES, "context table memory limit");
        auto context = row[0].get<std::size_t>();
        require(
            context < k &&
                books.emplace(context, Decoder(codes(parse_lengths(row[1], k))))
                    .second,
            "context table");
      }
      if (n)
        ids.push_back(std::size_t(r.get(width(k))));
      for (std::size_t i = 1; i < n; ++i) {
        auto it = books.find(ids.back());
        require(it != books.end(), "unknown context");
        ids.push_back(it->second.get(r));
      }
    } else {
      std::size_t stored = k;
      std::vector<Ids> dict;
      for (std::size_t i = 0; i < k; ++i)
        dict.push_back({i});
      if (n) {
        auto first = std::size_t(r.get(width(k)));
        require(first < k, "invalid LZW first");
        Ids prev{first};
        ids = prev;
        while (ids.size() < n) {
          auto code = std::size_t(r.get(width(dict.size() + 1)));
          Ids entry;
          if (code < dict.size())
            entry = dict[code];
          else {
            require(code == dict.size(), "invalid LZW code");
            entry = prev;
            entry.push_back(prev[0]);
          }
          require(entry.size() <= n - ids.size(), "LZW decoded count");
          ids.insert(ids.end(), entry.begin(), entry.end());
          prev.push_back(entry[0]);
          require(dict.size() <= MAX_SAMPLES + MAX_CENTERS,
                  "LZW dictionary limit");
          require(prev.size() <= 4194304 - stored,
                  "LZW dictionary memory limit");
          stored += prev.size();
          dict.push_back(prev);
          prev = std::move(entry);
        }
      }
    }
    require(r.n == bits, "trailing symbol bits");
  }
  for (auto i : ids)
    require(i < k, "symbol outside alphabet");
  return ids;
}
} // namespace abba_family

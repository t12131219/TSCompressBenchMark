// SPDX-License-Identifier: MIT
#include "abba_family.hpp"
#include "abba_family_c.h"
#include "internal.hpp"
#include <atomic>
#include <cstdlib>
#include <cstring>
#include <future>
#include <iostream>
#include <new>
#include <random>
#include <sys/mman.h>
#include <unistd.h>
#include <zlib.h>
using namespace abba_family;
namespace {
thread_local long fail_after = -1;
std::atomic<long> live_new{0};
std::size_t checks = 0;
void check(bool x, const char *message) {
  ++checks;
  if (!x)
    throw std::runtime_error(message);
}
void reject(const std::function<void()> &f) {
  bool bad = false;
  try {
    f();
  } catch (const std::exception &) {
    bad = true;
  }
  check(bad, "expected rejection");
}
Json request(std::string a = "fabba") {
  Json r{
      {"algorithm", a}, {"values", Json::array()}, {"config", Json::object()}};
  for (int i = 0; i < 65; ++i)
    r["values"].push_back(std::sin(i * .4) + i * .01);
  if (a == "abba")
    r["config"]["min_k"] = 1;
  return r;
}
void set32(std::vector<uint8_t> &b, std::size_t at, std::uint32_t x) {
  for (unsigned i = 0; i < 4; ++i)
    b[at + i] = uint8_t(x >> (8 * i));
}
void crc(std::vector<uint8_t> &b) {
  set32(b, b.size() - 4, crc32(0, b.data(), uInt(b.size() - 4)));
}
void abi(const Json &r) {
  auto text = r.dump();
  auto unchanged = text;
  std::size_t n = 99, need = 99;
  check(af_execute_v1(text.data(), text.size(), nullptr, 0, &n, &need) ==
                AF_CAPACITY &&
            n == 0 && need > 0,
        "size query");
  auto exact = need;
  std::vector<char> out(need + 2, '#');
  check(af_execute_v1(text.data(), text.size(), out.data() + 1, need - 1, &n,
                      &need) == AF_CAPACITY &&
            n == 0 && need == exact,
        "short capacity");
  for (auto c : out)
    check(c == '#', "short output modified");
  check(af_execute_v1(text.data(), text.size(), out.data() + 1, exact, &n,
                      &need) == AF_OK &&
            n == exact,
        "exact capacity");
  check(out.front() == '#' && out.back() == '#', "canary");
  check(Json::parse(out.begin() + 1, out.end() - 1) == execute(r),
        "ABI result");
  check(text == unchanged, "input immutability");
  auto page = std::size_t(sysconf(_SC_PAGESIZE));
  auto input_pages = (text.size() + page - 1) / page * page;
  auto output_pages = (exact + page - 1) / page * page;
  void *ip = mmap(nullptr, input_pages + page, PROT_READ | PROT_WRITE,
                  MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
  void *op = mmap(nullptr, output_pages + page, PROT_READ | PROT_WRITE,
                  MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
  check(ip != MAP_FAILED && op != MAP_FAILED, "guard page allocation");
  auto input_tail = static_cast<char *>(ip) + input_pages - text.size();
  auto output_tail = static_cast<char *>(op) + output_pages - exact;
  std::memcpy(input_tail, text.data(), text.size());
  check(mprotect(ip, input_pages, PROT_READ) == 0 &&
            mprotect(static_cast<char *>(ip) + input_pages, page, PROT_NONE) ==
                0 &&
            mprotect(static_cast<char *>(op) + output_pages, page, PROT_NONE) ==
                0,
        "guard page protection");
  check(af_execute_v1(input_tail, text.size(), output_tail, exact, &n, &need) ==
            AF_OK,
        "zero overread and overwrite at guard page");
  munmap(ip, input_pages + page);
  munmap(op, output_pages + page);

  std::vector<char> overlap(std::max(text.size() + 1, exact + 1) + 1, '#');
  std::memcpy(overlap.data() + 1, text.data(), text.size());
  check(af_execute_v1(overlap.data() + 1, text.size(), overlap.data() + 1,
                      exact, &n, &need) == AF_OK,
        "input-output overlap");
  check(Json::parse(overlap.data() + 1, overlap.data() + 1 + n) == execute(r),
        "overlap result");
  check(af_execute_v1(nullptr, 0, out.data(), out.size(), &n, &need) ==
                AF_INVALID &&
            n == 0 && need == 0,
        "null input");
  check(af_execute_v1(text.data(), text.size(), nullptr, 1, &n, &need) ==
            AF_INVALID,
        "null output");
  check(af_execute_v1(text.data(), text.size(), out.data(), out.size(), nullptr,
                      &need) == AF_INVALID,
        "null count");
  std::string deep(65, '[');
  deep += "0";
  deep += std::string(65, ']');
  auto saved = out;
  check(af_execute_v1(deep.data(), deep.size(), out.data(), out.size(), &n,
                      &need) == AF_INVALID &&
            out == saved,
        "depth limit atomic");
}
} // namespace
void *operator new(std::size_t n) {
  if (fail_after == 0)
    throw std::bad_alloc();
  if (fail_after > 0)
    --fail_after;
  if (void *p = std::malloc(n ? n : 1)) {
    ++live_new;
    return p;
  }
  throw std::bad_alloc();
}
void *operator new[](std::size_t n) { return ::operator new(n); }
void operator delete(void *p) noexcept {
  if (p)
    --live_new;
  std::free(p);
}
void operator delete[](void *p) noexcept {
  if (p)
    --live_new;
  std::free(p);
}
void operator delete(void *p, std::size_t) noexcept {
  if (p)
    --live_new;
  std::free(p);
}
void operator delete[](void *p, std::size_t) noexcept {
  if (p)
    --live_new;
  std::free(p);
}
int main(int argc, char **argv) {
  try {
    unsigned fuzz = argc > 1 ? unsigned(std::stoul(argv[1])) : 2000;
    check(af_api_version_v1() == 1, "ABI version");
    for (auto a : {"abba", "fabba", "qabba"}) {
      auto r = request(a);
      abi(r);
      auto baseline = execute(r);
      for (int i = 0; i < 3; ++i)
        check(execute(r) == baseline, "repeat determinism");
      for (auto codec : {"none", "fixed", "huffman", "huffman1", "lzw", "zlib",
                         "gzip", "bz2", "lzma", "zstd"}) {
        auto q = r;
        if (a == std::string("qabba"))
          q["config"]["symbol_codec"] = codec;
        else if (std::string(codec) != "none")
          continue;
        auto frame = encode(q);
        auto d = decode(frame.data(), frame.size());
        check(d["reconstructed"] == baseline["reconstructed"],
              "independent frame reconstruction");
        check(d["final_bits"] == frame.size() * 8 &&
                  d["external_side_information_bits"] == 0,
              "FinalBits");
        for (std::size_t n = 0; n < frame.size(); ++n)
          reject([&] { decode(frame.data(), n); });
        auto trailing = frame;
        trailing.push_back(0);
        reject([&] { decode(trailing.data(), trailing.size()); });
      }
      for (auto vals : {Json::array(), Json::array({1}), Json::array({1, 2}),
                        Json::array({1, 1, 1})}) {
        auto q = r;
        q["values"] = vals;
        if (vals.size() < 2)
          reject([&] { execute(q); });
        else
          execute(q);
      }
    }
    auto r = request("qabba");
    r["values"] = Json::array({r["values"], r["values"], r["values"]});
    r["config"]["n_jobs"] = 3;
    auto expected = execute(r);
    std::vector<std::future<void>> threads;
    for (int i = 0; i < 8; ++i)
      threads.push_back(std::async(std::launch::async, [&] {
        for (int j = 0; j < 10; ++j) {
          if (execute(r) != expected)
            throw std::runtime_error("batch concurrency");
          auto a = request("abba");
          auto b = execute(a);
          if (b != execute(a))
            throw std::runtime_error("CKmeans concurrency");
        }
      }));
    for (auto &t : threads)
      t.get();
    check(true, "threaded results");
    // Fault injection at every reached C++ allocation. No caller output
    // changes.
    std::vector<Json> fault_requests;
    for (auto alg : {"abba", "fabba", "qabba"}) {
      auto q = request(alg);
      q["values"] = Json::array({0., 1., 3., 1., -2., 4., 1., 7.});
      fault_requests.push_back(q);
    }
    auto image = fault_requests[1];
    image["operation"] = "image_fit";
    image["values"] =
        Json::array({Json::array({1, 2, 3, 4}), Json::array({6, 9, 1, 7})});
    fault_requests.push_back(image);
    for (auto codec : {"none", "fixed", "huffman", "huffman1", "lzw", "zlib",
                       "gzip", "bz2", "lzma", "zstd"}) {
      auto q = fault_requests[2];
      q["operation"] = "encode";
      q["config"]["symbol_codec"] = codec;
      fault_requests.push_back(q);
      auto frame = encode(q);
      Json d = Json::object();
      d["operation"] = "decode";
      d["container_hex"] = hex(frame);
      fault_requests.push_back(d);
    }
    std::size_t oom = 0;
    for (const auto &fault_request : fault_requests) {
      auto text = fault_request.dump();
      std::vector<char> output(65536, '@'), saved = output;
      bool completed = false;
      for (long fault = 0; fault < 20000; ++fault) {
        std::size_t n = 1, need = 1;
        auto before = live_new.load();
        fail_after = fault;
        int status = af_execute_v1(text.data(), text.size(), output.data(),
                                   output.size(), &n, &need);
        fail_after = -1;
        if (status != AF_OK && live_new.load() != before) {
          std::cerr << "allocation leak at fault " << fault << " operation "
                    << fault_request.value("operation", "fit") << " delta "
                    << live_new.load() - before << "\n";
          return 1;
        }
        if (status == AF_OK) {
          completed = true;
          break;
        }
        check(status == AF_NOMEM && n == 0 && need == 0 && output == saved,
              "allocation failure atomicity");
        ++oom;
      }
      check(completed, "allocation fault coverage");
    }
    std::mt19937 rng(20261020);
    auto base = encode(request());
    std::size_t rejected = 0, accepted = 0;
    for (unsigned i = 0; i < fuzz; ++i) {
      auto b = base;
      for (unsigned m = 0; m < 1 + rng() % 4; ++m)
        b[rng() % b.size()] ^= uint8_t(1 + rng() % 255);
      if (i % 2 == 0)
        crc(b);
      try {
        decode(b.data(), b.size());
        ++accepted;
      } catch (const std::exception &) {
        ++rejected;
      }
    }
    for (auto key : {"version", "algorithm", "centers", "alphabet", "starts",
                     "single", "config"})
      for (auto value :
           {Json(), Json(-1), Json::array(), Json::object(), Json("bad")}) {
        auto m = execute(request())["model"];
        m[key] = value;
        try {
          execute(Json{{"operation", "inverse"}, {"model", m}});
        } catch (const std::exception &) {
          ++rejected;
        }
      }
    for (auto a : {"abba", "fabba", "qabba"}) {
      auto q = request(a);
      q["config"]["bogus"] = true;
      reject([&] { execute(q); });
      q = request(a);
      q["values"][0] = 1e308;
      q["values"][1] = -1e308;
      reject([&] { execute(q); });
    }
    for (int bit = 1; bit <= 64; ++bit) {
      auto q = quantizer({-1., 0., 1.}, bit);
      check(q["bits"] == bit, "quantizer width");
      auto d = dequantize(q);
      check(d.size() == 3, "quantizer inverse");
    }
    std::cout << Json{{"status", "PASS"},
                      {"checks", checks},
                      {"oom_sites", oom},
                      {"oom_request_profiles", fault_requests.size()},
                      {"fuzz_mutations", fuzz},
                      {"fuzz_rejected", rejected},
                      {"fuzz_accepted_valid", accepted}}
                     .dump()
              << '\n';
    return 0;
  } catch (const std::exception &e) {
    fail_after = -1;
    std::cerr << "FAIL: " << e.what() << '\n';
    return 1;
  }
}

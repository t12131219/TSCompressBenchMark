#pragma once
#include <cstddef>
#include <cstdint>
struct RwConfig {
  std::uint64_t rows, columns;
  std::uint32_t a, b, c, d, seed, mode;
  double x, y, z;
  const char* model;
};
extern "C" {
std::uint32_t rw_version();
const char* rw_algorithm();
int rw_model_alphabet(const char*, std::uint32_t*, char*, std::size_t);
int rw_bound(const RwConfig*, const std::uint8_t*, std::size_t, std::size_t*, char*, std::size_t);
int rw_encode(const RwConfig*, const std::uint8_t*, std::size_t, std::uint8_t*, std::size_t, std::size_t*, char*, std::size_t);
int rw_decode(const std::uint8_t*, std::size_t, std::uint8_t*, std::size_t, std::size_t*, char*, std::size_t);
}

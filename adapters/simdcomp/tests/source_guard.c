/* Independent scalar wire, public API and protected-page checks for SIMDComp.
 * This program does not use an upstream unpacker to predict packed bytes. */
#define _GNU_SOURCE
#include "simdcomp.h"
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

typedef struct {
  unsigned char *mapping, *accessible, *bytes;
  size_t mapping_size, accessible_size, size, gap;
} Guard;

static const size_t lengths[] = {0, 1, 2, 3, 4, 7, 8, 15, 16, 17, 31, 32,
  33, 63, 64, 65, 127, 128, 129, 255, 256, 257, 511, 512, 513, 1023, 1024, 1025};
static const uint32_t seeds[] = {0, 1, 0x80000000U, 0xffffffffU};
static unsigned width_now;
static size_t count_now, cases, calls;
static const char *mode_now;

static void need(int condition, const char *reason) {
  if (!condition) {
    fprintf(stderr, "FAIL mode=%s width=%u count=%zu: %s\n",
            mode_now, width_now, count_now, reason);
    exit(1);
  }
}

static Guard make_guard(size_t bytes, size_t gap) {
  Guard g;
  size_t page = (size_t)sysconf(_SC_PAGESIZE);
  g.accessible_size = ((bytes + gap + 64 + page - 1) / page) * page;
  g.mapping_size = g.accessible_size + 2 * page;
  g.mapping = mmap(NULL, g.mapping_size, PROT_NONE,
                   MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
  need(g.mapping != MAP_FAILED, "mmap failed");
  g.accessible = g.mapping + page;
  need(mprotect(g.accessible, g.accessible_size, PROT_READ | PROT_WRITE) == 0,
       "mprotect writable failed");
  memset(g.accessible, 0xa5, g.accessible_size);
  g.bytes = g.accessible + g.accessible_size - bytes - gap;
  g.size = bytes;
  g.gap = gap;
  return g;
}

static void readonly(Guard *g) {
  need(mprotect(g->accessible, g->accessible_size, PROT_READ) == 0,
       "mprotect readonly failed");
}

static void check_canary(const Guard *g) {
  size_t i;
  for (i = 1; i <= 64; ++i)
    need(g->bytes[-(ptrdiff_t)i] == 0xa5, "prefix canary changed");
  for (i = 0; i < g->gap; ++i)
    need(g->bytes[g->size + i] == 0xa5, "suffix canary changed");
}

static void free_guard(Guard *g) {
  check_canary(g);
  need(munmap(g->mapping, g->mapping_size) == 0, "munmap failed");
}

static uint32_t mask(unsigned b) {
  return b == 32 ? UINT32_MAX : (uint32_t)((UINT64_C(1) << b) - 1);
}

static unsigned scalar_bits(uint32_t x) {
  unsigned b = 0;
  while (x) { ++b; x >>= 1; }
  return b;
}

static uint32_t random32(uint32_t *state) {
  *state ^= *state << 13;
  *state ^= *state >> 17;
  *state ^= *state << 5;
  return *state;
}

static size_t wire_size(size_t n, unsigned b, unsigned lanes) {
  if (b == 0) return 0;
  if (b == 32) return 4 * n;
  return ((n + lanes - 1) / lanes * b + 31) / 32 * lanes * 4;
}

static void scalar_wire(const uint32_t *values, size_t n, unsigned b,
                        unsigned lanes, unsigned char *wire) {
  size_t i;
  memset(wire, 0, wire_size(n, b, lanes));
  for (i = 0; i < n; ++i) {
    unsigned k;
    for (k = 0; k < b; ++k) {
      size_t word = ((i / lanes * b + k) / 32) * lanes + i % lanes;
      unsigned bit = (unsigned)((i / lanes * b + k) % 32);
      if ((values[i] >> k) & 1U)
        wire[4 * word + bit / 8] |= (unsigned char)(1U << (bit % 8));
    }
  }
}

static void fill(uint32_t *input, uint32_t *residual, size_t n,
                 unsigned b, uint32_t seed, int kind, int pattern) {
  size_t i;
  uint32_t state = 0x9e3779b9U ^ seed ^ (uint32_t)n ^ b;
  uint32_t previous = seed;
  for (i = 0; i < n; ++i) {
    uint32_t x = pattern == 0 ? 0 : pattern == 1 ? mask(b)
                   : random32(&state) & mask(b);
    residual[i] = x;
    input[i] = kind == 0 ? x : kind == 1 ? previous + x : seed + x;
    previous = input[i];
  }
}

static void utility_checks(const uint32_t *input, size_t n, uint32_t seed) {
  uint32_t combined = 0, delta = 0, previous = seed;
  uint32_t low = UINT32_MAX, high = 0, got_low, got_high;
  size_t i;
  for (i = 0; i < n; ++i) {
    combined |= input[i];
    delta |= input[i] - previous;
    previous = input[i];
    if (input[i] < low) low = input[i];
    if (input[i] > high) high = input[i];
  }
  need(maxbits_length(input, (uint32_t)n) == scalar_bits(combined), "maxbits_length");
  need(simdmin_length(input, (uint32_t)n) == low, "simdmin_length");
  simdmaxmin_length(input, (uint32_t)n, &got_low, &got_high);
  need(got_low == low && got_high == high, "simdmaxmin_length");
  if (n) need(simdmaxbitsd1_length(seed, input, (uint32_t)n) == scalar_bits(delta),
              "simdmaxbitsd1_length"); /* original API explicitly requires N>0 */
  if (n == 128) {
    need(maxbits(input) == scalar_bits(combined), "maxbits");
    need(simdmin(input) == low, "simdmin");
    simdmaxmin(input, &got_low, &got_high);
    need(got_low == low && got_high == high, "simdmaxmin");
    need(simdmaxbitsd1(seed, input) == scalar_bits(delta), "simdmaxbitsd1");
  }
}

static void codecs(int kind) {
  unsigned b;
  size_t l, s;
  for (b = 0; b <= 32; ++b) for (l = 0; l < sizeof(lengths)/sizeof(lengths[0]); ++l)
    for (s = 0; s < sizeof(seeds)/sizeof(seeds[0]); ++s) {
      size_t n = lengths[l], bytes = wire_size(n, b, 4), i;
      int pattern;
      if (kind == 1 && n != 128) continue; /* D1 pack/unpack API is full-block only. */
      width_now = b; count_now = n;
      for (pattern = 0; pattern < 3; ++pattern) {
        uint32_t residual[1025], expected[1025];
        unsigned char wire[4100];
        Guard input = make_guard(n * 4, 0), output = make_guard(bytes, 0);
        Guard restored = make_guard(n * 4, 0);
        uint32_t *values = (uint32_t *)input.bytes;
        const __m128i *end;
        fill(values, residual, n, b, seeds[s], kind, pattern);
        memcpy(expected, values, n * 4);
        /* Original D1/FOR width=32 stores absolute values, not residuals. */
        scalar_wire(b == 32 && kind ? values : residual, n, b, 4, wire);
        readonly(&input);
        utility_checks(values, n, seeds[s]);
        if (kind == 0) {
          need(simdpack_compressedbytes((int)n, b) == (int)bytes, "plain compressedbytes");
          end = simdpack_length(values, n, (__m128i *)output.bytes, b);
        } else if (kind == 1) {
          simdpackd1(seeds[s], values, (__m128i *)output.bytes, b);
          end = (const __m128i *)(output.bytes + bytes);
        } else {
          need(simdpackFOR_compressedbytes((int)n, b) == (int)bytes, "FOR compressedbytes");
          end = simdpackFOR_length(seeds[s], values, (int)n, (__m128i *)output.bytes, b);
        }
        need((const unsigned char *)end == output.bytes + bytes, "pack returned byte length");
        need(memcmp(output.bytes, wire, bytes) == 0, "independent scalar wire mismatch");
        readonly(&output);
        if (kind == 0)
          end = simdunpack_length((const __m128i *)output.bytes, n, (uint32_t *)restored.bytes, b);
        else if (kind == 1) {
          simdunpackd1(seeds[s], (const __m128i *)output.bytes, (uint32_t *)restored.bytes, b);
          end = (const __m128i *)(output.bytes + bytes);
        } else
          end = simdunpackFOR_length(seeds[s], (const __m128i *)output.bytes, (int)n, (uint32_t *)restored.bytes, b);
        need((const unsigned char *)end == output.bytes + bytes, "unpack returned byte length");
        need(memcmp(restored.bytes, expected, n * 4) == 0, "round trip mismatch");
        /* Exercise independent full-block and shortlength entry points too. */
        if (kind == 0 && n < 128) {
          Guard shortwire = make_guard(bytes, 0);
          end = simdpack_shortlength(values, (int)n, (__m128i *)shortwire.bytes, b);
          need((const unsigned char *)end == shortwire.bytes + bytes, "short pack pointer");
          need(memcmp(shortwire.bytes, wire, bytes) == 0, "short wire differs");
          readonly(&shortwire);
          end = simdunpack_shortlength((const __m128i *)shortwire.bytes, (int)n,
                                      (uint32_t *)restored.bytes, b);
          need((const unsigned char *)end == shortwire.bytes + bytes, "short unpack pointer");
          need(memcmp(restored.bytes, expected, n * 4) == 0, "short roundtrip");
          free_guard(&shortwire);
        }
        if (n == 128) {
          Guard fullwire = make_guard(bytes, 0);
          if (kind == 0) simdpack(values, (__m128i *)fullwire.bytes, b);
          else if (kind == 1) simdpackwithoutmaskd1(seeds[s], values, (__m128i *)fullwire.bytes, b);
          else simdpackFOR(seeds[s], values, (__m128i *)fullwire.bytes, b);
          need(memcmp(fullwire.bytes, wire, bytes) == 0, "full kernel wire differs");
          if (kind == 0) {
            simdpackwithoutmask(values, (__m128i *)fullwire.bytes, b);
            need(memcmp(fullwire.bytes, wire, bytes) == 0, "withoutmask wire differs");
          }
          readonly(&fullwire);
          if (kind == 0) simdunpack((const __m128i *)fullwire.bytes, (uint32_t *)restored.bytes, b);
          else if (kind == 1) simdunpackd1(seeds[s], (const __m128i *)fullwire.bytes, (uint32_t *)restored.bytes, b);
          else simdunpackFOR(seeds[s], (const __m128i *)fullwire.bytes, (uint32_t *)restored.bytes, b);
          need(memcmp(restored.bytes, expected, n * 4) == 0, "full kernel roundtrip");
          if (kind == 1) {
            __m128i state = _mm_set1_epi32(seeds[s]);
            uint32_t last[4];
            simdscand1(&state, (const __m128i *)fullwire.bytes, b);
            _mm_storeu_si128((__m128i *)last, state);
            for (i = 0; i < 4; ++i) need(last[i] == expected[124+i], "D1 scan state");
          }
          free_guard(&fullwire);
        }
        need(memcmp(values, expected, n * 4) == 0, "source changed");
        free_guard(&restored); free_guard(&output); free_guard(&input);
        ++cases;
      }
    }
}

static void queries(int kind) {
  unsigned b;
  for (b = 0; b <= 32; ++b) {
    uint32_t values[128], residual[128], previous = 0;
    unsigned char wire[512];
    size_t bytes = wire_size(128, b, 4), i, l;
    Guard packed = make_guard(bytes, 0);
    width_now = b; count_now = 128;
    for (i = 0; i < 128; ++i) {
      values[i] = (uint32_t)((uint64_t)mask(b) * i / 127);
      residual[i] = kind == 1 ? values[i] - previous : values[i];
      previous = values[i];
    }
    scalar_wire(b == 32 ? values : residual, 128, b, 4, wire);
    memcpy(packed.bytes, wire, bytes); readonly(&packed);
    for (i = 0; i < 128; ++i) {
      uint32_t selected = kind == 1 ? simdselectd1(0, (const __m128i *)packed.bytes, b, (int)i)
        : simdselectFOR(0, (const __m128i *)packed.bytes, b, (int)i);
      need(selected == values[i], "select value"); ++calls;
    }
    for (l = 0; l < sizeof(lengths)/sizeof(lengths[0]); ++l) {
      size_t n = lengths[l];
      if (n > 128) continue;
      count_now = n;
      for (i = 0; i < 130; ++i) {
        uint32_t keys[] = { i < 128 ? values[i] : 0, i < 128 ? values[i] + 1 : UINT32_MAX,
                           i < 128 ? values[i] - 1 : 0x80000000U };
        unsigned k;
        for (k = 0; k < 3; ++k) {
          size_t expected = 0;
          uint32_t result = 0xdeadbeefU;
          int found;
          while (expected < n && values[expected] < keys[k]) ++expected;
          found = kind == 1 ? simdsearchwithlengthd1(0, (const __m128i *)packed.bytes,
                   b, (int)n, keys[k], &result)
               : simdsearchwithlengthFOR(0, (const __m128i *)packed.bytes,
                   b, (int)n, keys[k], &result);
          need(found == (int)expected, "search lower bound position");
          if (expected < n) need(result == values[expected], "search lower bound value");
          ++calls;
          if (kind == 1 && n == 128) {
            __m128i state = _mm_setzero_si128();
            found = simdsearchd1(&state, (const __m128i *)packed.bytes, b, keys[k], &result);
            need(found == (int)expected, "full search lower bound position");
            if (expected < n) need(result == values[expected], "full search value");
            ++calls;
          }
        }
      }
      ++cases;
    }
    need(memcmp(packed.bytes, wire, bytes) == 0, "query modified input");
    free_guard(&packed);
  }
}

static void mutations(int kind) {
  unsigned b;
  for (b = 0; b <= 32; ++b) {
    size_t index;
    width_now = b; count_now = 128;
    for (index = 0; index < 128; ++index) {
      uint32_t values[128], residual[128], expected[128], decoded[128];
      unsigned char wire[512], predicted[512];
      uint32_t seed = 0x12345678U, old, replacement, previous;
      size_t bytes = wire_size(128, b, 4), i;
      Guard packed = make_guard(bytes, 0);
      fill(values, residual, 128, b, seed, kind, 2);
      scalar_wire(b == 32 && kind ? values : residual, 128, b, 4, wire);
      memcpy(packed.bytes, wire, bytes);
      memcpy(expected, values, sizeof(values));
      old = residual[index]; replacement = mask(b) ^ old;
      previous = index ? values[index-1] : seed;
      if (kind == 0) expected[index] = replacement;
      else if (kind == 2) expected[index] = seed + replacement;
      else for (i = index; i < 128; ++i) expected[i] += replacement - old;
      if (kind == 0) simdfastset((__m128i *)packed.bytes, b, expected[index], index);
      else if (kind == 2) simdfastsetFOR(seed, (__m128i *)packed.bytes, b, expected[index], index);
      else simdfastsetd1fromprevious((__m128i *)packed.bytes, b, previous, expected[index], index);
      previous = seed;
      for (i = 0; i < 128; ++i) {
        residual[i] = kind == 0 ? expected[i] : kind == 2 ? expected[i] - seed : expected[i] - previous;
        previous = expected[i];
      }
      scalar_wire(b == 32 && kind ? expected : residual, 128, b, 4, predicted);
      need(memcmp(packed.bytes, predicted, bytes) == 0, "mutation scalar wire differs");
      if (kind == 0) simdunpack((const __m128i *)packed.bytes, decoded, b);
      else if (kind == 2) simdunpackFOR(seed, (const __m128i *)packed.bytes, decoded, b);
      else {
        simdunpackd1(seed, (const __m128i *)packed.bytes, decoded, b);
        /* The second mutation entry point must produce the same bytes. */
        memcpy(packed.bytes, wire, bytes);
        simdfastsetd1(seed, (__m128i *)packed.bytes, b, expected[index], index);
        need(memcmp(packed.bytes, predicted, bytes) == 0, "computed-previous mutation differs");
      }
      need(memcmp(decoded, expected, sizeof(expected)) == 0, "mutation decoded values");
      free_guard(&packed); ++cases;
    }
  }
}

int main(int argc, char **argv) {
  need(argc == 2, "one mode argument required");
  mode_now = argv[1];
  if (!strcmp(mode_now, "plain")) codecs(0);
  else if (!strcmp(mode_now, "d1")) codecs(1);
  else if (!strcmp(mode_now, "for")) codecs(2);
  else if (!strcmp(mode_now, "query-d1")) queries(1);
  else if (!strcmp(mode_now, "query-for")) queries(2);
  else if (!strcmp(mode_now, "set-plain")) mutations(0);
  else if (!strcmp(mode_now, "set-d1")) mutations(1);
  else if (!strcmp(mode_now, "set-for")) mutations(2);
  else need(0, "unknown mode");
  printf("SIMDComp source %s cases PASS: %zu; query calls: %zu; exact guard pages; scalar wire\n",
         mode_now, cases, calls);
  return 0;
}

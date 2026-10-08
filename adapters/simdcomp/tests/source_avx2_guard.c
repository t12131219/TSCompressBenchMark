/* Reuse the already audited guard/oracle utilities without changing SSE evidence. */
#define main sse_source_qualification_main
#include "source_guard.c"
#undef main
#ifndef __AVX2__
#error AVX2 qualification must actually compile AVX2 kernels
#endif

static void avx2_checks(void) {
  unsigned b, pattern, gap;
  mode_now = "avx2";
  count_now = 256;
  for (b = 0; b <= 32; ++b) for (pattern = 0; pattern < 6; ++pattern)
    for (gap = 0; gap < 32; gap += 4) {
      uint32_t original[256], expected[256], state = 0x9e3779b9U ^ b;
      unsigned char wire[1024];
      size_t bytes = wire_size(256, b, 8), i;
      uint32_t combined = 0;
      Guard input = make_guard(1024, gap), fitted = make_guard(1024, gap);
      Guard packed = make_guard(bytes, gap), decoded = make_guard(1024, gap);
      uint32_t *values = (uint32_t *)input.bytes;
      width_now = b;
      for (i = 0; i < 256; ++i) {
        uint32_t x = pattern == 0 ? 0 : pattern == 1 ? mask(b)
          : pattern == 2 ? (i & 1 ? 0xaaaaaaaaU : 0x55555555U) & mask(b)
          : pattern == 3 ? (uint32_t)i & mask(b) : random32(&state);
        if (pattern != 5) x &= mask(b);
        original[i] = values[i] = x;
        expected[i] = x & mask(b);
        combined |= x;
      }
      memcpy(fitted.bytes, expected, sizeof(expected));
      readonly(&input); readonly(&fitted);
      need(avxmaxbits(values) == scalar_bits(combined), "AVX2 maxbits");
      scalar_wire(expected, 256, b, 8, wire);
      avxpack(values, (__m256i *)packed.bytes, b);
      need(memcmp(packed.bytes, wire, bytes) == 0, "masked AVX2 scalar wire");
      avxpackwithoutmask((const uint32_t *)fitted.bytes, (__m256i *)packed.bytes, b);
      need(memcmp(packed.bytes, wire, bytes) == 0, "unmasked AVX2 scalar wire");
      readonly(&packed);
      avxunpack((const __m256i *)packed.bytes, (uint32_t *)decoded.bytes, b);
      need(memcmp(decoded.bytes, expected, sizeof(expected)) == 0, "AVX2 decoded values");
      need(memcmp(input.bytes, original, sizeof(original)) == 0, "AVX2 original input changed");
      need(memcmp(fitted.bytes, expected, sizeof(expected)) == 0, "AVX2 fitted input changed");
      free_guard(&decoded); free_guard(&packed); free_guard(&fitted); free_guard(&input);
      ++cases;
    }
}

int main(int argc, char **argv) {
  if (argc == 2 && !strcmp(argv[1], "avx2")) {
    avx2_checks();
    printf("SIMDComp source avx2 cases PASS: %zu; 33 widths; 6 patterns; 8 alignments; scalar wire\n", cases);
    return 0;
  }
  return sse_source_qualification_main(argc, argv);
}

#include "lzma.h"

lzma_ret lzma_easy_buffer_encode(uint32_t preset, lzma_check check,
    const lzma_allocator *allocator, const uint8_t *input, size_t input_size,
    uint8_t *output, size_t *used, size_t capacity) {
    (void)preset; (void)check; (void)allocator; (void)input; (void)input_size;
    (void)output; (void)used; (void)capacity;
    return LZMA_PROG_ERROR;
}

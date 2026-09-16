#include "tscb_canonical_v1.h"

#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static uint16_t read_u16_le(const uint8_t *p) {
    return (uint16_t)p[0] | ((uint16_t)p[1] << 8u);
}

static uint32_t read_u32_le(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8u) | ((uint32_t)p[2] << 16u) |
           ((uint32_t)p[3] << 24u);
}

static uint64_t read_u64_le(const uint8_t *p) {
    uint64_t value = 0;
    for (unsigned int index = 0; index < 8u; ++index) {
        value |= ((uint64_t)p[index]) << (8u * index);
    }
    return value;
}

static int skip_bytes(FILE *input, uint64_t length) {
    uint8_t scratch[8192];
    while (length > 0u) {
        const size_t amount = length > sizeof(scratch) ? sizeof(scratch) : (size_t)length;
        if (fread(scratch, 1u, amount, input) != amount) {
            return -1;
        }
        length -= amount;
    }
    return 0;
}

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "usage: %s ARTIFACT.tscb\n", argv[0]);
        return 2;
    }
    FILE *input = fopen(argv[1], "rb");
    if (input == NULL) {
        fprintf(stderr, "cannot open %s: %s\n", argv[1], strerror(errno));
        return 2;
    }

    uint8_t header[24];
    if (fread(header, 1u, sizeof(header), input) != sizeof(header)) {
        fprintf(stderr, "truncated file header\n");
        fclose(input);
        return 3;
    }
    if (memcmp(header, TSCB_CANONICAL_MAGIC, 8u) != 0 ||
        read_u16_le(header + 8u) != TSCB_CANONICAL_FORMAT_MAJOR ||
        read_u16_le(header + 10u) != TSCB_CANONICAL_FORMAT_MINOR) {
        fprintf(stderr, "unsupported canonical header\n");
        fclose(input);
        return 4;
    }
    const uint64_t metadata_length = read_u64_le(header + 12u);
    const uint32_t buffer_count = read_u32_le(header + 20u);
    if (skip_bytes(input, metadata_length) != 0) {
        fprintf(stderr, "truncated metadata\n");
        fclose(input);
        return 5;
    }

    uint64_t payload_bytes = 0u;
    for (uint32_t index = 0; index < buffer_count; ++index) {
        uint8_t buffer_header[10];
        if (fread(buffer_header, 1u, sizeof(buffer_header), input) != sizeof(buffer_header)) {
            fprintf(stderr, "truncated buffer header at index %" PRIu32 "\n", index);
            fclose(input);
            return 6;
        }
        const uint16_t name_length = read_u16_le(buffer_header);
        const uint64_t payload_length = read_u64_le(buffer_header + 2u);
        if (skip_bytes(input, name_length) != 0 || skip_bytes(input, payload_length) != 0) {
            fprintf(stderr, "truncated buffer at index %" PRIu32 "\n", index);
            fclose(input);
            return 7;
        }
        payload_bytes += payload_length;
    }
    if (fgetc(input) != EOF) {
        fprintf(stderr, "undeclared trailing bytes\n");
        fclose(input);
        return 8;
    }
    fclose(input);
    printf(
        "format=%u.%u buffers=%" PRIu32 " metadata_bytes=%" PRIu64
        " payload_bytes=%" PRIu64 "\n",
        TSCB_CANONICAL_FORMAT_MAJOR,
        TSCB_CANONICAL_FORMAT_MINOR,
        buffer_count,
        metadata_length,
        payload_bytes
    );
    return 0;
}

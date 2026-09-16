#ifndef TSCB_CANONICAL_V1_H
#define TSCB_CANONICAL_V1_H

#include <stdint.h>

/*
 * On-disk fields are little-endian and packed byte-for-byte. Consumers must not
 * cast unaligned input directly to these structs; decode fields explicitly.
 *
 * File:
 *   tscb_file_header_v1
 *   metadata_json[metadata_length]
 *   repeated buffer_count times:
 *     tscb_buffer_header_v1
 *     name_utf8[name_length]
 *     payload[payload_length]
 *
 * Buffer dtype, shape, logical bit count, and SHA-256 are declared in metadata.
 */

#define TSCB_CANONICAL_MAGIC "TSCB2\0\0\0"
#define TSCB_CANONICAL_FORMAT_MAJOR 1u
#define TSCB_CANONICAL_FORMAT_MINOR 0u

#pragma pack(push, 1)
typedef struct tscb_file_header_v1 {
    uint8_t magic[8];
    uint16_t format_major_le;
    uint16_t format_minor_le;
    uint64_t metadata_length_le;
    uint32_t buffer_count_le;
} tscb_file_header_v1;

typedef struct tscb_buffer_header_v1 {
    uint16_t name_length_le;
    uint64_t payload_length_le;
} tscb_buffer_header_v1;
#pragma pack(pop)

#endif

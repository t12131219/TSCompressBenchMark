#pragma once
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

enum { BMK_GORILLA_COLUMN_ROWS = 512 };
/* A target compiles exactly one role. Successful payloads have a two-byte
 * big-endian row count, MSB-first tokens for that role, and zero padding. */
size_t bmk_gorilla_column_bound(size_t rows);
size_t bmk_gorilla_column_encode(const uint8_t *column, size_t rows, uint8_t *out, size_t cap);
int bmk_gorilla_column_decode(const uint8_t *payload, size_t bytes, size_t rows, uint8_t *column);

#ifdef __cplusplus
}
#endif

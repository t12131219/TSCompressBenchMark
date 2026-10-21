// SPDX-License-Identifier: MIT
#ifndef ABBA_FAMILY_C_H
#define ABBA_FAMILY_C_H
#include <stddef.h>
#ifdef __cplusplus
extern "C" {
#endif
/* All operations use UTF-8 JSON. Output has produced bytes, no NUL terminator.
 * out=NULL, capacity=0 queries exact required bytes (status AF_CAPACITY).
 * Failure sets produced=0 and preserves output, except capacity query/short
 * capacity returns the required size in required. Inputs may overlap output.
 * size_t output counters must point to separate writable caller objects.
 * JSON null samples denote missing values for supported fill policies.
 */
enum af_status {
  AF_OK = 0,
  AF_INVALID = 1,
  AF_CAPACITY = 2,
  AF_NOMEM = 3,
  AF_INTERNAL = 4
};
int af_execute_v1(const char *request, size_t request_bytes, char *output,
                  size_t capacity, size_t *produced, size_t *required);
unsigned af_api_version_v1(void);
#ifdef __cplusplus
}
#endif
#endif

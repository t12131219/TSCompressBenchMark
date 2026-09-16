#include "tscb_adapter_v1.h"
#include <string.h>

#ifdef __cplusplus
#define TSCB_STATIC_ASSERT static_assert
#else
#define TSCB_STATIC_ASSERT _Static_assert
#endif

TSCB_STATIC_ASSERT(TSCB_ADAPTER_ABI_V1 == 1u, "unexpected adapter ABI version");
TSCB_STATIC_ASSERT(TSCB_MAX_RANK_V1 == 8u, "unexpected maximum rank");
TSCB_STATIC_ASSERT(sizeof(((tscb_buffer_v1 *)0)->capacity_bytes) == 8u,
                   "buffer lengths must be uint64_t");

int main(void) {
    tscb_buffer_v1 buffer;
    memset(&buffer, 0, sizeof(buffer));
    buffer.dtype = TSCB_DTYPE_F64_LE_V1;
    buffer.rank = 1u;
    buffer.shape[0] = 1u;
    return buffer.used_bytes == 0u ? 0 : 1;
}

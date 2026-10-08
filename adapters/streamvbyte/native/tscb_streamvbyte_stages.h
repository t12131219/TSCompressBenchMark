#ifndef TSCB_STREAMVBYTE_STAGES_H
#define TSCB_STREAMVBYTE_STAGES_H
#include "tscb_adapter_v1.h"

/* Independent stages; seed is an explicitly accounted first int64 value. */
tscb_status_v1 tscb_svb_stage_a(tscb_codec_handle_v1 *, const tscb_buffer_v1 *,
    tscb_buffer_v1 *, int64_t *seed, uint32_t inverse, uint32_t enabled);
tscb_status_v1 tscb_svb_stage_b(tscb_codec_handle_v1 *, const tscb_buffer_v1 *,
    tscb_buffer_v1 *, uint32_t inverse, uint32_t enabled);
tscb_status_v1 tscb_svb_stage_c(tscb_codec_handle_v1 *, const tscb_buffer_v1 *,
    tscb_buffer_v1 *, uint32_t inverse, uint32_t enabled);
#endif

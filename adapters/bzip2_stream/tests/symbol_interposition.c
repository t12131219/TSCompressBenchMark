#include "bzlib.h"

int BZ2_bzCompressInit(bz_stream *stream, int block_size, int verbosity, int work_factor) {
    (void)stream;
    (void)block_size;
    (void)verbosity;
    (void)work_factor;
    return BZ_CONFIG_ERROR;
}

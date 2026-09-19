#include "zlib.h"

/* A globally loaded competing implementation must not replace vendored zlib. */
int ZEXPORT deflateInit2_(z_streamp stream, int level, int method, int window_bits,
                         int memory_level, int strategy, const char *version,
                         int stream_size) {
    (void)stream; (void)level; (void)method; (void)window_bits;
    (void)memory_level; (void)strategy; (void)version; (void)stream_size;
    return Z_VERSION_ERROR;
}

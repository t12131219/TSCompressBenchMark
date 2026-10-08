/* Modern frozen API shares the reviewed count/geometry/stage safety adapter. */
#define TSCB_SVB_MODERN 1
#if TSCB_SVB_DELTA64
#define KEY "delta-zigzag-streamvbyte-modern64"
#else
#define KEY "streamvbyte-modern-u32"
#endif
#include "../../streamvbyte/native/tscb_streamvbyte.c"

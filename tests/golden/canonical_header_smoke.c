#include "tscb_canonical_v1.h"

_Static_assert(sizeof(tscb_file_header_v1) == 24, "canonical file header size drifted");
_Static_assert(sizeof(tscb_buffer_header_v1) == 10, "canonical buffer header size drifted");

int main(void) {
    return TSCB_CANONICAL_FORMAT_MAJOR == 1u ? 0 : 1;
}

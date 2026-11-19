#include <tsbench/plugin_abi.h>

_Static_assert(sizeof(bmk_status) == 4, "ABI status width");
_Static_assert(BMK_ABI_V1 == 1, "ABI version");
_Static_assert(offsetof(bmk_plugin_v1, struct_size) == 0, "version prefix");
_Static_assert(offsetof(bmk_array_view, struct_size) == 0, "size prefix");

static const bmk_plugin_v1 test_plugin = {.struct_size = sizeof(bmk_plugin_v1), .abi_version = BMK_ABI_V1, .plugin_id = "test.abi"};
const bmk_plugin_v1 *bmk_get_plugin(uint32_t version) {
    return version == BMK_ABI_V1 ? &test_plugin : NULL;
}

int main(void) {
    return bmk_get_plugin(0) != NULL || bmk_get_plugin(BMK_ABI_V1) != &test_plugin;
}

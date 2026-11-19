#include "tsbench/plugin_abi.h"

#if BAD_PLUGIN == 1
int not_a_plugin(void) { return 42; }
#else
#if BAD_PLUGIN == 2
static bmk_plugin_v1 api = {.struct_size = sizeof(bmk_plugin_v1), .abi_version = 2, .plugin_id = "invalid"};
#elif BAD_PLUGIN == 3
static bmk_plugin_v1 api = {.struct_size = sizeof(uint32_t), .abi_version = 1, .plugin_id = "invalid"};
#elif BAD_PLUGIN == 4
static bmk_plugin_v1 api = {.struct_size = sizeof(bmk_plugin_v1), .abi_version = 1, .plugin_id = "invalid"};
#endif
const bmk_plugin_v1 *bmk_get_plugin(uint32_t abi) { return abi == BMK_ABI_V1 ? &api : 0; }
#endif

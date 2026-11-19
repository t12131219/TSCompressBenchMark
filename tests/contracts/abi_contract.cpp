#include <tsbench/plugin_abi.h>
#include <type_traits>

static_assert(std::is_standard_layout_v<bmk_plugin_v1>);
static_assert(std::is_standard_layout_v<bmk_owned_object>);
static_assert(std::is_same_v<decltype(&bmk_get_plugin), const bmk_plugin_v1*(*)(uint32_t)>);

int main() {
    return 0;
}

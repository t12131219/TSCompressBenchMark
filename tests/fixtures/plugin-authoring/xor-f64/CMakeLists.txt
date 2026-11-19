add_library(test_xor_f64 SHARED xor_f64.c)
target_link_libraries(test_xor_f64 PRIVATE tsbench_plugin_abi)
set_target_properties(test_xor_f64 PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED YES C_EXTENSIONS NO)

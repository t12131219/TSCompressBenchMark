from pathlib import Path
import subprocess
root=Path('/home/fzg/PycharmProjects/TSDataCompressBenchMark');src=root/'adapters/cameo_family/vendor/cameo_family';work=Path('/tmp/cameo-binding-sanitizer');work.mkdir(exist_ok=True)
archive=next((root/'build/tsbench/cameo-family-cache').glob('*/cmake/standalone/numeric/src/cf_lapack_source-build/lib/libopenblas_64.a'))
keys=['cameo','vw','pip','tp','swab','sim-piece','pmc-mean','swing-connected','dft','dwt-dct-ii']
s=f'''cmake_minimum_required(VERSION 3.18)
project(cameo_binding_safety LANGUAGES C CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(BUILD_TESTING OFF CACHE BOOL "" FORCE)
set(CF_ASAN ON CACHE BOOL "" FORCE)
set(CF_LAPACK_LIBRARY "{archive}" CACHE FILEPATH "" FORCE)
add_compile_options(-fsanitize=address,undefined -fno-omit-frame-pointer -fno-fast-math -ffp-contract=off)
add_link_options(-fsanitize=address,undefined)
add_subdirectory("{src}" standalone EXCLUDE_FROM_ALL)
'''
for i,k in enumerate(keys,1):
 t='tscb_'+k.replace('-','_');s+=f'''add_library({t} SHARED "{root/'adapters/cameo_family/native/binding.cc'}")
target_include_directories({t} PRIVATE "{root/'native/include'}" "{src/'tools'}")
target_link_libraries({t} PRIVATE cameo_family_static)
target_compile_definitions({t} PRIVATE CF_KIND={i} CF_KEY="{k}")
'''
s+=f'''add_executable(probe "{root/'docs/cameo_family_integration/sanitizer_probe.cpp'}")
target_include_directories(probe PRIVATE "{root/'native/include'}")
target_link_libraries(probe PRIVATE dl)
'''
(work/'CMakeLists.txt').write_text(s)
subprocess.run(['cmake','-S',str(work),'-B',str(work/'build'),'-DCMAKE_BUILD_TYPE=Debug'],check=True)
subprocess.run(['cmake','--build',str(work/'build'),'--parallel','2'],check=True)

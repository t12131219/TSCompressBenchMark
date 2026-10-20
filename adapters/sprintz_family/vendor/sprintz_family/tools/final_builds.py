from pathlib import Path
import subprocess,concurrent.futures
p=Path(__file__).resolve().parents[1]
def build(name,options):
 with (p/'evidence'/('final-'+name+'-build.log')).open('w') as f:
  subprocess.run(['cmake','-S',str(p),'-B',str(p/name)]+options,stdout=f,stderr=f,check=True)
  subprocess.run(['cmake','--build',str(p/name),'-j2'],stdout=f,stderr=f,check=True)
 return name
configs={
 'build':['-DCMAKE_BUILD_TYPE=Release'],
 'build-clang':['-DCMAKE_BUILD_TYPE=Release','-DCMAKE_C_COMPILER=clang','-DCMAKE_CXX_COMPILER=clang++'],
 'build-san':['-DCMAKE_BUILD_TYPE=Debug','-DSZ_SANITIZE=ON'],
 'build-tsan':['-DCMAKE_BUILD_TYPE=Debug','-DSZ_TSAN=ON'],
 'build-fuzz':['-DCMAKE_BUILD_TYPE=Debug','-DSZ_SANITIZE=ON','-DSZ_FUZZ=ON','-DCMAKE_C_COMPILER=clang','-DCMAKE_CXX_COMPILER=clang++']}
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
 for name in ex.map(lambda item:build(*item),configs.items()):print(name,'BUILD PASS',flush=True)

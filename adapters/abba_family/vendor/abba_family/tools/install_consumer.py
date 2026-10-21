from pathlib import Path
import subprocess,json,hashlib,os,tempfile
P=Path(__file__).resolve().parents[1];prefix=P/'install';steps=[]
def run(cmd,**kw):
 r=subprocess.run(list(map(str,cmd)),capture_output=True,text=True,**kw);steps.append({'cmd':list(map(str,cmd)),'exit':r.returncode,'stdout':r.stdout,'stderr':r.stderr});r.check_returncode();return r
run(['cmake','--install',P/'build','--prefix',prefix])
with tempfile.TemporaryDirectory(prefix='af-consumer-') as temp:
 t=Path(temp);(t/'client.c').write_text('''#include <abba_family_c.h>
#include <stdlib.h>
#include <string.h>
int main(void){const char *r="{\\"algorithm\\":\\"fabba\\",\\"values\\":[0,1,0,2]}";size_t n=9,need=9;if(af_api_version_v1()!=1)return 1;if(af_execute_v1(r,strlen(r),0,0,&n,&need)!=AF_CAPACITY||n)return 2;char*p=malloc(need);int rc=af_execute_v1(r,strlen(r),p,need,&n,&need);free(p);return rc;}
''');run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I'+str(prefix/'include'),t/'client.c','-L'+str(prefix/'lib'),'-labba_family','-Wl,-rpath,'+str(prefix/'lib'),'-o',t/'client-c']);run([t/'client-c'],cwd=t,env={'PATH':'/usr/bin:/bin'})
 (t/'client.cpp').write_text('''#include <abba_family.hpp>
#include <vector>
int main(){auto r=abba_family::parse_request(R"({"algorithm":"qabba","values":[0,1,3,1,2]})");const auto b=abba_family::encode(r);auto d=abba_family::decode(b.data(),b.size());return d["final_bits"]==b.size()*8?0:1;}
''')
 for kind in ['shared','static']:
  libs=['-labba_family'] if kind=='shared' else ['-labba_family_static','-laf_ckmeans','-laf_byte_zlib','-laf_byte_zstd','-laf_byte_bz2','-laf_lzma','-pthread']
  run(['g++','-std=c++17','-Wall','-Wextra','-Werror','-I'+str(prefix/'include'),t/'client.cpp','-L'+str(prefix/'lib'),*libs,'-Wl,-rpath,'+str(prefix/'lib'),'-o',t/('client-'+kind)]);run([t/('client-'+kind)],cwd=t,env={'PATH':'/usr/bin:/bin'})
report={'status':'PASS','steps':steps,'installed_dependencies':run(['ldd',prefix/'lib/libabba_family.so']).stdout};(P/'validation/installed-consumers.json').write_text(json.dumps(report,indent=2)+'\n');print('C11, shared C++17, static C++17 independent consumers PASS')

from pathlib import Path
import subprocess,tempfile,json,os
p=Path(__file__).resolve().parents[1];prefix=p/'install';rows=[]
with (p/'evidence/install.log').open('w') as log:
 subprocess.run(['cmake','--install',str(p/'build'),'--prefix',str(prefix)],stdout=log,stderr=log,check=True)
 with tempfile.TemporaryDirectory(prefix='sprintz-consumer-') as td:
  t=Path(td)
  source='''#include <sprintz_port.h>
#include <string.h>
int main(void){sz_config c={16,1,1,0,3};unsigned short input[1025];
for(int i=0;i<1025;i++)input[i]=(unsigned short)(i*7213);
unsigned char encoded[40000],decoded[2050];size_t n=0,z=0,b=0;
if(sz_bound(&c,sizeof input,&b)||b>sizeof encoded)return 1;
if(sz_encode(&c,input,sizeof input,encoded,sizeof encoded,&z))return 2;
if(sz_decode(&c,encoded,z,sizeof input,decoded,sizeof decoded,&n))return 3;
return n!=sizeof input||memcmp(input,decoded,n);}
'''
  (t/'consumer.c').write_text(source)
  subprocess.run(['cc','-std=c11','-I'+str(prefix/'include'),'-c',str(t/'consumer.c'),'-o',str(t/'consumer.o')],stdout=log,stderr=log,check=True)
  for typ in ['shared','static']:
   link=['-L'+str(prefix/'lib'),'-lsprintz'] if typ=='shared' else [str(prefix/'lib/libsprintz_static.a')]
   subprocess.run(['c++',str(t/'consumer.o')]+link+['-o',str(t/'consumer')],stdout=log,stderr=log,check=True)
   q=subprocess.run([str(t/'consumer')],cwd=t,env={'LD_LIBRARY_PATH':str(prefix/'lib'),'PATH':'/usr/bin:/bin'},stdout=log,stderr=log,check=True)
   rows.append({'language':'C11','link':typ,'status':'PASS'})
(p/'evidence/install-consumer.json').write_text(json.dumps(rows,indent=2)+'\n');print('install C11 consumers PASS',len(rows))

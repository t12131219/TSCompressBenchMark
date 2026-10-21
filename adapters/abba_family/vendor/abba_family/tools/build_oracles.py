from pathlib import Path
import subprocess,shutil,sys,sysconfig,json,hashlib,os
p=Path(__file__).resolve().parents[1];root=p.parents[1];work=p/'oracle-runtime';work.mkdir(exist_ok=True)
source=root/'Source/abba/upstream';out=work/'abba';shutil.copytree(source,out,dirs_exist_ok=True)
swig=root/'Toolchains/abba-swig-4.3.1/swig/data/bin/swig'
steps=[]
def run(cmd,cwd=None):
 env=dict(os.environ,SWIG_LIB=str(root/"Toolchains/abba-swig-4.3.1/swig/data/share/swig/4.3.1"));r=subprocess.run(list(map(str,cmd)),cwd=cwd,capture_output=True,text=True,env=env);steps.append({'command':list(map(str,cmd)),'exit':r.returncode,'stdout':r.stdout,'stderr':r.stderr});r.check_returncode()
run([swig,'-python','-c++','src/Ckmeans.i'],out)
run(['g++','-std=c++11','-O2','-fPIC','-shared','-I'+sysconfig.get_paths()['include'],*sorted((out/'src').glob('*.cpp')),out/'src/Ckmeans_wrap.cxx','-o',out/'src/_Ckmeans.so'])
(p/'validation/oracle-build.json').write_text(json.dumps({'status':'PASS','steps':steps,'swig_version':'4.3.1','swig_wheel_sha256':hashlib.sha256(next((root/'Source/abba-family-dependencies/oracle-wheels').glob('swig-*.whl')).read_bytes()).hexdigest()},indent=2)+'\n')
print('complete original ABBA CKmeans binding built')

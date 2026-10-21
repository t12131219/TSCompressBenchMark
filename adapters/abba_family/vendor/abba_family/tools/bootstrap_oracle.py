"""Install pinned wheels locally, without network or changes to host packages."""
from pathlib import Path
import subprocess,sys,json,hashlib
P=Path(__file__).resolve().parents[1];R=P.parents[1];wheels=R/'Source/abba-family-dependencies/oracle-wheels';groups={'abba-oracle-runtime':['numpy','scipy','scikit_learn','joblib','threadpoolctl','pytest','iniconfig','packaging','pluggy'],'abba-python-extra':['Cython','zstandard'],'abba-build-extra':['setuptools','wheel'],'abba-swig-4.3.1':['swig']};records=[]
for target,names in groups.items():
 files=[next(p for p in wheels.glob('*.whl') if p.name.lower().startswith(n.lower()+'-')) for n in names];cmd=[sys.executable,'-m','pip','install','--no-index','--no-deps','--upgrade','--target',str(R/'Toolchains'/target),*map(str,files)];subprocess.run(cmd,check=True);records.append({'target':target,'wheels':[{'name':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in files]})
(P/'validation/oracle-bootstrap.json').write_text(json.dumps(records,indent=2)+'\n')

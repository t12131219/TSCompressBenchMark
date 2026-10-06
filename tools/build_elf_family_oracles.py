"""Compile exact Elf / ElfStar source closures; codec logic remains untouched."""
import hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
for algorithm,bridge in [('elf','ElfOracle'),('elf-star','ElfStarOracle')]:
    d=ROOT/'Compression_Rewrite/Source'/algorithm;lock=json.loads((d/'ORACLE_ENVIRONMENT_LOCK.json').read_text());jars=[]
    for p in lock['packages']:
        path=Path('/tmp/tscb-elf-oracle-downloads')/p['name'];assert sha(path)==p['sha256']
        if path.suffix=='.jar':jars.append(path)
    files=[];patches=[]
    for f in json.loads((d/'SOURCE_FILES.json').read_text())['files']:
        p=d/'upstream'/f['path'];assert sha(p)==f['sha256']
        if p.suffix=='.java':files.append(p)
    if algorithm=='elf-star':
        original=next(p for p in files if p.name=='Elf32Utils.java');overlay=d/'build/reference-overlay/Elf32Utils.java';overlay.parent.mkdir(parents=True,exist_ok=True)
        s=original.read_text();marker='        int tempInt = (int) temp;';assert s.count(marker)==2
        overlay.write_text(s.replace(marker,'        float temp = v * get10iP(i);\n'+marker,1));files[files.index(original)]=overlay
        patches=[{'reason':'same missing unused helper declaration as SElfStar','original_sha256':sha(original),'overlay_sha256':sha(overlay),'selected_runtime_path_changed':False}]
    classes=d/'build/classes';classes.mkdir(parents=True,exist_ok=True)
    cmd=[lock['java_home']+'/bin/javac','-encoding','UTF-8','-source','1.8','-target','1.8','-cp',':'.join(map(str,jars)),'-d',str(classes),*map(str,files),str(d/(bridge+'.java'))]
    p=subprocess.run(cmd,capture_output=True);(d/'build/oracle.log').write_bytes(p.stdout+p.stderr)
    report={'status':'PASS' if p.returncode==0 else 'FAIL','command':cmd,'java':lock['java_home']+'/bin/java','classpath':':'.join(map(str,[classes,*jars])),'bridge':bridge,'patches':patches,'source_manifest_sha256':sha(d/'SOURCE_FILES.json'),'bridge_sha256':sha(d/(bridge+'.java'))}
    (d/'ORACLE_BUILD.json').write_text(json.dumps(report,indent=2)+'\n');print(algorithm,report['status'],p.stderr.decode()[-1800:]);assert p.returncode==0

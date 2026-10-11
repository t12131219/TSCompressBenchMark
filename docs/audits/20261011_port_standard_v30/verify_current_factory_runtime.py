"""Actual current factory admission and load, without codec/source parity claims."""
import ctypes
import hashlib
import json
from pathlib import Path

from tscompbench.adapters.factory import adapter_artifacts, create_adapter
from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.ids import canonical_json_bytes

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent / 'current_factory_runtime_verification_v1.json'
registry = CodecRegistry(ROOT / 'registry/codecs', SourceRegistry(ROOT / 'registry/sources'))
results=[]
for key in registry:
    manifest=registry.get(key)
    try:
        artifact,support=adapter_artifacts(ROOT,manifest)
        adapter=create_adapter(ROOT,manifest)
        oracle=manifest.document['identity']['family']=='HARNESS_ORACLE'
        if not oracle:
            library=ctypes.CDLL(str(artifact))
            library.tscb_get_abi_version.restype=ctypes.c_uint32
            assert library.tscb_get_abi_version()==1
        components=[{'role':'primary','sha256':hashlib.sha256(artifact.read_bytes()).hexdigest()}]
        components += [{'role':f'supporting_{index}','sha256':hashlib.sha256(path.read_bytes()).hexdigest()} for index,path in enumerate(support)]
        results.append({'codec':key,'status':'PASS','algorithm_id':manifest.algorithm_id,'source_artifact_id':manifest.source_artifact_id,'kind':'ORACLE_FACTORY' if oracle else 'REAL_FACTORY_PRE_POST_ELF_LOAD_AND_ABI_VERSION','support_count':len(support),'combined_artifact_sha256':hashlib.sha256(canonical_json_bytes(components)).hexdigest(),'runtime_profile':manifest.document['adapter'].get('runtime_profile')})
    except Exception as error:
        results.append({'codec':key,'status':'FAIL','error':str(error)})
report={'status':'PASS' if all(x['status']=='PASS' for x in results) else 'FAIL','scope':'CURRENT_FACTORY_AND_ELF_LOAD_ADMISSION_WITH_ABI_VERSION_ONLY_NOT_FINITE_CODEC_NATIVE_SUITE_OR_SOURCE_PARITY','entries':len(results),'native_entries':sum(x.get('kind')=='REAL_FACTORY_PRE_POST_ELF_LOAD_AND_ABI_VERSION' for x in results),'results':results,'driver_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
with OUT.open('x') as stream: stream.write(json.dumps(report,indent=2)+'\n')
print(json.dumps({'status':report['status'],'entries':report['entries'],'native_entries':report['native_entries'],'failures':[x for x in results if x['status']=='FAIL'],'report':str(OUT)},indent=2))
if report['status']!='PASS': raise SystemExit(1)

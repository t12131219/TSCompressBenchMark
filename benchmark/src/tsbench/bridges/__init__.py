"""Native bridge factory; frozen codec assets are its only external input."""
from pathlib import Path
import numpy as np
from ..build import artifact_path, sha
from ..registry import Registry, CodecError
from ..errors import Unavailable
import json


class RawStoreBridge:
    key = 'raw-store'
    last_native_ns = None
    last_native_timing = None

    def encode(self, array, params=None):
        if params:
            raise CodecError('raw-store has no parameters')
        return np.ascontiguousarray(array).tobytes()

    def decode(self, payload, dtype, shape, params=None):
        if params:
            raise CodecError('raw-store has no parameters')
        dtype = np.dtype(dtype)
        if len(payload) != int(np.prod(shape))*dtype.itemsize:
            raise CodecError('raw-store decoded length differs from descriptor')
        return np.frombuffer(payload,dtype=dtype).reshape(shape).copy()


def create_bridge(root, key, build_root=None):
    root = Path(root).resolve()
    spec = Registry(root).get(key)
    if spec.key == 'raw-store':
        return RawStoreBridge()
    path = artifact_path(root,spec.key,build_root=build_root)
    record_path = path.parent / 'build.json'
    if not path.is_file() or not record_path.is_file():
        raise Unavailable(f'{spec.key}: installed library missing; run tsbench build {spec.key}',stage='load')
    record = json.loads(record_path.read_text())
    if record.get('status') != 'ok' or record.get('artifact_sha256') != sha(path):
        raise Unavailable(f'{spec.key}: installed library hash differs from build record',stage='load')
    for entry in record.get('runtime_dependencies',[]):
        dependency = Path(entry['path'])
        if not dependency.is_file() or sha(dependency) != entry['sha256']:
            raise Unavailable(f'{spec.key}: runtime dependency missing or changed: {dependency}',stage='load')
    if spec.document['adapter']['factory'] == 'COMPLETED_REWRITE_CTYPES_V1':
        from .rw_abi_v1 import RwAbiBridge
        return RwAbiBridge(spec,path,record['artifact_sha256'])
    if spec.key == 'gorilla-prometheus-xor':
        from .gorilla import GorillaBridge
        return GorillaBridge(spec,path,record['artifact_sha256'])
    from .c_abi_v1 import CAbiBridge
    return CAbiBridge(spec,path,record['artifact_sha256'])

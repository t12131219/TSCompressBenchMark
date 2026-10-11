import ctypes, hashlib, importlib.util, json, os, re, subprocess, sys
from pathlib import Path
repository, root = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(repository / "src"))
spec = importlib.util.spec_from_file_location("isolated_build_evidence", repository / "src/tscompbench/adapters/build_evidence.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
artifact = root / "artifacts/release/libtoy_wrapper.so"
dependencies = module.verified_build_dependencies(root, artifact, "toy-native", {"factory": "TOY_NATIVE_CTYPES_V1"})
library = ctypes.CDLL(str(artifact))
library.toy_entry.restype = ctypes.c_int
value = library.toy_entry()
mapped = sorted({line.split()[-1] for line in Path("/proc/self/maps").read_text().splitlines() if "libtoy_runtime.so" in line})
listing = subprocess.run(["ldd", str(artifact)], check=True, capture_output=True, text=True).stdout
print(json.dumps({"declared_dependency_verification": "PASS", "verified_path_count": len(dependencies), "LD_LIBRARY_PATH": os.environ["LD_LIBRARY_PATH"], "toy_value": value, "actual_mapped_runtime": mapped, "current_ldd": listing}))

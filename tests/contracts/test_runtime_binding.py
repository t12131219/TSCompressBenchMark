import copy
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tsbench.assets import ContractError  # noqa: E402
from tsbench.runtime import create_build_lock, resolve_worker  # noqa: E402


class RuntimeBindingTests(unittest.TestCase):
    def test_change_requires_explicit_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("catalog", "schemas", "plugins", "include", "cmake", "tools", "third_party"):
                shutil.copytree(ROOT / name, root / name)
            for name in ("worker", "raw.so"):
                (root / name).write_bytes(name.encode())
            initial = create_build_lock(root, "worker", {"raw-store": "raw.so"})
            result = resolve_worker(root, initial, "raw-store", {})
            self.assertEqual(root / "raw.so", result["library"])
            with self.assertRaisesRegex(ContractError, "unknown plugin option"):
                resolve_worker(root, initial, "raw-store", {"threads": 2})
            modified = copy.deepcopy(initial)
            modified["plugins"]["raw-store"]["library"]["path"] = "worker"
            with self.assertRaisesRegex(ContractError, "identity mismatch"):
                resolve_worker(root, modified, "raw-store", {})
            (root / "raw.so").write_bytes(b"replacement")
            with self.assertRaisesRegex(ContractError, "SHA-256 mismatch"):
                resolve_worker(root, initial, "raw-store", {})
            rebound = create_build_lock(root, "worker", {"raw-store": "raw.so"})
            self.assertNotEqual(initial["build_id"], rebound["build_id"])
            (root / "plugins/codecs/raw-store/raw_store.c").write_text("/* changed source */")
            with self.assertRaisesRegex(ContractError, "manifest_id differs"):
                resolve_worker(root, rebound, "raw-store", {})
            index = root / "catalog/plugins.toml"
            index.write_text(index.read_text().replace("enabled = true", "enabled = false"))
            with self.assertRaisesRegex(ContractError, "disabled plugin"):
                resolve_worker(root, rebound, "raw-store", {})

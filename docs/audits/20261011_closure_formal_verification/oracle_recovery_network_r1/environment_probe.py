"""Python 3.6 compatible environment-only probe; no source model/codec is loaded."""
import importlib
import json
import os
import sys
import traceback


def main():
    result = {
        "schema_version": "tscb.legacy-runtime-environment-probe.v1",
        "python": sys.version,
        "executable": sys.executable,
        "prefix": sys.prefix,
        "base_prefix": getattr(sys, "base_prefix", None),
        "environment": {key: os.environ.get(key) for key in (
            "LD_LIBRARY_PATH", "CUDA_VISIBLE_DEVICES", "TF_FP16_RNN_USE_FP32_COMPUTE",
            "PYTHONHASHSEED", "PYTHONDONTWRITEBYTECODE", "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "KERAS_HOME", "TMPDIR")},
        "modules": {},
        "device_probe": None,
        "source_model_or_codec_loaded": False,
        "training_or_performance_executed": False,
    }
    modules = {}
    for name in ("numpy", "h5py", "tensorflow", "keras"):
        try:
            module = importlib.import_module(name)
            modules[name] = module
            result["modules"][name] = {
                "status": "IMPORTED", "version": getattr(module, "__version__", None),
                "path": getattr(module, "__file__", None),
            }
        except Exception as error:
            result["modules"][name] = {
                "status": "IMPORT_FAILED", "error_type": type(error).__name__,
                "error": str(error), "traceback": traceback.format_exc(),
            }
    if "tensorflow" in modules:
        try:
            tf = modules["tensorflow"]
            config = tf.ConfigProto(intra_op_parallelism_threads=1, inter_op_parallelism_threads=1)
            config.gpu_options.allow_growth = True
            with tf.Session(config=config) as session:
                devices = [{"name": device.name, "device_type": device.device_type}
                           for device in session.list_devices()]
            result["device_probe"] = {
                "status": "SESSION_INITIALIZED_DEVICES_ENUMERATED",
                "devices": devices, "is_built_with_cuda": tf.test.is_built_with_cuda(),
                "gpu_allow_growth": True, "empty_graph_only": True,
            }
        except Exception as error:
            result["device_probe"] = {
                "status": "DEVICE_INITIALIZATION_FAILED", "error_type": type(error).__name__,
                "error": str(error), "traceback": traceback.format_exc(),
            }
    try:
        import pkg_resources
        result["resolved_distributions"] = [
            {"name": dist.project_name, "version": dist.version, "location": dist.location}
            for dist in sorted(pkg_resources.working_set, key=lambda dist: dist.key)
        ]
    except Exception as error:
        result["distribution_inventory_error"] = str(error)
    with open("/proc/self/maps") as handle:
        paths = set()
        for line in handle:
            parts = line.rstrip().split(None, 5)
            if len(parts) == 6 and parts[5].startswith("/"):
                paths.add(parts[5])
        result["mapped_file_paths"] = sorted(paths)
    with open("/proc/self/status") as handle:
        result["process_status_observations"] = [line.strip() for line in handle
                                                  if line.startswith(("Threads:", "VmRSS:", "VmHWM:"))]
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()

"""Python 3.6 compatible CUDA/cuDNN version query; no model or kernel workload."""
import argparse
import ctypes
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runtime", type=Path)
    args = parser.parse_args()
    directory = args.runtime.resolve()
    result = {"schema_version": "tscb.locked-cuda-cudnn-version-query.v1", "runtime": str(directory),
              "source_model_codec_training_or_performance_executed": False}
    cuda = directory / "libcudart.so"
    cudnn = directory / "libcudnn.so"
    try:
        cudart = ctypes.CDLL(str(cuda))
        runtime_version = ctypes.c_int()
        driver_version = ctypes.c_int()
        runtime_rc = cudart.cudaRuntimeGetVersion(ctypes.byref(runtime_version))
        driver_rc = cudart.cudaDriverGetVersion(ctypes.byref(driver_version))
        cnn = ctypes.CDLL(str(cudnn))
        cnn.cudnnGetVersion.restype = ctypes.c_size_t
        result.update(status="VERSION_API_QUERIED", cuda_runtime_returncode=runtime_rc,
                      cuda_runtime_version=runtime_version.value, cuda_driver_returncode=driver_rc,
                      cuda_driver_version=driver_version.value, cudnn_version=cnn.cudnnGetVersion(),
                      cudart_path=str(cuda.resolve()), cudnn_path=str(cudnn.resolve()))
    except Exception as error:
        result.update(status="VERSION_API_FAILED", error_type=type(error).__name__, error=str(error))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()

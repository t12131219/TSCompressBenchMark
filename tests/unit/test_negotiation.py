from pathlib import Path

import numpy as np

from tscompbench.adapters import apply_compatibility_plan, validate_prepared_input
from tscompbench.codecs import (
    CodecRegistry,
    DataDescriptor,
    SourceRegistry,
    negotiate,
)
from tscompbench.contracts import (
    BenchmarkTrack,
    CapabilityStatus,
    LossMode,
    Topology,
    ValidityShape,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _codecs() -> CodecRegistry:
    sources = SourceRegistry(PROJECT_ROOT / "registry" / "sources")
    return CodecRegistry(PROJECT_ROOT / "registry" / "codecs", sources)


def _descriptor() -> DataDescriptor:
    return DataDescriptor(
        dataset_id="v2:dataset:sha256:" + "0" * 64,
        track=BenchmarkTrack.VALUE,
        topology=Topology.SYNCHRONOUS_MTS,
        n=4,
        m=1,
        shape=(4,),
        dtype_vector=("<f8",),
        physical_layout="SOA_COLUMNS",
        endianness="little",
        alignment_bytes=1,
        canonical_raw_bits=256,
        validity_shape=ValidityShape.NONE,
        timestamp_present=True,
        preserve_order=True,
        has_duplicates=False,
        has_out_of_order=False,
        has_negative_delta=False,
    )


def test_four_state_negotiation_and_adapter_validation() -> None:
    codecs = _codecs()
    descriptor = _descriptor()
    direct = negotiate(codecs.get("oracle-direct"), descriptor)
    assert direct.status is CapabilityStatus.DIRECT_SUPPORTED
    lossless = negotiate(codecs.get("oracle-lossless-adapter"), descriptor)
    lossy = negotiate(codecs.get("oracle-lossy-adapter"), descriptor)
    unsupported = negotiate(codecs.get("oracle-native-nd-only"), descriptor)
    assert lossless.status is CapabilityStatus.ADAPTER_LOSSLESS
    assert lossy.status is CapabilityStatus.ADAPTER_LOSSY
    assert unsupported.status is CapabilityStatus.UNSUPPORTED
    assert unsupported.missing_capabilities == ("rank", "topology")

    original = np.array([0.0, -0.0, 1.25, -3.5], dtype="<f8")
    original.flags.writeable = False
    prepared = apply_compatibility_plan(original, lossless)
    validate_prepared_input(original, prepared, lossless)
    assert prepared.telemetry.padding_bytes == 16
    assert prepared.telemetry.copied is True

    lossy_prepared = apply_compatibility_plan(original, lossy)
    validate_prepared_input(original, lossy_prepared, lossy, max_abs_error="0.000001")
    assert original.tobytes() == np.array([0.0, -0.0, 1.25, -3.5], dtype="<f8").tobytes()


def test_native_lossy_codec_uses_its_declared_loss_mode() -> None:
    manifest = _codecs().get("serf-qt")
    compatibility = negotiate(manifest, _descriptor())
    assert compatibility.status is CapabilityStatus.DIRECT_SUPPORTED
    assert compatibility.effective_loss_mode is LossMode.ERROR_BOUNDED_LOSSY

    unsupported = negotiate(
        manifest,
        _descriptor(),
        requested_loss_mode=LossMode.LOSSLESS,
    )
    assert unsupported.status is CapabilityStatus.UNSUPPORTED
    assert unsupported.reason_code == "LOSS_MODE_UNSUPPORTED"

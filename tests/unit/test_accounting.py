import pytest

from tscompbench.accounting import AccountingContractError, AccountingLedger
from tscompbench.contracts import BenchmarkTrack


def test_bit_first_ledger_closes_once_at_final_stream_boundary() -> None:
    ledger = AccountingLedger.create(
        track=BenchmarkTrack.VALUE,
        canonical_raw_bits=800,
        final_physical_bytes=5,
        value_bits=31,
        metadata_bits=1,
        padding_bits=8,
        external_side_information_bits=7,
    )
    assert ledger.serialized_bits == 40
    assert ledger.final_bits == 47
    assert ledger.final_physical_bytes == 5
    assert ledger.to_document()["size_ratio"] == format(47 / 800, ".17g")


def test_ledger_rejects_capacity_as_size_and_cross_track_ownership() -> None:
    with pytest.raises(AccountingContractError, match="close"):
        AccountingLedger.create(
            track=BenchmarkTrack.VALUE,
            canonical_raw_bits=64,
            final_physical_bytes=100,
            value_bits=8,
        )
    with pytest.raises(AccountingContractError, match="Timestamp track"):
        AccountingLedger.create(
            track=BenchmarkTrack.TIMESTAMP,
            canonical_raw_bits=64,
            final_physical_bytes=1,
            value_bits=8,
        )

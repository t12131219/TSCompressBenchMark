from decimal import Decimal

import pytest

from tscompbench.ids.canonical_json import CanonicalJSONError, canonical_json_bytes, stable_id


def test_canonical_json_normalizes_unicode_and_key_order() -> None:
    left = {"é": "é", "a": Decimal("1.2500")}
    right = {"a": Decimal("1.25"), "e\u0301": "e\u0301"}
    assert canonical_json_bytes(left) == canonical_json_bytes(right)
    assert stable_id("fixture", left) == stable_id("fixture", right)


def test_binary_float_and_path_are_rejected_from_ids(tmp_path) -> None:
    with pytest.raises(CanonicalJSONError):
        canonical_json_bytes({"value": 0.1})
    with pytest.raises(CanonicalJSONError):
        canonical_json_bytes({"path": tmp_path})

from __future__ import annotations

import json
from pathlib import Path

from tscompbench.codecs import validate_onboarding_card

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_all_source_onboarding_cards_are_complete_and_stable() -> None:
    cards = sorted((PROJECT_ROOT / "registry/onboarding").glob("*.json"))
    assert cards
    for path in cards:
        document = json.loads(path.read_text(encoding="utf-8"))
        validated = validate_onboarding_card(document)
        assert validated["source_onboarding_id"].startswith(
            "v2:source-onboarding:sha256:"
        )

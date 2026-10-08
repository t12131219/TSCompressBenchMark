"""A successful total duration must not conceal an undersampled direction."""
from pathlib import Path
import runpy

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def checker(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT/'tools'))
    return runpy.run_path(str(ROOT/'tools/streamvbyte_audit_common.py'))[
        'formal_direction_durations_satisfied'
    ]


@pytest.mark.parametrize('encode,decode',[(10**9-1,2*10**9),(2*10**9,10**9-1)])
def test_total_duration_and_pass_flag_cannot_hide_short_direction(checker,encode,decode):
    assert not checker({'selected_encode_wall_ns':encode,'selected_decode_wall_ns':decode,
                        'selected_wall_ns':encode+decode,'min_duration_satisfied':True})


def test_both_directions_meet_the_exact_threshold(checker):
    assert checker({'selected_encode_wall_ns':10**9,'selected_decode_wall_ns':10**9,
                    'min_duration_satisfied':True})


@pytest.mark.parametrize('value',[None,True,10**9+0.0,'1000000000'])
def test_missing_or_invalid_saved_nanoseconds_are_rejected(checker,value):
    assert not checker({'selected_encode_wall_ns':value,'selected_decode_wall_ns':10**9,
                        'min_duration_satisfied':True})


def test_failed_duration_claim_is_not_promoted(checker):
    assert not checker({'selected_encode_wall_ns':10**9,'selected_decode_wall_ns':10**9,
                        'min_duration_satisfied':False})

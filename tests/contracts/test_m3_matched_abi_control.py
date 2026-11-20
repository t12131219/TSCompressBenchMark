from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from m3_matched_abi_control import _binding, _bytes
from tsbench.assets import ContractError


def test_bounded_abi_decoder_requires_actual_restored_bits_and_backend(tmp_path):
    raw, schema = b'data', b'{}'
    (tmp_path / 'raw').write_bytes(raw)
    (tmp_path / 'schema').write_bytes(schema)
    expected = {'raw': _bytes(raw), 'schema': _bytes(schema)}
    meta = {'backend': 'ln-xz-baseline', 'threads': 1, 'blocks': 1, 'mode': 'batch', 'fallback': False, 'operation': 'decode'}
    obs = [{'columns': [{'dtype': 2, 'count': 4}]}, meta]
    assert _binding(tmp_path, 'decode', 'xz-baseline', obs, expected)['outputs'] == expected
    with pytest.raises(ContractError, match='different native configuration'):
        _binding(tmp_path, 'decode', 'zstd', obs, expected)
    (tmp_path / 'raw').write_bytes(b'0000')
    with pytest.raises(ContractError, match='recovery differs'):
        _binding(tmp_path, 'decode', 'xz-baseline', obs, expected)


def test_encoder_records_preset_and_nonempty_artifact(tmp_path):
    (tmp_path / 'frame').write_bytes(b'frame')
    obs = [{'backend': 'ln-zstd-baseline', 'threads': 1, 'blocks': 1, 'mode': 'batch', 'fallback': False,
            'operation': 'encode', 'level': 3}]
    assert _binding(tmp_path, 'encode', 'zstd', obs, {})['outputs']['frame'] == _bytes(b'frame')
    obs[0]['level'] = 5
    with pytest.raises(ContractError, match='different native configuration'):
        _binding(tmp_path, 'encode', 'zstd', obs, {})

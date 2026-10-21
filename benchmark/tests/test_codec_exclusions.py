"""Excluded codecs remain inspectable but cannot enter Bench execution."""
import json
from pathlib import Path

import numpy as np
import pytest

from tsbench import build, cli, schemes
from tsbench.bridges import create_bridge
from tsbench.bridges.c_abi_v1 import CAbiBridge
from tsbench.config import DEFAULT_PROFILE, DEFAULT_TASK
from tsbench.data import TimeSeriesObject
from tsbench.registry import ExcludedError, Registry

ROOT=Path(__file__).resolve().parents[2]
EXCLUDED=('lzss-raw','lzss-dipperstein-c')
REASON='算法接入异常，处于排除状态'


@pytest.mark.parametrize('key',EXCLUDED)
def test_excluded_registration_is_visible_but_not_selectable(key):
    registry=Registry(ROOT);spec=registry.get(key)
    assert spec.excluded and spec.exclusion_reason==REASON
    assert key not in {s.key for s in registry.list()}
    assert key in {s.key for s in registry.list(include_excluded=True)}
    with pytest.raises(ExcludedError,match=REASON):spec.validate_array(np.arange(4,dtype='u1'))
    assert not registry.get('lzsse2-raw').excluded
    assert not registry.get('lzsse8-raw').excluded


@pytest.mark.parametrize('key',EXCLUDED)
@pytest.mark.parametrize('boundary',['native_core','native_api','object_memory'])
def test_all_benchmark_boundaries_reject_excluded_codec(key,boundary):
    obj=TimeSeriesObject({'V':np.arange(8,dtype='u1')},{'roles':{'V':'V'}})
    task={**DEFAULT_TASK,'boundary':boundary,'lifecycle':'independent_object' if boundary=='object_memory' else 'prepared'}
    support=schemes.capability({'codec':key,'params':{}},obj,task,DEFAULT_PROFILE,asset_root=ROOT)
    assert support['supported'] is False
    assert support['status']=='excluded' and support['stage']=='registry.admission'
    assert REASON in support['reason']


@pytest.mark.parametrize('key',EXCLUDED)
def test_component_routes_cannot_bypass_exclusion(key):
    obj=TimeSeriesObject({'V':np.arange(8,dtype='u1')},{'roles':{'V':'V'}})
    method={'codec':'raw-store','components':{'V':{'codec':key}}}
    task={**DEFAULT_TASK,'boundary':'object_memory','lifecycle':'independent_object'}
    support=schemes.capability(method,obj,task,DEFAULT_PROFILE,asset_root=ROOT)
    assert support['status']=='excluded' and REASON in support['reason']


@pytest.mark.parametrize('key',EXCLUDED)
def test_explicit_build_and_load_fail_before_touching_native_code(key,monkeypatch):
    def forbidden(*args,**kwargs):raise AssertionError('native code must not be touched')
    monkeypatch.setattr(build,'_source_files',forbidden)
    monkeypatch.setattr('tsbench.bridges.artifact_path',forbidden)
    monkeypatch.setattr('tsbench.bridges.c_abi_v1.load_library',forbidden)
    with pytest.raises(ExcludedError,match=REASON):build.build_codec(ROOT,key)
    with pytest.raises(ExcludedError,match=REASON):create_bridge(ROOT,key)
    with pytest.raises(ExcludedError,match=REASON):CAbiBridge(Registry(ROOT).get(key),Path('/not-loaded'),'unused')


def test_build_all_omits_excluded_codecs(monkeypatch):
    called=[]
    def fake(root,key,**kwargs):called.append(key);return {'status':'ok','codec':key}
    monkeypatch.setattr(build,'build_codec',fake)
    records=build.build_all(ROOT)
    assert len(records)==43 and not set(EXCLUDED)&set(called)
    assert {'lzsse2-raw','lzsse8-raw'}<=set(called)


def test_codec_command_reports_exclusion_reason(capsys):
    assert cli.main(['codecs','--asset-root',str(ROOT)])==0
    rows={r['key']:r for r in json.loads(capsys.readouterr().out)}
    for key in EXCLUDED:
        assert rows[key]['status']=='excluded' and rows[key]['reason']==REASON
    assert rows['lzsse2-raw']['status']=='enabled'

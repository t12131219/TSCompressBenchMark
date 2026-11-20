"""Retain and verify native diagnostics before releasing unsuccessful scratch work."""
import shutil

from ..assets import local_file, require
from .m3_lzbench_timing import _file, _ref
from .m3_pcodec_grouped_timing import _sync

NAMES = ('native.stdout', 'native.stderr')
SUFFIXES = {'anchor', 'trial'}


def retain(run, directory, kind, scratch, lanes):
    """Copy only the supervisor-owned log files; never publish native scratch output."""
    require(kind in SUFFIXES, 'unknown failed measurement phase')
    refs = []
    for lane in lanes:
        require(lane in ('encode', 'decode', 'snapshot_decode'), 'invalid failed measurement lane')
        for name in NAMES:
            src = scratch / lane / name
            if not src.exists():
                continue
            src = local_file(scratch, f'{lane}/{name}')
            target = run / directory / kind / lane / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with src.open('rb') as inp, target.open('xb') as out:
                shutil.copyfileobj(inp, out)
            _sync(target)
            refs.append(_ref(run, target))
    if refs:
        for place in (run / directory / kind, run / directory, (run / directory).parent, run):
            _sync(place)
        for lane in lanes:
            place = run / directory / kind / lane
            if place.is_dir():
                _sync(place)
    return refs


def reason(exc, scratch, failed_path):
    return (str(exc) or type(exc).__name__).replace(str(scratch), failed_path.as_posix())


def check(run, directory, doc, directions, *, full=True):
    failure = doc['failure_logs']
    failed = doc['status'] == 'measurement_failed'
    require(isinstance(failure, list) and (failed or not failure), 'invalid M3 failure log terminal')
    expected = []
    if failed:
        trial = next((t for t in doc['trials'] if t['status'] == 'measurement_failed'), None)
        kind, lanes = ('trial', (trial['direction'],)) if trial else ('anchor', directions)
        possible = [f'{directory}/{kind}/{lane}/{name}' for lane in lanes for name in NAMES]
        expected = [r['path'] for r in failure]
        require(expected == [p for p in possible if p in expected], 'unexpected M3 failure log paths')
        if '; see ' in doc['reason']:
            named = doc['reason'].rsplit('; see ', 1)[1]
            require(any(named.endswith('/' + p) for p in expected), 'referenced M3 failure log was not retained')
    for ref in failure:
        _file(run, ref)
    if full:
        base = run / directory
        require(not base.is_symlink(), 'symlink in M3 failed measurement inventory')
        paths = list(base.rglob('*'))
        require(all(not p.is_symlink() and (p.is_dir() or p.is_file()) for p in paths) and
                {p.relative_to(run).as_posix() for p in paths if p.is_file()} == set(expected) and
                base.exists() == bool(expected), 'M3 failed measurement log inventory differs')

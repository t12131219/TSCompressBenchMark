"""Launch the unmodified CORAD Source bridge without train/evaluation corpus access."""
from pathlib import Path
import sys

from ..assets import digest, require
from ..planner.corad_training import STAGED_BRIDGE, VECTORS
from .isolated_worker import LAUNCHERS, validate_limits
from .process import invoke


def invoke_source(slot, step, limits, work, logs, label, inputs, cancelled):
    env=slot['source_runtime']
    prefix=Path(sys.prefix).resolve(strict=True)
    exe=(prefix/'bin/python').resolve(strict=True)
    require(exe.is_relative_to(prefix) and digest(exe)==env['python_sha256'] and
            list(inputs)==[STAGED_BRIDGE,VECTORS], 'CORAD Source interpreter or training-only mounts differ')
    validate_limits(limits)
    out=work/'out'; out.mkdir()
    a,f=(limits[k] for k in ('address_space_bytes','file_bytes'))
    argv=[LAUNCHERS[0],f'--as={a}:{a}',f'--fsize={f}:{f}','--core=0:0','--',LAUNCHERS[1],
          '--unshare-net','--unshare-pid','--unshare-ipc','--die-with-parent','--clearenv','--cap-drop','ALL',
          '--ro-bind','/usr/lib','/usr/lib','--symlink','usr/lib','/lib','--symlink','usr/lib64','/lib64',
          '--ro-bind','/usr/lib64','/usr/lib64','--proc','/proc','--dev','/dev','--tmpfs','/tmp',
          '--ro-bind',str(prefix),'/toolchain','--setenv','HOME','/tmp','--setenv','LC_ALL','C',
          '--bind',str(out),'/out','--dir','/stage',
          '--symlink','/out/'+step['outputs'][0],'/stage/'+step['outputs'][0]]
    for k,v in sorted(env['thread_environment'].items()):
        argv.extend(('--setenv',k,v))
    for name,path in inputs.items():
        argv.extend(('--ro-bind',str(path),f'/stage/{name}'))
    argv.extend(('--chdir','/stage','--',env['executable'],*step['argv']))
    result=invoke(argv,work,logs,label,limits['wall_seconds'],cancelled,environment={},observe_process=True,capture_usage=True)
    if result['pid'] is not None:
        result['input_mounts']={k:{'bytes':p.stat().st_size,'sha256':digest(p)} for k,p in inputs.items()}
    return out,result

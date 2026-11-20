#!/usr/bin/env python3
"""Build and freeze a development-only ZFP array rate comparison."""
from argparse import ArgumentParser
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from tsbench.application.m3_real_corpus_execution import _entry_map
from tsbench.application.m3_zfp import ARRAY_LAYOUT, array_windows
from tsbench.application.smoke import write_new
from tsbench.assets import content_id, digest, load_json, local_file, require, verify_asset
from tsbench.recovery import plan_recovery
from tsbench.supervisor.isolated_worker import launcher_lock

RATES = ((18,32),(33,48),(49,64))
CONTROL = 'plugins/codecs/zfp-reversible/corpus_control.cpp'
HEADER = 'a702beb75462ac64772339455d8041302e634edb88c2f9aa2bebf07b5a9b832b'
TOOL = 'zfp-array-rate-development'


def ref(p):
    return {'path':p.relative_to(ROOT).as_posix(),'bytes':p.stat().st_size,'sha256':digest(p)}


def derived(text):
    # Keep exactly the array create/get/set/flush/import operations from the
    # hashed corpus harness. Parameterize only the rate and word-aligned size.
    pairs = ', '.join(f'{{{a}, {b}}}' for a,b in RATES)
    for old,new in (
        ('zn_config array_config(size_t n)',f'''struct ArrayRate {{ unsigned requested, effective; }};
constexpr ArrayRate array_rates[] = {{{pairs}}};
ArrayRate array_rate(std::string_view arg) {{
    for (const auto rate : array_rates)
        if (arg == std::to_string(rate.requested)) return rate;
    throw std::runtime_error("unregistered ZFP development rate");
}}
zn_config array_config(size_t n, ArrayRate rate)'''),
        ('cfg.parameter = 18;', 'cfg.parameter = rate.requested;'),
        ('void array_io(bool encode, size_t n, const char* path) {\n    const auto cfg = array_config(n);\n    const size_t bytes = ((n + 3) / 4) * 16;',
         'void array_io(bool encode, size_t n, const char* path, ArrayRate rate) {\n    const auto cfg = array_config(n, rate);\n    const size_t bytes = ((n + 3) / 4) * (rate.effective / 2);'),
        ('zn_array_rate(raw) == 32', 'zn_array_rate(raw) == rate.effective'),
        (r'<< ",\"requested_rate\":18,\"effective_rate\":32}\n";',
         r'<< ",\"requested_rate\":" << rate.requested << ",\"effective_rate\":" << rate.effective << "}\n";'),
        ('check(argc == 4 && (op == "array-update" || op == "array-reopen"), "invalid array arguments");',
         'check(argc == 5 && (op == "array-update" || op == "array-reopen"), "invalid array arguments");'),
        ('rows(argv[2], 8, max_array_rows), argv[3]);','rows(argv[2], 8, max_array_rows), argv[3], array_rate(argv[4]));')):
        require(text.count(old)==1,'frozen ZFP control is not the expected rate-18 harness')
        text = text.replace(old,new)
    return text


def project_windows(contract, cols, rows, start, end):
    require(0 <= start < end <= rows,'invalid development range')
    spans = []
    for c,a,b in array_windows(contract,cols,rows):
        lo,hi = max(start,a),min(end,b)
        if lo >= hi:
            continue
        if spans and spans[-1][0]==c and spans[-1][2]==lo:
            spans[-1][2] = hi
        else:
            spans.append([c,lo,hi])
    # An arbitrary boundary of a full-file window must not discard otherwise
    # usable development rows. Rebalance only within contiguous accepted spans.
    limit = ARRAY_LAYOUT['max_rows']
    kept, short = [], []
    for c,lo,hi in spans:
        if hi-lo < ARRAY_LAYOUT['min_rows']:
            short.append([c,lo,hi])
            continue
        count = (hi-lo+limit-1)//limit
        base,extra = divmod(hi-lo,count)
        require(base>=ARRAY_LAYOUT['min_rows'],'ZFP development balance cannot cover accepted span')
        for i in range(count):
            stop = lo + base + (i<extra)
            kept.append([c,lo,stop])
            lo = stop
        require(lo==hi,'ZFP development geometry did not close')
    return kept,short


def freeze(baseline_file, build, out):
    require(build.is_relative_to(ROOT/'build') and out.is_relative_to(ROOT/'results') and not out.exists(),
            'ZFP development needs fresh project-local outputs')
    baseline = load_json(baseline_file)
    require(baseline['plan_content_id']==content_id({k:v for k,v in baseline.items() if k!='plan_content_id'}),
            'ZFP baseline plan identity differs')
    native = baseline['build']['zfp_corpus']
    library = verify_asset(ROOT,native['dependency'])
    require(library.stat().st_size==native['dependency']['bytes'],'ZFP library extent differs')
    header = local_file(library.parent,'source/zfp-native/include/zfp_native.h')
    source = local_file(ROOT,CONTROL)
    require(digest(header)==HEADER and digest(source)==native['code'][CONTROL], 'frozen ZFP control or header changed')
    definition = verify_asset(ROOT,baseline['definition']['plan'])
    entries = _entry_map(ROOT,load_json(definition))
    cases = {}
    for item in baseline['work_items']:
        if (item['selection'],item['route'])!=(31,'fixed-rate-array'):
            continue
        ds = item['dataset_id']; entry = entries[ds]
        train,dev,test = entry['partitions']
        require(ds not in cases and item['applicability']=='input_domain_matches' and
                [p['name'] for p in (train,dev,test)]==['train','development','test'] and train['start']==0 and
                train['end']==dev['start'] and dev['end']==test['start'] and test['end']==entry['rows'],
                'ZFP candidate scope crosses a development boundary or duplicates a file')
        kept,short = project_windows(item['input']['array_contract'],entry['value_count'],entry['rows'],dev['start'],dev['end'])
        require(bool(kept),'ZFP candidate development file has no usable array windows')
        cases[ds] = {'work_item_id':item['work_item_id'],'source':entry['file'],'development':dev,
                     'windows':kept,'excluded_short_fragments':short}
    require(set(cases)==set(entries) and len(cases)==23,'ZFP candidate must cover every frozen input')
    build.mkdir(parents=True,exist_ok=False)
    code = build/'zfp_array_rate_development.cpp'; code.write_text(derived(source.read_text()))
    binary = build/TOOL; cxx = '/usr/bin/c++'
    flags = ['-std=c++17','-O2','-fno-fast-math','-ffp-contract=off','-Wall','-Wextra','-Werror']
    subprocess.run([cxx,*flags,'-I',str(header.parent),str(code),str(library),'-Wl,-rpath,$ORIGIN','-o',str(binary)],check=True)
    runtime = plan_recovery(ROOT,{},(),tools={TOOL:{k:v for k,v in ref(binary).items() if k!='bytes'}},libraries=[native['dependency']])
    body = {'schema':'bmk.m3-zfp-array-rate-development/1','base_plan':ref(baseline_file),'definition':ref(definition),
            'source_control':ref(source),'header':ref(header),'control':ref(code),'builder':ref(Path(__file__).resolve()),
            'compiler':subprocess.check_output([cxx,'--version'],text=True).splitlines()[0],'compile_flags':flags,
            'runtime':runtime,'launchers':launcher_lock(),'rates':[{'requested':a,'expected_effective':b} for a,b in RATES],
            'selection_policy':'only after all 23 development projections; both quality checks and unchanged blocks required; minimize complete bytes; tie to lower request',
            'geometry_policy':'intersect accepted domain with development, then balance within each contiguous eligible span',
            'recovery_mounts':['frame'],'quality':ARRAY_LAYOUT['quality'],'cases':cases,'held_out_read':False,
            'qualification_granted':False,'timing_admitted':False,'stage_accepted':False}
    write_new(out,{**body,'plan_id':content_id(body)})
    print(len(cases),sum(len(c['windows']) for c in cases.values()),sum(len(c['excluded_short_fragments']) for c in cases.values()))


if __name__=='__main__':
    p = ArgumentParser(description=__doc__)
    for key in ('baseline','build','out'):
        p.add_argument('--'+key,type=Path,required=True)
    a = p.parse_args()
    try:
        freeze(a.baseline.resolve(strict=True),a.build.resolve(),a.out.resolve())
    except (OSError,ValueError,subprocess.CalledProcessError) as exc:
        p.exit(1,f'{exc}\n')

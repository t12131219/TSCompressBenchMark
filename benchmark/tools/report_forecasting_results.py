"""Audit and visualize the representative forecasting runs without codecs."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import sys
import tomllib
from zoneinfo import ZoneInfo

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'benchmark/src'))
from tsbench.records import file_hash, write_json

METRICS=('compression_ratio','encode_MiB_s','decode_MiB_s')
LIVES=('prepared','fresh_request')
KINDS={'bitwise':'无损','bounded_abs':'ABS ≤ 0.01','empirical_quality':'经验质量（无最大误差保证）'}


def number(value):
    if value is None:return '—'
    return f'{value:.3g}'


def method_label(row):
    if row['codec']=='swing-filter-disjoint-quantized':
        return row['codec']+' / '+row['params']['quality_mode']
    return row['codec'] if row['method_id']==row['codec'] else row['codec']+' / '+row['method_id']


def identity(path):
    path=Path(path)
    return {'path':str(path.resolve()),'sha256':file_hash(path),'bytes':path.stat().st_size}


def audit(entry, allow_incomplete):
    directory=Path(entry['run'])
    summary_path=directory/'report/summary.json'
    if not summary_path.exists():
        if allow_incomplete:return [],None
        raise ValueError(f'missing run: {directory}')
    manifest=json.loads((directory/'manifest.json').read_text())
    summary=json.loads(summary_path.read_text())
    assert summary['manifest_hash']==file_hash(directory/'manifest.json')
    assert summary['observations_hash']==file_hash(directory/'observations.jsonl')
    assert not summary['interrupted_jsonl_tail']
    assert manifest['state']=='complete' and manifest['execution_source_unchanged']
    schedule=Counter((x['case_id'],x['session'],x['round']) for x in manifest['schedule'])
    assert all(n==1 for n in schedule.values())
    actual=Counter()
    products=0; quality_failures=0
    with (directory/'observations.jsonl').open() as stream:
        for line in stream:
            row=json.loads(line)
            if row.get('event')!='terminal' or row.get('phase')!='measurement':continue
            actual[(row['case_id'],row['session'],row['round'])]+=1
            assert row.get('attempt',0)==0
            if row['status']!='ok':continue
            assert row['verification']['passed'] and row['verification']['input_unchanged']
            batch=row['native_batch']
            assert batch['python_inside_batch_clock'] is False
            assert batch['clock']=='CLOCK_MONOTONIC'
            assert batch['iterations']==manifest['resolved_config']['execution']['native_loops']
            for operation in ('encode','decode'):
                assert math.isclose(row[operation+'_ns']*row['loops'],row[operation+'_batch_ns'])
            assert len(row['native_products'])==batch['iterations']+batch['warmup_iterations']
            assert row['verification']['validated_operations']==len(row['native_products'])
            for op in row['native_products']:
                assert op['verification']['passed'] and op['verification']['input_unchanged']
                assert op['output_bytes']>=0
                if op.get('payload_path'):
                    assert file_hash(op['payload_path'])==op['payload_hash']
                products+=1
            assert row['raw_bytes']==row['codec_input_bytes']
            assert row['framework_management_bytes_in_codec_size']==0
    assert schedule==actual, f'incomplete/extra trial schedule: {directory}'
    case_map={x['case_id']:x for x in manifest['cases']}
    rows=[]
    for case in summary['cases']:
        raw=case_map[case['case_id']]
        value=raw.get('components',{}).get('V',{})
        rows.append({**case,'fidelity':entry['fidelity'],'kind':entry['kind'],
                     'raw_object_id':raw['raw_object_id'],
                     'domain_supplement':entry['group'].startswith('domain-supplement'),
                     'run':str(directory),'dtype':value.get('dtype'), 'shape':value.get('shape'),
                     'recorder_affinity':manifest['environment'].get('affinity'),
                     'run_created_at_utc':manifest['created_at_utc'],
                     'input_path':raw['dataset']['path'],
                     'source_file':raw['dataset'].get('source'),
                     'params':raw['method']['params']})
    return rows,{'run':str(directory),'requested_cases':len(rows),'planned_trials':len(schedule),
                'complete_cases':sum(x['complete_case'] for x in rows),
                'status_counts':summary['status_counts'],'admission_counts':summary['admission_counts'],
                'verified_products':products,'source_id':manifest['execution_provenance']['source_id'],
                'files':[identity(directory/p) for p in ['manifest.json','observations.jsonl','report/summary.json']]}


def chart(pairs, title, path, average=False, lives=LIVES):
    names=sorted(pairs)
    if not names:return
    fig,axes=plt.subplots(1,3,figsize=(17,max(3.1,0.31*len(names)+1.8)),sharey=True)
    y=np.arange(len(names))
    colors=['#147d92','#df9a39']
    for axis,metric,label in zip(axes,METRICS,['Compression ratio (x)','Encode (MiB/s)','Decode (MiB/s)']):
        for i,life in enumerate(lives):
            vals=[];lo=[];hi=[]
            for name in names:
                row=pairs[name].get(life)
                valid=row and row.get('complete_case') and row.get(metric) is not None
                v=row[metric] if valid else np.nan
                vals.append(v)
                if valid and metric!='compression_ratio' and not average:
                    op='encode' if metric.startswith('encode') else 'decode'
                    times=row[op+'_ns'];scale=row['raw_bytes']*1e9/2**20
                    lo.append(max(0,v-scale/times['q3']));hi.append(max(0,scale/times['q1']-v))
                else:lo.append(0);hi.append(0)
            yy=y+(i-.5)*.36
            finite=np.isfinite(vals)
            axis.barh(yy[finite],np.asarray(vals)[finite],height=.32,color=colors[i] if i==0 else 'none',
                      edgecolor=colors[i],hatch='///' if i else None,
                      xerr=[np.asarray(lo)[finite],np.asarray(hi)[finite]] if metric!='compression_ratio' and not average else None,
                      error_kw={'elinewidth':.7,'capsize':1.7,'ecolor':'#3b4653'})
            for j,v in enumerate(vals):
                if not np.isfinite(v):
                    axis.text(.01,yy[j], 'N/A',transform=axis.get_yaxis_transform(),fontsize=6.5,color='#8a6550',va='center')
        if metric=='compression_ratio':axis.axvline(1,color='#919aa6',linestyle='--',linewidth=.8)
        else:axis.set_xscale('log')
        axis.set_xlabel(label);axis.grid(axis='x',alpha=.17);axis.set_axisbelow(True)
        axis.spines[['top','right']].set_visible(False)
    axes[0].set_yticks(y,names,fontsize=8);axes[0].invert_yaxis()
    fig.suptitle(title,fontsize=12)
    fig.legend(handles=[Patch(facecolor=colors[0],edgecolor=colors[0],label=lives[0]),
                        Patch(facecolor='none',edgecolor=colors[1],hatch='///',label=lives[1])],
               loc='upper right',ncols=2,frameon=False,bbox_to_anchor=(.99,.98))
    fig.tight_layout(rect=[0,0,1,.94])
    path.parent.mkdir(parents=True,exist_ok=True)
    fig.savefig(path.with_suffix('.png'),dpi=145,bbox_inches='tight')
    fig.savefig(path.with_suffix('.svg'),bbox_inches='tight')
    plt.close(fig)


def table(pairs):
    lines=['| codec | 完整输出 bytes P / F | 压缩倍数 P / F | 编码 MiB/s P / F | 解码 MiB/s P / F | 有效批次 P / F |',
           '|---|---:|---:|---:|---:|---:|']
    for name,pair in sorted(pairs.items()):
        values=[]
        for metric in ('codec_complete_bytes_median',*METRICS):
            values.append(' / '.join(number(pair[l].get(metric)) if l in pair and pair[l]['complete_case'] else '—' for l in LIVES))
        counts=' / '.join(f"{pair[l]['ok_primary_trials']}/{pair[l]['planned_trials']}" if l in pair else '未运行' for l in LIVES)
        lines.append('| '+name+' | '+' | '.join(values)+' | '+counts+' |')
    rejected=[]
    for name,pair in sorted(pairs.items()):
        for life,row in pair.items():
            if not row['complete_case']:
                reason=row.get('reason') or row.get('performance_invalidity_reason') or row.get('primary_reasons') or row.get('primary_trial_status_counts')
                rejected.append(f'- `{name}` / {life}：{row["case_status"]}，{str(reason).replace(chr(10)," ")}')
    return lines+(['','拒绝或未完整完成的请求：','']+rejected if rejected else [])+['']


def support_figures(rows, design, output):
    from matplotlib.colors import ListedColormap
    names=[r['id'] for r in design['selected']]
    codecs=design['codecs']
    cells=defaultdict(list)
    for row in rows:
        if row['lifecycle']=='prepared' and not row['domain_supplement']:
            cells[(row['codec'],Path(row['source_file']).stem)].append(row)
    slugs=[]
    for page,start in enumerate(range(0,len(names),18),1):
        sources=names[start:start+18]
        values=np.zeros((len(codecs),len(sources)),dtype=int)
        fig,ax=plt.subplots(figsize=(15,15))
        for i,codec in enumerate(codecs):
            for j,source in enumerate(sources):
                requested=cells[(codec,source)];valid=sum(r['complete_case'] for r in requested)
                values[i,j]=2 if valid and valid==len(requested) else 1 if valid else 0
        ax.imshow(values,cmap=ListedColormap(['#f0ddd3','#efd199','#318b81']),vmin=0,vmax=2,aspect='auto')
        for i,codec in enumerate(codecs):
            for j,source in enumerate(sources):
                rs=cells[(codec,source)]
                ax.text(j,i,f'{sum(r["complete_case"] for r in rs)}/{len(rs)}',ha='center',va='center',fontsize=6.5)
        ax.set_xticks(range(len(sources)),sources,rotation=65,ha='right',fontsize=7)
        ax.set_yticks(range(len(codecs)),codecs,fontsize=8)
        ax.set_title(f'Observed support / prepared / page {page}\nvalid / requested; f64, f32, exact integer and records tasks retained separately in tables')
        fig.legend(handles=[Patch(facecolor=c,label=t) for c,t in [('#f0ddd3','No complete result'),('#efd199','Some requests complete'),('#318b81','Every request complete')]],loc='lower center',ncols=3,frameon=False)
        fig.tight_layout(rect=[0,.04,1,1]);slug=f'support-{page}'
        fig.savefig(output/'figures'/(slug+'.png'),dpi=145,bbox_inches='tight')
        fig.savefig(output/'figures'/(slug+'.svg'),bbox_inches='tight');plt.close(fig);slugs.append(slug)
    return slugs


def fast_overview(rows, output):
    sources=['ETTh1','Weather','ILI','PEMS04','Electricity']
    codecs=['lz4-frame','snappy-raw','zstd-frame']
    cells={(Path(r['source_file']).stem,r['codec']):r for r in rows
           if r['dtype']=='<f8' and r['kind']=='values' and r['fidelity']=='bitwise'
           and r['lifecycle']=='prepared' and r['codec'] in codecs}
    if not all(k in cells and cells[k]['complete_case'] for k in ((s,c) for s in sources for c in codecs)):
        return False
    fig,axes=plt.subplots(1,3,figsize=(16,5.5),sharey=True)
    y=np.arange(len(sources))
    for ax,metric,label in zip(axes,METRICS,['Compression ratio (x)','Encode (MiB/s)','Decode (MiB/s)']):
        for i,(codec,color) in enumerate(zip(codecs,['#0072b2','#e69f00','#009e73'])):
            ax.barh(y+(i-1)*.25,[cells[(s,codec)][metric] for s in sources],height=.23,color=color,label=codec)
        if metric=='compression_ratio':ax.axvline(1,color='gray',linestyle='--',linewidth=.8)
        else:ax.set_xscale('log')
        ax.set_xlabel(label);ax.grid(axis='x',alpha=.17);ax.set_axisbelow(True)
    axes[0].set_yticks(y,sources);axes[0].invert_yaxis()
    axes[-1].legend(loc='best',frameon=False,fontsize=8)
    fig.suptitle('Five complete representative files / prepared / f64 C / bitwise')
    fig.tight_layout(rect=[0,0,1,.94])
    for suffix in ['png','svg']:fig.savefig(output/'figures'/('fast-codecs-overview.'+suffix),dpi=145,bbox_inches='tight')
    plt.close(fig)
    return True


def generate(design_path, output, allow_incomplete=False):
    design_path=Path(design_path).resolve();output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    design=json.loads(design_path.read_text())
    # Bind the selected source and prepared numeric bytes to the frozen design.
    for row in design['selected']+design.get('domain_supplements',[]):
        assert hashlib.file_digest(Path(row['source']).open('rb'),'sha256').hexdigest()==row['source_sha256']
        assert file_hash(row['npy'])==row['npy_sha256']
    for item in design['typed_inputs']:assert file_hash(item['path'])==item['sha256']
    for item in design.get('record_inputs',[]):assert file_hash(item['path'])==item['sha256']
    amendment_paths={Path(path) for path in design.get('execution_amendments',[])}
    parallel_path=design_path.parent/'amendments/parallel-light/amendment.json'
    parallel=json.loads(parallel_path.read_text()) if parallel_path.exists() else None
    if parallel:
        amendment_paths.add(parallel_path)
        amendment_paths.update(parallel_path.parent.glob('host_readback.json'))
        if not allow_incomplete:
            assert any(e['event']=='parallel_complete' for e in parallel['events'])
            assert len(parallel['runs'])==24 and all(r['complete'] and r['returncode']==0 for r in parallel['runs'])
        write_json(output/'parallel_schedule.json',parallel)
    amendments=[identity(path) for path in sorted(amendment_paths)]
    all_rows=[];audits=[]
    for entry in design['configurations']:
        assert file_hash(entry['path'])==entry['sha256']
        rows,evidence=audit(entry,allow_incomplete)
        all_rows.extend(rows)
        if evidence:audits.append(evidence)
    all_rows.sort(key=lambda r:(r['dataset_id'],r['fidelity'],r['profile_id'],r['codec'],r['lifecycle']))
    object_ids=defaultdict(set)
    for row in all_rows:
        if row['raw_object_id'] is not None:object_ids[row['dataset_id']].add(row['raw_object_id'])
    assert all(len(ids)==1 for ids in object_ids.values()), 'input differs across codecs or lifecycles'
    gpu_rows=[];gpu_audits=[]
    if design.get('gpu_configurations') and (not allow_incomplete or all((Path(e['run'])/'summary.json').exists() for e in design['gpu_configurations'])):
        from forecasting_gpu_results import audit_gpu
        gpu_rows,gpu_audits=audit_gpu(design,object_ids)
    requested=design['requested_cases'];completed=len(all_rows)
    if not allow_incomplete:assert completed==requested
    columns=['run','dataset_id','codec','method_id','dtype','shape','kind','fidelity','profile_id','lifecycle',
             'recorder_affinity','run_created_at_utc',
             'case_status','reason','complete_case','raw_bytes','codec_complete_bytes_median',
             'compression_ratio','encode_MiB_s','decode_MiB_s','planned_trials','ok_primary_trials','params']
    with (output/'primary.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=columns,extrasaction='ignore');writer.writeheader()
        writer.writerows(all_rows)
    write_json(output/'audit.json',{'design':identity(design_path),'analysis':identity(__file__),
               'analysis_helpers':[identity(ROOT/'benchmark/tools/forecasting_gpu_results.py')] if gpu_rows else [],
               'execution_amendments':amendments,
               'gpu_runs':gpu_audits,'gpu_audited_requests':len(gpu_rows),
               'analysis_runtime':{'python':sys.version,'numpy':np.__version__,'matplotlib':matplotlib.__version__},'runs':audits,
               'audited_requests':completed,'planned_requests':requested,
               'cross_codec_and_lifecycle_input_ids':{k:sorted(v) for k,v in object_ids.items()},
               'verified_formal_product_pairs':sum(x['verified_products'] for x in audits),
               'artifact_policy':'Every warmup and timed product validated outside clocks; formal product hashes retained in observations; representative exact qualification payloads persisted, repeated formal payload bytes not archived.'})
    by_source=defaultdict(lambda:defaultdict(lambda:defaultdict(dict)))
    for row in all_rows:
        source=Path(row['source_file']).stem
        key=(row['dataset_id'],row['dtype'] or 'unknown',row['fidelity'],row['kind'],row['profile_id'])
        by_source[source][key][method_label(row)][row['lifecycle']]=row
    datestr=datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S')+'（Asia/Shanghai，UTC+08:00）'
    good=sum(r['complete_case'] for r in all_rows)
    trials=sum(x['planned_trials'] for x in audits)
    ok=sum(x['status_counts'].get('ok',0) for x in audits)
    stamp=design_path.parent.name.replace('forecasting-','')
    (output/'figures').mkdir(exist_ok=True)
    report=output/('visual_report_'+stamp+'.md')
    lines=['# forecasting_transpose 压缩算法可视化报告','',f'生成时间：{datestr}。',
           '',f'选自 **8,093 个 CSV、53 个数据家族的 53 个代表文件**；每个代表文件使用全部行、全部数值列。完整 float64 主输入未截断、填补、归一化或额外量化；补充 dtype 任务单独声明。',
           '',f'当前 **42 个 CPU codec**（排除 `lzss-raw`、`lzss-dipperstein-c`；不含 raw-store 基线）；冻结 **{requested:,} 个请求**，已审计 {completed:,} 个，完整有效 {good:,} 个，正式批次 {ok:,}/{trials:,} 成功。'+(' **本文件为进度报告，尚未完成全设计。**' if completed!=requested else ''),
           '', '[平均结果](#averages) · [逐数据集结果](#datasets) · [算法覆盖](#coverage) · [GPU结果](#gpu) · [统计口径与复现](#methodology)',
           '', '[逐案例 CSV](primary.csv) · [审计证据](audit.json) · [冻结选样和配置](../../benchmark/experiments/'+design_path.parent.name+'/design.json)',
           '', '以下CPU图的压缩倍数 = 有效原始 bytes / 完整 codec 输出 bytes；编码、解码按相同原始 bytes 归一化为 MiB/s。完整输出包含 codec 必要参数、模型和结束数据；实验管理 JSON、hash 不计入。实心为 prepared，斜线为空心 fresh_request；吞吐使用对数轴，误差线由批次时长的 Q3/Q1 反算。GPU采用独立对象边界和完整object wire，见GPU章节，不混合比较。1×虚线表示膨胀分界。N/A 表示拒绝、缺失或未完整完成，不能解释为零性能。',
           '', '<a id="averages"></a>','', '## 平均结果','',
           '每个数据家族等权；先取每案例 14 个正式批次时长的中位数，再反算吞吐并对固定家族集合求算术平均。某 codec 缺少任一家族的完整有效结果，则其该组均值为 N/A。不同 dtype、质量任务及线程配置不合并。均值不使用成功子集替代固定集合，也不是合并所有文件后的总吞吐或总字节比。'+(' 本轮包含顺序和隔离核心并行两种调度条件；均值描述本次混合调度，不代表统一独占条件下的性能，详见调度记录。' if parallel else ''),'']
    gpu_path=design_path.parent/'gpu_availability.json'
    if gpu_path.exists():
        gpu=json.loads(gpu_path.read_text())
        gpu_text=('GPU 扩展 `cuSZp-fixed-1d`：本轮宿主机测量结果见独立的 [GPU章节](#gpu)，不与CPU native_core结果混合排名。' if gpu_rows else
                  'GPU 扩展 `cuSZp-fixed-1d`：宿主机可用，等待CPU结束后的独立GPU测量。' if gpu.get('status')=='available_pending_build' else
                  'GPU 扩展 `cuSZp-fixed-1d`：当前不可用，原因见可用性检查，未使用历史GPU结果代替。')
        lines[lines.index('<a id="averages"></a>'):lines.index('<a id="averages"></a>')]=[
            gpu_text,
            '', '[GPU 可用性检查](../../benchmark/experiments/'+design_path.parent.name+'/gpu_availability.json)','']
    if design.get('domain_supplements'):
        insert=next(i for i,s in enumerate(lines) if s.startswith('当前 **42'))+2
        lines[insert:insert]=['另加 1 个完整文件作为 DeepZip 原生符号域补充，单独展示，不改变 53 个代表文件的平均分母。该补充在正式测量前，按符合 0..3 符号域的 4 个完整文件取下中位选出。','']
    if gpu_rows:
        insert=next(i for i,s in enumerate(lines) if s.startswith('当前 **42'))+2
        gpu_good=sum(r['complete_case'] for r in gpu_rows)
        lines[insert:insert]=[f'另有 **1 个 GPU codec（cuSZp）**：已审计 {len(gpu_rows)} 个请求，完整有效 {gpu_good} 个。本页合计 **43 个算法、{completed+len(gpu_rows):,} 个请求、{good+gpu_good:,} 个完整有效案例**；CPU与GPU的计时、存储边界分别声明。','']
    if fast_overview(all_rows,output):
        insert=lines.index('<a id="averages"></a>')
        lines[insert:insert]=['## 通用快速编码器概览','','五个预先指定的完整代表文件，prepared、float64、无损；完整算法与 fresh_request 结果见后文。','',
                             '![快速编码器概览](figures/fast-codecs-overview.png)','','[SVG](figures/fast-codecs-overview.svg)','']
    average_groups=defaultdict(list)
    for row in all_rows:
        if not row['domain_supplement']:
            average_groups[(row['dtype'] or 'unknown',row['fidelity'],row['kind'],row['profile_id'])].append(row)
    input_dtypes={row['id']+'-f64':'<f8' for row in design['selected']}
    input_dtypes.update({row['id']+'-records':'<f8' for row in design['selected']})
    input_dtypes.update({row['id']:row['dtype'] for row in design['typed_inputs']})
    intended=defaultdict(set)
    for entry in design['configurations']:
        if entry['group'].startswith('domain-supplement'):
            continue
        config=tomllib.loads(Path(entry['path']).read_text())
        profile=config['profiles'][0]['id']
        for dataset in config['datasets']:
            intended[(input_dtypes[dataset['id']],entry['fidelity'],entry['kind'],profile)].add(dataset['id'])
    for index,(key,members) in enumerate(sorted(average_groups.items())):
        dtype,fidelity,kind,profile=key
        required=intended[key]
        pairs=defaultdict(dict)
        codecs=sorted(set(method_label(r) for r in members))
        for codec in codecs:
            for life in LIVES:
                rs=[r for r in members if method_label(r)==codec and r['lifecycle']==life]
                complete=(len(rs)==len(required) and all(r['complete_case'] for r in rs))
                pairs[codec][life]={'complete_case':complete,**{m:float(np.mean([r[m] for r in rs])) if complete and all(r[m] is not None for r in rs) else None for m in METRICS},
                                    'valid':sum(r['complete_case'] for r in rs),'required':len(required)}
        # Avoid an entire large chart containing only N/A rows.
        drawable={c:p for c,p in pairs.items() if any(r['complete_case'] for r in p.values())}
        title=f'{dtype} / {fidelity} / {kind} / {profile} / {len(required)} families'
        lines += [f'### {dtype} · {KINDS.get(fidelity,fidelity)} · {kind} · {profile}', '']
        if drawable:
            slug=f'mean-{index:02d}';chart(drawable,title,output/'figures'/slug,average=True)
            lines += [f'![{title}](figures/{slug}.png)','',f'[SVG](figures/{slug}.svg)','']
        lines += ['<details><summary>均值及覆盖分母</summary>','',
                  '| codec | 有效／固定家族数 P / F | 平均压缩倍数 P / F | 平均编码 MiB/s P / F | 平均解码 MiB/s P / F |',
                  '|---|---:|---:|---:|---:|']
        for codec,pair in sorted(pairs.items()):
            count=' / '.join(f'{pair[l]["valid"]}/{pair[l]["required"]}' for l in LIVES)
            values=[' / '.join(number(pair[l][m]) for l in LIVES) for m in METRICS]
            lines.append('| '+codec+' | '+count+' | '+' | '.join(values)+' |')
        lines += ['','</details>','']
    lines += ['<a id="datasets"></a>','','## 逐数据集结果','',
              '选样规则：文件名在 `_dataset` 前的前缀作为家族；其余名称去掉末尾 `_数字`。每家族按（完整数值元素数量、文件名）排序后取下中位文件。大写 Weather 与小写 weather 分别保留为不同来源家族。所有选择在正式运行前冻结。', '',
              '| 家族 | 家族文件数 | 代表文件 | 原始 f64 shape | 有效数值 bytes |', '|---|---:|---|---|---:|']
    for row in design['selected']:
        lines.append(f'| {row["family"]} | {row["family_file_count"]} | [{row["id"]}](#dataset-{row["id"]}) | {row["shape"]} | {row["raw_bytes"]:,} |')
    lines.append('')
    for row in design.get('domain_supplements',[]):
        lines += [f'算法域补充：`{row["id"]}`，完整 shape `{row["shape"]}`，原始 f64 数值 bytes {row["raw_bytes"]:,}；仅按原值精确转换为 u8 后测试 DeepZip，不离散化、不重编号。','']
    conversion={r['id']:r for r in design['typed_inputs']}
    for source,groups in sorted(by_source.items()):
        lines += [f'<a id="dataset-{source}"></a>','',f'### {source}','']
        for index,(key,pairs) in enumerate(sorted(groups.items())):
            dataset,dtype,fidelity,kind,profile=key
            sample=next(iter(next(iter(pairs.values())).values()))
            title=f'{dataset} / {fidelity} / {kind} / {profile}'
            lines += [f'**{dtype} · {sample["shape"]} · {KINDS.get(fidelity,fidelity)} · {kind} · {profile}**','']
            if parallel:
                affinities={life:sorted({tuple(r['recorder_affinity'] or []) for pair in pairs.values() for l,r in pair.items() if l==life}) for life in LIVES}
                lines += [f'运行进程 CPU 亲和性（P / F）：`{affinities["prepared"]}` / `{affinities["fresh_request"]}`；逐配置创建时间见 CSV，是否处于并行窗口见调度记录。','']
            if dtype=='<f4' and dataset in conversion:
                error=conversion[dataset]['source_conversion_max_abs']
                lines += [f'f64→f32 准备阶段转换的最大绝对差：**{error:.9g}**；本组 codec 的恢复质量相对转换后的 f32 输入验证。','']
            drawable={c:p for c,p in pairs.items() if any(r['complete_case'] for r in p.values())}
            if drawable:
                slug=f'{dataset}--{fidelity}--{profile}';chart(drawable,title,output/'figures'/slug)
                lines += [f'![{title}](figures/{slug}.png)','',f'[SVG](figures/{slug}.svg)','']
            lines += ['<details><summary>完整数值、有效批次及拒绝原因</summary>','']+table(pairs)+['</details>','']
    lines += ['<a id="coverage"></a>','','## 算法覆盖','',
              '| codec | 请求数 | 完整有效数 | 拒绝／未完整数 |', '|---|---:|---:|---:|']
    for codec in design['codecs']:
        rs=[r for r in all_rows if r['codec']==codec];valid=sum(r['complete_case'] for r in rs)
        lines.append(f'| {codec} | {len(rs)} | {valid} | {len(rs)-valid} |')
    if not allow_incomplete:
        lines += ['', '下图是本轮 prepared 请求的实测覆盖：每格为有效／请求数，包含分别声明的 dtype 与 T+V 任务。部分有效不代表该算法对整个原始 f64 文件提供无损支持。','']
        for slug in support_figures(all_rows,design,output):
            lines += [f'![实测能力支持矩阵](figures/{slug}.png)','',f'[SVG](figures/{slug}.svg)','']
    lines += ['', 'DeepZip 固定模型仅支持 0..3 符号，DZip 要求其原生符号域；未对原始连续数值任意离散化或重新编号。不满足输入域时保留拒绝，不能把请求覆盖写成性能有效覆盖。',
              '', '<a id="methodology"></a>','','## 统计口径与复现','',
              '- 主任务为全部数值列的 float64 C-order；CSV 的 date 不计入 V-only 原始 bytes。单数值列保留 rank1，多列保留 rank2，未隐式 flatten、分列或分块。',
              '- float32 是单独声明的输入精度任务；其无损只针对转换后的 f32 bits，不代表原 float64 无损。转换误差在冻结设计 typed_inputs 中记录。整数仅对有限、全为整数且范围适配的数据精确转换，并检查转回 f64 完全相等。整数任务吞吐分母按自身 itemsize 计算。',
              '- Gorilla T+V 仅使用原文件本来就是单变量的代表文件，保留所有行；datetime 转为 int64 纳秒，原数字索引保持原整数值且不假称物理时间。多变量文件不选取单列冒充整文件。',
              '- 无损、ABS≤0.01 与经验质量分别报告；filter epsilon=0.1、quality_mode=compatible。误差数值可在原始 summary.json 的 quality 中读取。缺失、NaN、超范围和超大小限制不修补，不支持时保留原因。',
              '- Quantized 的 compatible 模式按源码保留单点斜率溢出，资格检查发现非有限恢复后，另加注册表默认的 strict_abs 模式作为独立补充条件；它拒绝不满足实际恢复检查的帧。该补充在观察资格失败后冻结，原 compatible 失败完整保留，两种参数不混合统计。',
              '- 每案例 2 sessions × 7 rounds；≤128 KiB 的基础 f64 文件每批 8 次计时内循环、2 次 warmup，其余整文件每批 1 次计时内循环、1 次 warmup。DZip 和 Quantized strict_abs 独立补充统一使用1次计时、1次warmup。内循环不当独立样本。',
              '- DZip 时长修订：完整10,898点输入的资格检查显示单次编码/解码约48秒，在尚无正式DZip结果时，将双生命周期内部批次由8计时+2预热调整为1计时+1预热；14个正式批次、输入内容和线程配置均保留。原配置及原资格记录未删除，修改前设计与理由见冻结目录的 amendments/dzip-duration/amendment.json。',
              '- Python 仅调度、准备和校验；CLOCK_MONOTONIC 位于原生 driver 内。每次 warmup 和正式产物均在主时钟外验证恢复和输入不变性；每案例 exact 资格包含独立 decoder 恢复。',
              '- prepared 与 fresh_request 分开；CPU 单线程，DZip 按实际 caller+2 workers 单列。'+('按用户要求加入 Wind、ZafNoo 两条独立核心辅助队列，主队列与辅助队列可并行；具体时间及亲和性见下方调度记录。' if parallel else '每次只测一个配置，不并行测量其他 codec。')+'正式重复产物保留 hash 与验证记录，exact 资格保存代表 payload，不保存所有重复 payload 的字节副本。',
              '- 图中误差线为时长四分位数换算的描述区间，不是置信区间；53 个家族是本地语料选择，不据此推断独立物理总体或跨任务总排名。','',
              '```bash', f'PYTHONPATH=benchmark/src python benchmark/tools/forecasting_benchmark.py run benchmark/experiments/{design_path.parent.name}',
              f'python benchmark/tools/report_forecasting_results.py {design_path} --output {output}', '```','']
    if parallel:
        starts=[e['at'] for e in parallel['events'] if e['event']=='parallel_started']
        ends=[e['at'] for e in parallel['events'] if e['event']=='parallel_complete']
        lines += ['### 并行调度记录','',
                  f'并行开始：{starts[0] if starts else "等待当前配置结束"}；辅助队列结束：{ends[-1] if ends else "尚未结束"}。',
                  '',f'Wind 使用 CPU 12，ZafNoo 使用 CPU 13；两者为无 SMT 兄弟的独立物理核心。并行期间主调度进程允许核心为 `{parallel["main_parallel_affinity"]}`；已有主配置在原核心条件下完成后才启动辅助测量。辅助结束后恢复主调度父进程的原亲和性；当时正在运行的配置保留已继承的核心集合，后续新配置继承恢复后的集合，逐配置实际值见 CSV。所有输入、codec 参数、生命周期和正式重复次数保持冻结值。',
                  '', '各队列共享末级缓存、内存带宽和整机功耗预算，固定核心与可迁移核心集合的条件也不同；核心隔离不能消除这些影响。此前顺序结果与并行期间结果具有不同运行条件，吞吐及跨家族均值应结合调度记录解读。',
                  '', '[完整调度与逐配置时间](parallel_schedule.json) · [宿主机亲和性及拓扑核验](../../benchmark/experiments/'+design_path.parent.name+'/amendments/parallel-light/host_readback.json)',
                  '', '| 辅助配置 | CPU | 开始 | 结束 | 状态 |', '|---|---:|---|---|---|']
        for run in parallel['runs']:
            lines.append(f'| {Path(run["configuration"]).stem} | {run["cpu"]} | {run["started_at"]} | {run["ended_at"]} | {"完成" if run["complete"] else "失败"} |')
        lines.append('')
    if gpu_rows:
        from forecasting_gpu_results import report_gpu
        insert=lines.index('<a id="methodology"></a>')
        lines[insert:insert]=report_gpu(gpu_rows,gpu_audits,output,chart,number)
    report.write_text('\n'.join(lines),encoding='utf-8')
    print(report)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('design',type=Path);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--allow-incomplete',action='store_true')
    args=parser.parse_args()
    generate(args.design,args.output,args.allow_incomplete)

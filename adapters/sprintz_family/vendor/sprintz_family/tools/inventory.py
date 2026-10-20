from pathlib import Path
import re,json,hashlib
p=Path(__file__).resolve().parents[1];s=p.parent.parent/'Source/sprintz-family'
rows=[]
for f in sorted((s/'upstream/core').iterdir()):
 if not f.is_file():continue
 name=f.name
 if name.startswith(('sprintz_delta_rle_query','sprintz_xff_rle_query')): scope='QUERY_RESEARCH_ONLY_NOT_SAFE_ABI'
 elif name.startswith(('sprintz','format','bitpack','util','traits','transpose','macros','debug_utils','query')):scope='REQUIRED_CORE_OR_SUPPORT'
 elif name.startswith(('delta','predict','univariate')):scope='ABLATION_NATIVE_DIAGNOSTIC'
 elif name.startswith('entropy'):scope='INCOMPLETE_KAYAK_NOT_HUFFMAN'
 elif name.startswith(('online','nn_','search')):scope='EXPERIMENTAL_AUXILIARY_NOT_SAFE_ABI'
 else:scope='UPSTREAM_TEST_RUNNER'
 text=f.read_text(errors='replace'); funcs=sorted(set(re.findall(r'\b(?:int64_t|uint64_t|void|int|uint16_t)\s+([A-Za-z_]\w*)\s*\(',text)))
 rows.append({'file':name,'scope':scope,'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'symbols':funcs})
(p/'docs/SOURCE_CAPABILITY_INVENTORY.json').write_text(json.dumps(rows,indent=2)+'\n')
lz=(s/'upstream/lzbench/_lzbench/lzbench.h').read_text();r=[]
for line in lz.splitlines():
 if re.search(r'\{\s*"(?:spr|sprintz)',line):
  r.append({'registration':line.strip(),'status':'REQUIRED_MAIN_OR_ABLATION' if not any(x in line for x in ['Zstd','zstd','bz2','FSE','Query','1d','sprDelta2','sprDeltaRLE','sprJust','sprFixed']) else 'EXPERIMENTAL_OR_OTHER_PIPELINE_NOT_SAFE_ABI'})
(p/'docs/LZBENCH_REGISTRATIONS.json').write_text(json.dumps(r,indent=2)+'\n')
print('core files',len(rows),'registrations',len(r))

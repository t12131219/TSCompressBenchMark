from pathlib import Path
import hashlib,json
p=Path(__file__).resolve().parents[1];src=(p.parent.parent/'Source/sprintz-family/upstream/lzbench/_lzbench/compressors.cpp').read_text();chunks=[];ranges=[]
for name in ['lzbench_huff0_compress','lzbench_huff0_decompress']:
 start=src.index('int64_t '+name+'(');op=src.index('{',start);depth=1;i=op+1
 while depth:
  if src[i]=='{':depth+=1
  if src[i]=='}':depth-=1
  i+=1
 chunk=src[start:i];chunks.append(chunk);ranges.append({'symbol':name,'start_line':src[:start].count('\n')+1,'end_line':src[:i].count('\n')+1,'body_sha256':hashlib.sha256(chunk.encode()).hexdigest()})
text='#include <cstdint>\n#include <cstddef>\n#include <cstdio>\n#include <cstdlib>\n#include <cstring>\nextern "C" {\n#include "huf.h"\n#include "error_private.h"\n}\n'+'\n'.join(chunks)+'\n'
assert text==(p/'tools/source_huff.cpp').read_text(),'Oracle driver differs from exact source function extraction'
(p/'evidence/oracle_extraction.json').write_text(json.dumps(ranges,indent=2)+'\n')
print('oracle function extraction PASS')

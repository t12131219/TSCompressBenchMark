"""Extract the delivered Archify SVG; resolve its classic theme without a browser."""
from pathlib import Path
import re
import xml.etree.ElementTree as ET
root=Path(__file__).resolve().parent
html=(root/'framework.html').read_text()
svg=re.search(r'<svg\b[\s\S]*?</svg>',html).group()
width,height=map(int,re.search(r'viewBox="0 0 (\d+) (\d+)"',svg).groups())
css='\n'.join(re.findall(r'<style(?:\s[^>]*)?>([\s\S]*?)</style>',html))
for theme in ('light','dark'):
    variables=re.search(r'\[data-theme="'+theme+r'"\]\s*\{([^}]+)\}',css).group(1)
    values=dict(re.findall(r'(--[\w-]+)\s*:\s*([^;]+);',variables))
    rules=[]
    for selector,body in re.findall(r'([^{}]+)\{([^{}]*)\}',css):
        selector=selector.strip().split('*/')[-1].strip()
        if re.fullmatch(r'\.(?:c|t|a|m|s)-[\w-]+',selector) or selector.startswith('svg .semantic-sigil') or re.fullmatch(r'svg \.s-[\w-]+',selector):
            rules.append(selector+'{'+re.sub(r'var\((--[\w-]+)\)',lambda m:values.get(m[1],'#64748b'),body)+'}')
    font='text{font-family:"Noto Sans CJK SC",sans-serif}'
    exported=svg.replace('<svg ','<svg xmlns="http://www.w3.org/2000/svg" width="'+str(width)+'" height="'+str(height)+'" data-theme="'+theme+'" ',1)
    exported=exported.replace('<!-- Definitions -->','<style>'+font+'\n'+''.join(rules)+'</style><rect width="'+str(width)+'" height="'+str(height)+'" fill="'+values['--bg']+'"/><!-- Definitions -->',1)
    ET.fromstring(exported)
    (root/('framework.'+theme+'.svg')).write_text(exported)
print('Extracted light/dark SVGs from the unchanged delivered HTML.')

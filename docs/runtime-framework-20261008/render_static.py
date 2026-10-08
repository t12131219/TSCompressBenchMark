"""Extract delivered SVGs for supplementary static previews, not browser evidence."""
from pathlib import Path
import re
import subprocess

OUT=Path(__file__).resolve().parent
for path in sorted(OUT.glob('[0-9][0-9]-*.html')):
    if '.' in path.stem:
        continue
    document=path.read_text()
    svg=re.search(r'<svg\b.*?</svg>',document,re.S).group()
    css=re.findall(r'<style[^>]*>(.*?)</style>',document,re.S)[1]
    theme=re.search(r'\[data-theme="dark"\]\s*\{(.*?)\}',css,re.S).group(1)
    variables=dict(re.findall(r'(--[\w-]+)\s*:\s*([^;]+);',theme))
    classes={name for group in re.findall(r'class="([^"]+)"',svg) for name in group.split()}
    rules=[]
    for name in classes:
        match=re.search(r'(?m)^\s*\.'+re.escape(name)+r'\s*\{([^}]+)\}',css)
        if match:
            value=re.sub(r'var\((--[\w-]+)\)',lambda m:variables.get(m[1],'#94a3b8'),match[1])
            rules.append('.'+name+'{'+value+'}')
    rules.append('text{font-family:"Noto Sans CJK SC",sans-serif}.semantic-sigil{fill:none;stroke:#94a3b8;stroke-width:1.5}.sigil-fill{fill:#94a3b8;stroke:none}')
    svg=svg.replace('<svg ','<svg xmlns="http://www.w3.org/2000/svg" width="1150" height="755" ',1)
    end=svg.index('>')+1
    svg=svg[:end]+'<style>'+''.join(rules)+'</style><rect width="1150" height="755" fill="'+variables['--bg']+'"/>'+svg[end:]
    target=path.with_suffix('.diagram.svg')
    target.write_text(svg)
    subprocess.run(['rsvg-convert','-w','1725','-o',str(path.with_suffix('.diagram.png')),str(target)],check=True)
print('22 supplementary static previews generated.')

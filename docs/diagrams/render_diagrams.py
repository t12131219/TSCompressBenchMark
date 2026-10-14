"""Render the V4 plan diagrams as SVG; requires Pillow and Noto Sans CJK.

Run this script, then use rsvg-convert to produce the PNG previews.
This is a documentation generator; it does not execute benchmark codecs.
"""
from pathlib import Path
from html import escape
from PIL import ImageFont

OUT = Path(__file__).resolve().parent
OUT.mkdir(parents=True, exist_ok=True)
FONT_PATH = '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
INK = '#17324d'
MUTED = '#536579'
EDGE = '#64748b'
BLUE = '#2467a9'
TEAL = '#14786c'
PURPLE = '#7655a5'
RED = '#b45346'
PALE = {'blue':'#edf5ff','teal':'#edf8f5','purple':'#f5f0fb','gray':'#f5f7fa','red':'#fff2ed'}
STROKE = {'blue':'#8eb6de','teal':'#88beb1','purple':'#bba5d7','gray':'#b8c5d2','red':'#d9a495'}

class Canvas:
    def __init__(self, width, height, title, subtitle):
        self.width, self.height = width, height
        self.bg, self.edges, self.boxes, self.labels = [], [], [], []
        self.metrics = []
        self.text(56, 60, title, 34, weight=600)
        self.text(56, 99, subtitle, 21, color=MUTED)
    def text(self, x, y, value, size=20, color=INK, anchor='start', weight=400):
        value = str(value)
        self.labels.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" text-anchor="{anchor}" font-weight="{weight}">{escape(value)}</text>')
    def group(self, x, y, width, height, title):
        self.bg.append(f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="18" fill="#fcfdff" stroke="#c5d1de" stroke-width="1.8"/>')
        self.text(x+24, y+34, title, 24, weight=600)
    def wrap(self, s, max_width, size):
        font = ImageFont.truetype(FONT_PATH, size)
        lines, line = [], ''
        for ch in s:
            if font.getlength(line+ch) > max_width and line:
                lines.append(line)
                line = ch
            else:
                line += ch
        if line:
            lines.append(line)
        return lines or ['']
    def node(self, x, y, width, height, title, lines=(), kind='blue', dashed=False, title_size=24, body_size=20):
        dash = ' stroke-dasharray="8 6"' if dashed else ''
        self.boxes.append(f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="12" fill="{PALE[kind]}" stroke="{STROKE[kind]}" stroke-width="2"{dash}/>')
        title_lines = self.wrap(title, width-40, title_size)
        body_lines = []
        for s in lines:
            body_lines.extend(self.wrap(s, width-40, body_size))
        total_height = len(title_lines)*(title_size+9) + len(body_lines)*(body_size+8)
        assert total_height <= height-10, (title, height, total_height)
        ty = y + (height-total_height)/2 + title_size
        for line in title_lines:
            self.text(x+width/2, ty, line, title_size, anchor='middle', weight=600)
            ty += title_size+9
        for line in body_lines:
            self.text(x+width/2, ty, line, body_size, color=MUTED, anchor='middle')
            ty += body_size+8
        self.metrics.append((x,y,width,height,title))
    def diamond(self, x, y, width, height, title):
        pts = f'{x+width/2},{y} {x+width},{y+height/2} {x+width/2},{y+height} {x},{y+height/2}'
        self.boxes.append(f'<polygon points="{pts}" fill="#f4f0fb" stroke="#bba5d7" stroke-width="2"/>')
        self.text(x+width/2, y+height/2+8, title, 23, anchor='middle', weight=600)
        self.metrics.append((x,y,width,height,title))
    def arrow(self, points, color=EDGE, dashed=False, label=None, label_at=None, both=False):
        commands = 'M ' + ' L '.join(f'{x} {y}' for x,y in points)
        dash = ' stroke-dasharray="8 6"' if dashed else ''
        start = f' marker-start="url(#arrow-{color[1:]})"' if both else ''
        self.edges.append(f'<path d="{commands}" fill="none" stroke="{color}" stroke-width="2.4" stroke-linejoin="round" marker-end="url(#arrow-{color[1:]})"{start}{dash}/>')
        if label:
            lx,ly = label_at
            label_width = ImageFont.truetype(FONT_PATH,19).getlength(label) + 16
            self.boxes.append(f'<rect x="{lx-label_width/2}" y="{ly-21}" width="{label_width}" height="26" rx="4" fill="#ffffff"/>')
            self.text(lx,ly,label,19,color=color,anchor='middle')
    def write(self, filename):
        defs = ''.join(f'<marker id="arrow-{color[1:]}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="{color}"/></marker>' for color in [EDGE,BLUE,TEAL,PURPLE,RED])
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" height="{self.height}" viewBox="0 0 {self.width} {self.height}" role="img"><title>TSBench V4.0 {escape(filename)}</title><desc>依据V4.0计划绘制。CPU对象主路径与cuSZp GPU host/device执行器已实现；进程pool作为独立workload工具。</desc><defs>{defs}</defs><rect width="100%" height="100%" fill="#ffffff"/><g font-family="Noto Sans CJK SC, sans-serif">' + ''.join(self.bg+self.edges+self.boxes+self.labels) + '</g></svg>'
        (OUT/filename).write_text(svg,encoding='utf-8')

c = Canvas(1440,1645,'TSBench 4.0 · 框架模块结构','独立 Python benchmark｜CPU 对象主路径已实施｜pool 为独立工具｜cuSZp GPU host/device 已接入')
for x,title,body in [
    (56,'一份 experiment.toml',['对象 / 方法 / 质量 / 边界 / 资源']),
    (528,'时序数据源',['npy / CSV / source catalog']),
    (1000,'保留的 codec 资产',['源码 / 必要模型 / 真实构建配方'])]:
    c.node(x,145,384,105,title,body,kind='gray')
for x,title,body in [
    (56,'CLI / config',['解析、校验、默认值展开']),
    (528,'data',['canonical V / T / mask 与身份']),
    (1000,'registry / build',['能力、factory、构建库与身份'])]:
    c.node(x,323,384,105,title,body)
    c.arrow([(x+192,250),(x+192,323)],color=BLUE)
    c.arrow([(x+192,428),(x+192,493)],color=BLUE)
c.group(56,493,1328,209,'控制与调度 · 父进程')
c.node(80,551,790,113,'runner',['case 矩阵 / 随机 schedule / 预算 / resume','默认主计时顺序执行；父进程补记异常'])
c.node(925,551,430,113,'资格缓存',['implementation / exact-input','只复用已通过范围'],kind='purple')
c.arrow([(870,608),(925,608)],color=PURPLE,both=True)
c.arrow([(720,702),(720,783)],color=BLUE,label='case / input / library / profile · IPC',label_at=(720,746))
c.group(56,783,1328,548,'隔离 worker · method × resource profile × session')
c.node(80,842,1275,91,'executor：计时边界、生命周期、实际资源与完成',['CPU wall 已实施；pool 独立 workload；cuSZp GPU host/device completion 已实施'],body_size=20)
c.node(80,995,380,113,'scheme / artifact',['适配 / 组合 / Finish / packing','对象 → 完整 wire'],kind='teal')
c.node(570,995,410,113,'DecoderRegistry',['wire → 新 decoder session','逆变换 / 完整恢复 / close'],kind='teal')
c.node(1070,995,285,113,'validate',['恢复 / 原始域质量','输入未改 · 计时外'],kind='gray')
c.arrow([(270,933),(270,995)],color=BLUE,label='encode 计时',label_at=(360,970))
c.arrow([(775,933),(775,995)],color=BLUE,label='decode 计时',label_at=(865,970))
c.arrow([(460,1051),(570,1051)],color=TEAL,label='wire',label_at=(515,1034))
c.arrow([(980,1051),(1070,1051)],color=TEAL,label='恢复对象',label_at=(1025,1034))
c.node(360,1183,620,101,'C / RW / CUDA bridges',['CPU ABI；GPU 独立 opaque owner / 完成 API'])
c.node(1070,1183,285,101,'native codec',['构建库 / 必要模型'],kind='gray')
c.arrow([(270,1108),(270,1148),(470,1148),(470,1183)],color=BLUE)
c.arrow([(775,1108),(775,1183)],color=BLUE,label='调用 codec',label_at=(830,1154))
c.arrow([(980,1234),(1070,1234)],color=BLUE)
c.text(80,1310,'decoder 只从 wire 与已计费依赖恢复；原始对象保留在验证端。',20,color=MUTED)
c.arrow([(1384,1070),(1415,1070),(1415,1364),(450,1364),(450,1442)],color=TEAL,label='worker 结果',label_at=(869,1389))
c.arrow([(56,620),(26,620),(26,1498),(80,1498)],color=RED,dashed=True)
c.group(56,1402,1328,182,'原始记录与独立分析')
c.node(80,1442,420,109,'records / run artifacts',['manifest / JSONL / 代表 wire','worker 结果 + 父进程终态'],kind='gray')
c.node(620,1442,350,109,'report / study',['描述 / 覆盖 / 失败','配对 / source-cluster 统计'],kind='teal')
c.node(1080,1442,275,109,'profiling · 可选',['同 manifest，另开 pass','RSS / 显存 / perf'],kind='purple',dashed=True,title_size=22,body_size=19)
c.arrow([(500,1498),(620,1498)],color=TEAL,label='读取 raw',label_at=(560,1481))
c.arrow([(290,1551),(290,1571),(1217,1571),(1217,1551)],color=PURPLE,dashed=True)
c.arrow([(1080,1498),(970,1498)],color=PURPLE,dashed=True,label='附加结果',label_at=(1025,1481))
c.text(56,1620,'实线：核心关系 / 调用；虚线：独立 profiling 或异常补记。pool 与边界实验另存身份和 raw。',20,color=MUTED)
c.write('architecture.svg')

c = Canvas(1440,2160,'TSBench 4.0 · 一次实验的运行流程','展开比较 block / session 的主路径｜默认 object_memory｜loops = 1｜正式每 trial 都恢复并验证')
main_x,main_w,mid = 88,825,500.5
c.node(main_x,151,main_w,82,'读取一份配置',['数据 / 方法 / 质量 / 边界 / 资源 profile'])
c.node(main_x,279,main_w,113,'展开请求 case 矩阵',['对象与方法身份、支持范围、预算和比较条件'])
c.arrow([(mid,233),(mid,279)],color=BLUE)
c.node(990,279,390,113,'静态不支持 / 缺环境',['保留 case 及原因','unsupported / unavailable'],kind='red',title_size=22)
c.arrow([(913,335),(990,335)],color=RED,label='拒绝',label_at=(951,317))
c.node(main_x,437,main_w,120,'准备方法 / session 的隔离 worker',['pool / 设备初始化 / first-touch 前落实资源政策','加载库与当前 block，核验有效资源；不符则拒绝或另分层'])
c.arrow([(mid,392),(mid,437)],color=BLUE,label='可执行候选',label_at=(mid,420))
c.diamond(168,617,665,106,'所需资格缓存都命中？')
c.arrow([(mid,557),(mid,617)],color=BLUE)
c.node(990,597,390,160,'只补未命中的必要检查',['implementation suite','exact-input：wire-only 新进程恢复','PASS 更新缓存'],kind='purple',title_size=22,body_size=19)
c.arrow([(833,670),(990,670)],color=PURPLE,label='缺项',label_at=(911,652))
c.node(990,803,390,86,'资格失败：保留真实终态',['stage / reason / 证据'],kind='red',title_size=22,body_size=19)
c.arrow([(1185,757),(1185,803)],color=RED,label='未通过',label_at=(1235,785))
c.node(main_x,822,main_w,93,'计时诊断 / 校准 → 在本 worker 预热',['丢弃预热 codec session；首版固定 loops = 1'])
c.arrow([(mid,723),(mid,822)],color=BLUE,label='命中：跳对应检查',label_at=(mid,773))
c.arrow([(990,727),(950,727),(950,795),(865,795),(865,822)],color=PURPLE,label='PASS',label_at=(890,780))
c.node(main_x,965,main_w,93,'保存可执行 schedule 与 resolved manifest',['保存 / 读取既定顺序；发出 trial，记录 planned / started'])
c.arrow([(mid,915),(mid,965)],color=BLUE)
c.group(main_x,1110,main_w,346,'每次正式 trial · 新 codec session / 新 decoder session')
c.node(115,1158,771,77,'encode 计时',['对象 → 完整 wire；本次 encoder 关闭完成'],kind='teal',title_size=23,body_size=19)
c.node(115,1259,771,77,'decode 计时',['wire → 新 decoder session → 完整对象；decoder 关闭完成'],kind='teal',title_size=23,body_size=19)
c.node(115,1360,771,77,'计时外验证',['恢复 / 原始域误差 / 输入不变；违例为 error（reason = quality_violation）'],kind='gray',title_size=23,body_size=19)
c.arrow([(mid,1058),(mid,1082),(60,1082),(60,1196),(115,1196)],color=BLUE)
c.arrow([(mid,1235),(mid,1259)],color=TEAL)
c.arrow([(mid,1336),(mid,1360)],color=TEAL)
c.node(990,1259,390,200,'任意 stage 异常 / 错误',['native error + stage / reason','crash / timeout / 有证据的 oom','失效 worker 不复用；清理后重建','GPU 恢复未确认：余项 not_run'],kind='red',title_size=21,body_size=19)
c.arrow([(913,1300),(990,1300)],color=RED,dashed=True,label='异常',label_at=(951,1281))
c.node(main_x,1514,main_w,102,'追加原始记录与必要工件',['encode/decode_ns、完整 bytes、wire hash、质量、实际资源与终态','失败、retry attempt 和未运行项均保留'],kind='gray',title_size=23,body_size=19)
c.arrow([(mid,1456),(mid,1514)],color=TEAL)
for sx,sy in [(1380,335),(1380,846),(1380,1353)]:
    c.arrow([(sx,sy),(1413,sy),(1413,1565),(913,1565)],color=RED)
c.diamond(168,1674,665,106,'runner 还有待执行计划项？')
c.arrow([(mid,1616),(mid,1674)],color=BLUE)
c.arrow([(168,1727),(34,1727),(34,1011),(88,1011)],color=BLUE,label='是：已就绪健康 worker',label_at=(205,1649))
c.node(990,1674,390,153,'新 case/session 或 worker 失效',['记录终态后推进其他 case','清理 / 重建，再查询资格缓存','已停用设备的 not_run 项不再调度'],kind='blue',title_size=21,body_size=19)
c.arrow([(833,1727),(990,1727)],color=BLUE,label='是：需准备',label_at=(911,1706))
c.arrow([(1185,1674),(1185,1637),(1426,1637),(1426,497),(913,497)],color=BLUE)
c.node(main_x,1835,main_w,82,'全部结束：关闭剩余 worker / session',['GPU 恢复未确认时结束设备 session，余项已记 not_run'])
c.arrow([(mid,1780),(mid,1835)],color=BLUE,label='否',label_at=(mid,1818))
c.node(main_x,1966,main_w,103,'读取 raw → 描述报告 / 可选研究统计',['覆盖与失败、条件性能、完整大小、时间分布','重绘报告只读 raw'],kind='teal',title_size=23,body_size=19)
c.arrow([(mid,1917),(mid,1966)],color=TEAL)
c.node(990,1966,390,103,'可选：独立 profiling pass',['同 manifest，资源采样另一次执行','profile 结果可加入重生成报告'],kind='purple',dashed=True,title_size=22,body_size=19)
c.arrow([(913,1590),(950,1590),(950,1933),(1185,1933),(1185,1966)],color=PURPLE,dashed=True)
c.arrow([(990,2029),(913,2029)],color=PURPLE,dashed=True)
c.text(56,2124,'资格缓存只省必要预检；重复 trial 回到已保存 schedule，逐次恢复校验始终执行。',21,color=MUTED)
c.write('workflow.svg')
print('Generated architecture.svg and workflow.svg; every node text fits its box.')

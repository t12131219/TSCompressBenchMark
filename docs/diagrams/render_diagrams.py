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
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" height="{self.height}" viewBox="0 0 {self.width} {self.height}" role="img"><title>TSBench V4.0 {escape(filename)}</title><desc>依据V4.0计划绘制。2026-10-15设计修订：37真实CPU codec加raw，共38个key已完成两个生命周期直接原生测量；28组358请求、348完整有效、10不支持，4872/4872正式批次成功，715项测试通过；输入与流验证在主计时外，storage区分caller和owner；此前六组2534/2534 trials保留历史身份，C1/RW API及object辅助继续保留。</desc><defs>{defs}</defs><rect width="100%" height="100%" fill="#ffffff"/><g font-family="Noto Sans CJK SC, sans-serif">' + ''.join(self.bg+self.edges+self.boxes+self.labels) + '</g></svg>'
        (OUT/filename).write_text(svg,encoding='utf-8')

c = Canvas(1440,1645,'TSBench · 原生默认架构','2026-10-15｜38 CPU keys（含raw）已实测｜4872/4872批次｜715 tests passed')
for x,title,body in [(56,'experiment.toml',['任务 / dtype / layout / 质量 / 资源']),(528,'数据与同输入分母',['canonical V / T / mask；有效 bytes']),(1000,'codec 来源与构建',['真实源码 / 参数 / 模型 / binary 身份'])]:
    c.node(x,145,384,110,title,body,kind='gray',title_size=23,body_size=18)
c.group(56,315,1328,244,'Python 控制面 · 均在原生主计时外')
c.node(80,373,790,130,'config / runner / worker',['解析 → 完整请求矩阵 → 资格 → prepare / warmup → schedule','隔离 / timeout / retry / 失败分母；正式计时独占串行'],title_size=24,body_size=21)
c.node(925,373,430,130,'资格与验证基准',['implementation / exact-input','输入与stream准入在主计时外','content hash / dtype / shape / layout'],kind='purple',title_size=23,body_size=20)
for x in [248,720,1192]: c.arrow([(x,255),(x,315)],color=BLUE)
c.arrow([(870,438),(925,438)],color=PURPLE,both=True)
c.group(56,625,1328,550,'隔离 worker 内的三条边界 · 38 key direct 已验证')
c.node(80,689,405,180,'native_core · 默认 / 已验证',['37 codec + raw；双生命周期实测','C++ 内部循环 + CLOCK_MONOTONIC','prepared / fresh_request 分列'],kind='teal',title_size=24,body_size=20)
c.node(520,689,405,180,'native_api · 辅助 / 已实现',['C++ 内部循环调用 C1 / RW','shim 扫描 / 转换 / 内部分配计入','不可称 pure core；完整性另审核'],kind='purple',title_size=24,body_size=20)
c.node(960,689,395,180,'object_memory · 已有辅助',['Python wall：scheme → 完整 wire','独立 encoder / decoder session','适配 / hash / JSON / close 计入'],kind='gray',title_size=23,body_size=20)
c.arrow([(280,559),(280,689)],color=TEAL)
c.arrow([(720,559),(720,689)],color=PURPLE)
c.arrow([(1155,559),(1155,689)],color=BLUE)
c.node(80,937,845,175,'真实输出 / 完成 / 每份恢复',['主大小：codec 必要 header / 参数 / 模型 / index / tail','storage：按需caller容量；独立owner在context关闭后有效','每次必需 reset / sampling / modeling / Finish 仍计时','API 输出 / ABI envelope / framework wire 实证分账'],kind='teal',title_size=24,body_size=21)
c.node(960,937,395,175,'保留 GPU / pool',['host/device completion 各具名','集合 wall 与传输属于辅助边界','旧结果保留原身份和真实失败'],kind='gray',title_size=23,body_size=20)
c.arrow([(280,869),(280,937)],color=TEAL)
c.arrow([(720,869),(720,937)],color=PURPLE)
c.arrow([(1155,869),(1155,905),(900,905),(900,937)],color=BLUE)
c.node(80,1238,1275,125,'计时外逐产物验证 → append-only raw',['验证每份实际压缩 / 恢复输出、原始域质量、输入未改；不只验证最后一份','native totals / loops / clock / bytes 账单 / 状态；失败时间仅诊断'],kind='gray',title_size=24,body_size=21)
c.arrow([(500,1175),(500,1238)],color=TEAL)
c.node(80,1430,840,135,'只读 report：主表 core，API / object 辅助',['压缩倍数 / bits-value / native 吞吐；prepared 与 fresh 分表','未知完整性 / 未接入 core：null / unsupported，保留分母'],kind='teal',title_size=24,body_size=21)
c.node(970,1430,385,135,'可选 profiling',['同 manifest，另开 pass','RSS / perf / GPU / energy'],kind='purple',dashed=True,title_size=23,body_size=21)
c.arrow([(500,1363),(500,1430)],color=TEAL)
c.arrow([(1160,1363),(1160,1430)],color=PURPLE,dashed=True)
c.text(56,1613,'虚线：独立 profiling；358请求 / 348完整 / 10不支持；历史API / object保留原身份。',21,color=MUTED)
c.write('architecture.svg')

c = Canvas(1440,1960,'TSBench · 原生默认运行流程','2026-10-15｜38 key / 4872成功批次｜准入与流验证在主计时外｜715 tests passed')
x,w,mid=88,825,500.5
c.node(x,145,w,100,'读取配置：默认 native_core / prepared / natural',['native_api 辅助；object_memory / independent_object 保留'],title_size=25,body_size=21)
c.node(x,306,w,120,'同输入任务 → 全请求 case 矩阵',['固定 dtype / shape / layout / 有效 bytes / 质量 / 分片','不含 ABI envelope、padding、逐列重复共享 T'],title_size=24,body_size=21)
c.arrow([(mid,245),(mid,306)],color=BLUE)
c.node(990,306,390,150,'入口 / 能力不支持',['未接入 core 不 fallback','保留 unsupported / unavailable','不能核实必要输出：主大小 null'],kind='red',title_size=23,body_size=20)
c.arrow([(913,365),(990,365)],color=RED)
c.node(x,487,w,125,'worker prepare → 资格 → warmup / 固定预算',['真实输入身份与 validate_input 源域准入；主计时外','storage按需分配；loops通常8／DZip为2；保留内存有界'],title_size=24,body_size=21)
c.arrow([(mid,426),(mid,487)],color=BLUE)
c.node(x,673,w,100,'保存 schedule；父进程 planned / started',['主计时独占串行；Python 一次 batch 调用，循环在 C++ 内'],title_size=24,body_size=21)
c.arrow([(mid,612),(mid,673)],color=BLUE)
c.group(x,834,w,440,'C++ 原生 driver · 38 key direct 已验证；API辅助保留')
c.node(115,889,771,110,'完整 encode 批次：原生时钟',['独立 reset → 必需采样 / 建模 / encode / Finish → 保留每份输出','prepared 复用 workspace；fresh 含 context / buffer 分配及 context 关闭'],kind='teal',title_size=23,body_size=19)
c.node(115,1042,771,100,'完整 decode 批次：原生时钟',['独立decoder，无encoder参数或免费外部模型','已验不可变stream → 必需decode → 保留每份恢复'],kind='teal',title_size=23,body_size=20)
c.node(115,1180,771,75,'返回真实 encode / decode totals、loops、输出数',['Python 不减估计开销；内循环不算独立样本'],kind='teal',title_size=23,body_size=19)
c.arrow([(mid,773),(mid,834)],color=TEAL)
c.arrow([(mid,999),(mid,1042)],color=TEAL,label='计时外 validate：每份不可变stream',label_at=(mid,1029))
c.arrow([(mid,1142),(mid,1180)],color=TEAL)
c.node(990,890,390,230,'独立辅助分支',['native_api：完整 C1 / RW ABI','含 shim 解析 / 转换 / 分配','object：完整 wire 和 Python wall','GPU / pool：各自完成边界','分表记录，不冒称 core'],kind='gray',title_size=23,body_size=20)
c.arrow([(913,723),(1185,723),(1185,890)],color=BLUE)
c.node(990,1175,390,150,'错误 / 崩溃 / 超时',['保留 stage / reason / attempt','恢复未通过：时间仅诊断','父进程补终态、清理后重建'],kind='red',title_size=23,body_size=20)
c.arrow([(913,1050),(965,1050),(965,1250),(990,1250)],color=RED,dashed=True)
c.node(x,1335,w,135,'计时外：逐份恢复 / 质量 / 输入不变验证',['每个计时 operation 的真实输出均覆盖，不只最后一份','codec 必要输出实证账单；unknown → 主大小 null'],kind='gray',title_size=24,body_size=21)
c.arrow([(mid,1274),(mid,1335)],color=TEAL)
c.node(x,1525,w,110,'追加 raw / 必要工件；推进既定 schedule',['ok / error / unsupported / not_run 和原失败保留','下轮不重跑全资格；新 session / 失效 worker 按身份准备'],kind='gray',title_size=23,body_size=20)
c.arrow([(mid,1470),(mid,1525)],color=TEAL)
c.arrow([(88,1580),(38,1580),(38,725),(88,725)],color=BLUE,label='下一 trial',label_at=(150,1499))
for sy in [382,1250]: c.arrow([(1380,sy),(1412,sy),(1412,1580),(913,1580)],color=RED)
c.node(x,1715,w,125,'关闭 → 只读主 / 辅助报告',['core 压缩倍数 / bits-value / 原生吞吐；prepared / fresh 分表','覆盖与失败完整；API / wire / object 延迟仅作辅助'],kind='teal',title_size=24,body_size=21)
c.arrow([(mid,1635),(mid,1715)],color=TEAL,label='全部结束',label_at=(mid,1687))
c.node(990,1715,390,125,'独立 profiling pass',['同 manifest，另一次执行','不与正式测量 / 构建并行'],kind='purple',dashed=True,title_size=23,body_size=20)
c.arrow([(913,1777),(990,1777)],color=PURPLE,dashed=True)
c.text(56,1905,'fresh 保留产物最终释放在计时外；旧 object raw 不回填 native 字段，正式测量使用新 run。',21,color=MUTED)
c.write('workflow.svg')
print('Generated native-target architecture and workflow SVG; node text fits.')

"""Render a proposed CoR identity, without changing application assets.

Requires cairosvg and Pillow. Run with the environment under local_debug/brand-design.
"""
from pathlib import Path
from io import BytesIO
import cairosvg
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
ORIGINAL = ROOT.parents[3] / 'ts-phone/apps/mobile/assets/branding/ts-phone-icon.png'

DEFS = '''<defs>
  <linearGradient id="teal" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#24D4CA"/><stop offset="1" stop-color="#06A6AD"/></linearGradient>
  <linearGradient id="blue" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#28B9F0"/><stop offset="1" stop-color="#0865E8"/></linearGradient>
  <linearGradient id="gold" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#FFD34D"/><stop offset="1" stop-color="#F5AB17"/></linearGradient>
</defs>'''

def artwork(mono=False, small=False):
    def c(value):
        return 'currentColor' if mono else value
    claw = 'M 144,171 C 105,164 66,193 65,232 C 64,265 85,286 112,286 C 145,286 165,254 151,218 C 139,237 124,239 117,228 C 108,214 126,188 144,171 Z'
    parts = [
        f'<g fill="none" stroke-width="23" stroke-linecap="round"><path d="M111 274 Q107 307 155 322" stroke="{c("#079DA7")}"/><path d="M401 274 Q405 307 357 322" stroke="{c("#0965D9")}"/></g>',
        f'<path d="M117 356 L96 398 Q94 404 101 404 L120 404 L151 371 Z" fill="{c("#079DA7")}"/>',
        f'<path d="M395 356 L416 398 Q418 404 411 404 L392 404 L361 371 Z" fill="{c("#0965D9")}"/>',
        f'<path d="{claw}" fill="{c("url(#teal)")}"/>',
        f'<path d="{claw}" transform="translate(512 0) scale(-1 1)" fill="{c("url(#blue)")}"/>',
        f'<path fill-rule="evenodd" d="M256 150 C237 150 226 196 205 243 C180 299 147 324 91 344 L130 385 L181 415 L256 387 L331 415 L382 385 L421 344 C365 324 332 299 307 243 C286 196 275 150 256 150 Z {"M235 307 A13 13 0 1 0 209 307 A13 13 0 1 0 235 307 Z M303 307 A13 13 0 1 0 277 307 A13 13 0 1 0 303 307 Z" if mono else ""}" fill="{c("url(#teal)")}"/>',
    ]
    if not mono:
        parts += [
            '<path d="M256 150 C275 150 286 196 307 243 C332 299 365 324 421 344 L382 385 L331 415 L256 387 Z" fill="url(#blue)"/>',
        ]
        if not small:
            parts += [
                '<path d="M91 344 L173 369 L256 332 L256 387 L181 415 L130 385 Z" fill="#078C9F"/>',
                '<path d="M256 332 L339 369 L421 344 L382 385 L331 415 L256 387 Z" fill="#0755C0"/>',
                '<path d="M173 369 L181 415 L130 385 L91 344 Z" fill="#087989" opacity=".48"/>',
                '<path d="M339 369 L331 415 L382 385 L421 344 Z" fill="#064CA8" opacity=".55"/>',
            ]
    parts += [f'<circle cx="256" cy="119" r="33" fill="none" stroke="{c("url(#gold)")}" stroke-width="17"/>']
    for x in (222, 290):
        if mono:
            continue
        parts.append(f'<circle cx="{x}" cy="307" r="13" fill="#092A40"/>')
        if not small:
            parts.append(f'<circle cx="{x-3}" cy="303" r="3.8" fill="white"/>')
    return '\n'.join(parts)

def svg(mono=False, small=False, icon=False):
    bg = '<rect width="512" height="512" fill="#F6F9FC"/>' if icon else ''
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 512 512" color="#122E43" role="img" aria-labelledby="title desc">
<title id="title">CoR crab — proposed shared brand mark</title>
<desc id="desc">A symmetric teal and blue crab with raised claws, a triangular folded body, two eyes and a golden ring above its head.</desc>
{DEFS}{bg}<g>{artwork(mono, small)}</g></svg>'''

def render(data, size):
    return Image.open(BytesIO(cairosvg.svg2png(bytestring=data.encode(), output_width=size, output_height=size))).convert('RGBA')

for name, options in [('cor-crab-mark', {}), ('cor-crab-mono', {'mono': True}), ('cor-crab-small', {'small': True}), ('corhub-icon', {'icon': True})]:
    data = svg(**options)
    (ROOT / f'{name}.svg').write_text(data)
    render(data, 1024).save(ROOT / f'{name}.png')

W, H = 1600, 1240
board = Image.new('RGB', (W, H), '#EFF3F6')
d = ImageDraw.Draw(board)
FONT = '/usr/share/fonts/google-noto-sans-cjk-vf-fonts/NotoSansCJK-VF.ttc'
LATIN = '/usr/share/fonts/redhat/RedHatDisplay-SemiBold.otf'
def txt(x, y, value, size=24, color='#142F43', latin=False):
    font = ImageFont.truetype(LATIN if latin else FONT, size)
    if not latin:
        font.set_variation_by_axes([450 if size >= 25 else 380])
    d.text((x, y), value, font=font, fill=color)
def card(box, color='white', radius=26):
    d.rounded_rectangle(box, radius=radius, fill=color)
def paste(im, x, y):
    board.paste(im, (x, y), im)

txt(64, 34, 'CoR / 螃蟹标志优化', 42)
txt(66, 103, '保留青蓝双钳、三角折面与金环，让同一只螃蟹适配新的产品家族。', 23, '#5A7080')
txt(1320, 51, 'CONCEPT 01', 20, '#5A7080', True)

card((64, 169, 607, 739))
card((631, 169, 1536, 739))
txt(93, 190, '原版 / TS Phone', 23, '#5A7080')
txt(663, 190, '优化版 / CoR', 23, '#5A7080')
old = Image.open(ORIGINAL).convert('RGBA').resize((480, 480), Image.Resampling.LANCZOS)
paste(old, 96, 234)
paste(render(svg(), 490), 660, 229)
txt(1171, 295, '延续识别特征', 25)
txt(1171, 340, '青蓝双色与金环', 21, '#5A7080')
txt(1171, 378, '双钳与折面身体', 21, '#5A7080')
txt(1171, 462, '优化使用体验', 25)
txt(1171, 507, '统一对称与曲线', 21, '#5A7080')
txt(1171, 545, '减少纹理与碎高光', 21, '#5A7080')
txt(1171, 583, '补齐小尺寸与单色版', 21, '#5A7080')

card((64, 765, 788, 994))
card((812, 765, 1536, 994), '#102C42')
paste(render(svg(), 210), 85, 771)
txt(307, 804, 'CoRAgent', 57, latin=True)
txt(310, 885, 'Computational Research Agent', 23, '#5A7080', True)
txt(310, 926, '推进计算研究的智能体', 20, '#5A7080')
paste(render(svg(), 210), 833, 771)
txt(1055, 804, 'CoRHub', 57, '#FFFFFF', True)
txt(1058, 885, 'Your computational research workspace', 21, '#B6C9D7', True)
txt(1058, 926, '连接工作区，跟进研究与计算', 20, '#B6C9D7')

card((64, 1020, 1536, 1175))
txt(92, 1040, '小尺寸图标', 20, '#5A7080')
for x, size in [(108, 24), (184, 32), (271, 48), (375, 64)]:
    paste(render(svg(small=True), size), x, 1100-size//2)
    txt(x-1, 1136, str(size), 15, '#5A7080', True)
txt(512, 1040, '单色适配', 20, '#5A7080')
paste(render(svg(mono=True), 90), 513, 1076)
card((639, 1075, 731, 1160), '#102C42', 14)
paste(render(svg(mono=True).replace('color="#122E43"', 'color="#FFFFFF"'), 90), 640, 1073)
txt(823, 1040, '品牌色', 20, '#5A7080')
for x, color, name in [(824, '#10BDBB', '青绿'), (994, '#1479ED', '研究蓝'), (1164, '#F7BC2A', '金环'), (1334, '#102C42', '深海蓝')]:
    card((x, 1091, x+32, 1123), color, 9)
    txt(x+44, 1085, name, 17, '#5A7080')
    txt(x, 1133, color.upper(), 16, '#5A7080', True)
txt(66, 1197, '提案 v1 · 共用图形，以产品字标区分 · 应用图标采用无文字版本', 18, '#5A7080')
board.save(ROOT / 'cor-brand-proposal.png')
print(ROOT / 'cor-brand-proposal.png')

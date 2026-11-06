"""生成单字母印章块（字粒）的测试 STL。

用法（在项目根执行）：
    .venv313\\Scripts\\python.exe letter_blocks\\scripts\\build.py all
    .venv313\\Scripts\\python.exe letter_blocks\\scripts\\build.py thickness
    .venv313\\Scripts\\python.exe letter_blocks\\scripts\\build.py spacing
    .venv313\\Scripts\\python.exe letter_blocks\\scripts\\build.py single A V I --thickness 1.2
    .venv313\\Scripts\\python.exe letter_blocks\\scripts\\build.py strip AVIHOW --thickness 1.2

设计约束（与 stampgen 整块方案对齐）：
  * 块宽 = 字体 advance（逐字母），保证拼装后字距逐对复刻
  * 统一基线：cap 高中心对齐块深中心
  * 只镜像字形，不镜像块（否则块内留白互换，字距错位）
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from stampgen.fonts import FontLibrary
from stampgen.metrics import ADVANCE_SCALE, INK_SCALE
from stampgen.openscad import stl_extent, stl_stats

OPENSCAD = ROOT / "OpenSCAD" / "openscad.exe"
SCAD_SINGLE = HERE / "scad" / "letter_block.scad"
SCAD_STRIP = HERE / "scad" / "letter_strip.scad"
SCAD_TRAY = HERE / "scad" / "tray.scad"
SCAD_BAR = HERE / "scad" / "bar.scad"
OUT = HERE / "out"

FONT_FAMILY = "Arial"
FONT_STYLE = "Regular"
SIZE = 6.0
BLOCK_DEPTH = 13.0
"""块在 Y 向（上下 / 进深）的长度。

初版按整块方案的底座宽 6.6mm 做，实测卡槽夹不住 —— 卡槽需要 13mm 才够夹持。
改这个值不影响字距（字距只由 X 向的 advance 决定），只是块变「深」，
字仍然在 13mm 的正中（由 BASELINE_Y 保证）。
"""
LETTER_HEIGHT = 6.0
STRIP_GAP = 0.5
"""整排件里块与块之间的缝。

不能小于 0.4（喷嘴直径）：A / V / W 的字形会伸出底板 0.06~0.14mm，
缝太小会让字形与邻块粘连，掰不开。掰开后贴合拼装，这个缝不影响最终字距。
"""

CAP_REF = "HELT"

lib = FontLibrary()
_face = lib.find(FONT_FAMILY, FONT_STYLE)
_m = lib.metrics(_face)
_ENV = lib.env()


def _mm(units: float) -> float:
    return units / _m.upem * SIZE * INK_SCALE


CAP = max(_mm(_m.v_bboxes[ord(c)][1]) for c in CAP_REF)


def baseline_for(depth: float) -> float:
    """把字形的 cap 高中心对齐到块深中心，返回基线在块坐标系里的 Y 值。

    块深一变（13 / 13.5 / 14），基线必须跟着动，否则字会偏上或偏下。
    """
    return round(depth / 2 - CAP / 2, 4)


BASELINE_Y = baseline_for(BLOCK_DEPTH)


def metrics_of(ch: str) -> dict[str, float]:
    adv = _m.advances[ord(ch)] / _m.upem * SIZE * ADVANCE_SCALE
    b = _m.bboxes[ord(ch)]
    return {
        "letter": ch,
        "advance": round(adv, 4),
        "ink": round(_mm(b[1] - b[0]), 4),
        "xmin": round(_mm(b[0]), 4),
        "xmax": round(_mm(b[1]), 4),
        "overhang": round(_mm(b[1]) - adv, 4),
    }


def _run(scad: Path, out: Path, defines: list[str]) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    args = [str(OPENSCAD), "-o", str(out), "--export-format", "binstl"]
    for d in defines:
        args += ["-D", d]
    args.append(str(scad))
    proc = subprocess.run(
        args, capture_output=True, text=True, env=_ENV,
        encoding="utf-8", errors="replace", timeout=300,
    )
    text = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
        raise RuntimeError(f"渲染失败 {out.name}: {text.strip()[:400]}")
    if "not closed" in text or "CGAL_Nef" in text:
        raise RuntimeError(f"网格未闭合 {out.name}: {text.strip()[:400]}")


def _defines(mt: dict[str, float], thickness: float, depth: float = BLOCK_DEPTH) -> list[str]:
    return [
        f'letter="{mt["letter"]}"',
        f"block_width={mt['advance']}",
        f"block_depth={depth}",
        f"plate_thickness={thickness}",
        f"letter_height={LETTER_HEIGHT}",
        f"letter_size={SIZE}",
        f"ink_xmin={mt['xmin']}",
        f"ink_xmax={mt['xmax']}",
        f"baseline_y={baseline_for(depth)}",
        f'font_family="{FONT_FAMILY}"',
        f'font_style="{FONT_STYLE}"',
    ]


def render_single(ch: str, thickness: float, out_dir: Path,
                  depth: float = BLOCK_DEPTH, tag_depth: bool = False) -> Path:
    mt = metrics_of(ch)
    suffix = f"_d{depth:g}" if tag_depth else ""
    out = out_dir / f"{ch}_t{thickness:.1f}{suffix}.stl"
    _run(SCAD_SINGLE, out, _defines(mt, thickness, depth))
    ext = stl_extent(out, z_above=thickness + 0.1)
    if abs(ext.width - mt["ink"]) > 0.05:
        print(f"    ! 字形宽 {ext.width:.2f} 与预期 {mt['ink']:.2f} 不符")
    return out


def render_strip(letters: str, thickness: float, out_dir: Path,
                 depth: float = BLOCK_DEPTH, tag_depth: bool = False) -> Path:
    # 印章压印时整排翻转，顺序会反转 —— STL 里必须倒着排，压印后才正读
    rev = letters[::-1]
    mts = [metrics_of(c) for c in rev]
    offsets, x = [], 0.0
    for mt in mts:
        offsets.append(round(x, 4))
        x += mt["advance"] + STRIP_GAP
    suffix = f"_d{depth:g}" if tag_depth else ""
    out = out_dir / f"{letters}_strip_t{thickness:.1f}{suffix}.stl"
    defines = [
        f"letters=[{','.join(chr(34) + c + chr(34) for c in rev)}]",
        f"widths=[{','.join(str(m['advance']) for m in mts)}]",
        f"xmins=[{','.join(str(m['xmin']) for m in mts)}]",
        f"xmaxs=[{','.join(str(m['xmax']) for m in mts)}]",
        f"offsets=[{','.join(str(o) for o in offsets)}]",
        f"block_depth={depth}",
        f"plate_thickness={thickness}",
        f"letter_height={LETTER_HEIGHT}",
        f"letter_size={SIZE}",
        f"baseline_y={baseline_for(depth)}",
        f'font_family="{FONT_FAMILY}"',
        f'font_style="{FONT_STYLE}"',
    ]
    _run(SCAD_STRIP, out, defines)
    return out


def write_metrics_csv() -> Path:
    path = HERE / "data" / "letters.csv"
    rows = [metrics_of(c) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return path


def plan_thickness() -> None:
    """方案 1：只打 H，6 种底板厚度，测卡槽配合。"""
    print("方案 1 · 底板厚度标定（字母 H，无 overshoot、无越界，最干净）")
    out_dir = OUT / "01_thickness"
    for t in (1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6):
        t0 = time.time()
        p = render_single("H", t, out_dir)
        print(f"  H_t{t:.1f}.stl  {p.stat().st_size/1024:6.1f} KB  {time.time()-t0:4.1f}s")


def plan_spacing() -> None:
    """方案 2：AVILOW 六块 + 整排，测字距复刻与镜像方向。"""
    word = "AVILOW"
    print(f"方案 2 · 字距复刻（{word}，覆盖 8/8 测试维度，含不对称字母 L）")
    out_dir = OUT / "02_spacing"
    for ch in word:
        mt = metrics_of(ch)
        t0 = time.time()
        p = render_single(ch, 1.2, out_dir)
        print(f"  {ch}_t1.2.stl  块宽 {mt['advance']:5.2f}  墨迹 {mt['ink']:5.2f}  "
              f"越界 {mt['overhang']:+.2f}  {time.time()-t0:4.1f}s")
    t0 = time.time()
    p = render_strip(word, 1.2, out_dir)
    print(f"  {word}_strip_t1.2.stl  整排（间隙 {STRIP_GAP}mm，打印后掰开）  "
          f"{p.stat().st_size/1024:6.1f} KB  {time.time()-t0:4.1f}s")
    total = sum(metrics_of(c)["advance"] for c in word)
    print(f"  拼装总宽应为 {total:.2f}mm（= Σadvance），用卡尺核对")


def render_preview(letters: str, thickness: float) -> Path:
    """渲染整排的预览图，用于快速核对镜像与字距。"""
    rev = letters[::-1]
    mts = [metrics_of(c) for c in rev]
    offsets, x = [], 0.0
    for mt in mts:
        offsets.append(round(x, 4))
        x += mt["advance"] + STRIP_GAP
    out = OUT / f"{letters}_preview.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    args = [
        str(OPENSCAD), "-o", str(out), "--imgsize=1800,760",
        "--viewall", "--autocenter", "--projection=o",
        "--colorscheme=Tomorrow", "--camera=0,0,0,0,0,0,0",
    ]
    for d in [
        f"letters=[{','.join(chr(34) + c + chr(34) for c in rev)}]",
        f"widths=[{','.join(str(m['advance']) for m in mts)}]",
        f"xmins=[{','.join(str(m['xmin']) for m in mts)}]",
        f"xmaxs=[{','.join(str(m['xmax']) for m in mts)}]",
        f"offsets=[{','.join(str(o) for o in offsets)}]",
        f"block_depth={depth}",
        f"plate_thickness={thickness}",
        f"letter_height={LETTER_HEIGHT}",
        f"letter_size={SIZE}",
        f"baseline_y={BASELINE_Y}",
        f'font_family="{FONT_FAMILY}"',
        f'font_style="{FONT_STYLE}"',
    ]:
        args += ["-D", d]
    args.append(str(SCAD_STRIP))
    subprocess.run(args, capture_output=True, env=_ENV, timeout=300)
    if not out.is_file():
        raise RuntimeError("预览渲染失败")
    return out


def plan_fit() -> None:
    """方案 3：板厚 × 块深 配合矩阵（3 × 3 = 9 件）。

    板厚决定卡槽的夹持力，块深决定块在槽里能不能顶到两侧。
    两个方向都可能「差一点就松」，所以做全组合而不是一次改一个变量。
    """
    print("方案 3 · 板厚 × 块深 配合矩阵（字母 H）")
    out_dir = OUT / "03_fit"
    for t in (1.4, 1.5, 1.6):
        for d in (13.0, 13.5, 14.0):
            t0 = time.time()
            p = render_single("H", t, out_dir, depth=d, tag_depth=True)
            print(f"  {p.name:<24} 板厚 {t:.1f}  块深 {d:g}  "
                  f"总高 {t + LETTER_HEIGHT:.2f}  {time.time()-t0:4.1f}s")


SAMPLE_THICKNESS = 1.5
SAMPLE_DEPTH = 14.0
SAMPLE_WORD = "AVILOW"


def plan_sample() -> None:
    """方案 4：选定尺寸的正式打样（板厚 1.5 / 块深 14）。"""
    print(f"方案 4 · 正式打样（板厚 {SAMPLE_THICKNESS} / 块深 {SAMPLE_DEPTH:g}，"
          f"词 {SAMPLE_WORD}）")
    out_dir = OUT / f"04_sample_t{SAMPLE_THICKNESS:.1f}_d{SAMPLE_DEPTH:g}"
    for ch in SAMPLE_WORD:
        mt = metrics_of(ch)
        t0 = time.time()
        p = render_single(ch, SAMPLE_THICKNESS, out_dir,
                          depth=SAMPLE_DEPTH, tag_depth=True)
        print(f"  {p.name:<26} 块宽 {mt['advance']:5.2f}  墨迹 {mt['ink']:5.2f}  "
              f"越界 {mt['overhang']:+.2f}  {time.time()-t0:4.1f}s")
    t0 = time.time()
    p = render_strip(SAMPLE_WORD, SAMPLE_THICKNESS, out_dir,
                     depth=SAMPLE_DEPTH, tag_depth=True)
    print(f"  {p.name:<26} 整排（缝 {STRIP_GAP}mm）  {time.time()-t0:4.1f}s")
    total = sum(metrics_of(c)["advance"] for c in SAMPLE_WORD)
    print(f"  拼装总宽应为 {total:.2f}mm")


def render_multi(ch: str, count: int, thickness: float, depth: float,
                 out_dir: Path, gap: float = 0.5) -> Path:
    """把同一个字符排成 N 连，一次打印、掰开即用。

    注意不能用字距排：同字母相邻的墨迹间隙是负的（A→A 为 −0.154mm），
    会直接重叠。备料件按固定 gap 排，和排版无关。
    """
    mt = metrics_of(ch)
    offsets = [round(i * (mt["advance"] + gap), 4) for i in range(count)]
    out = out_dir / f"{ch}_x{count}.stl"
    defines = [
        f"letters=[{','.join(chr(34) + ch + chr(34) for _ in range(count))}]",
        f"widths=[{','.join(str(mt['advance']) for _ in range(count))}]",
        f"xmins=[{','.join(str(mt['xmin']) for _ in range(count))}]",
        f"xmaxs=[{','.join(str(mt['xmax']) for _ in range(count))}]",
        f"offsets=[{','.join(str(o) for o in offsets)}]",
        f"block_depth={depth}",
        f"plate_thickness={thickness}",
        f"letter_height={LETTER_HEIGHT}",
        f"letter_size={SIZE}",
        f"baseline_y={baseline_for(depth)}",
        f'font_family="{FONT_FAMILY}"',
        f'font_style="{FONT_STYLE}"',
    ]
    _run(SCAD_STRIP, out, defines)
    return out


KIT_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
KIT_DIGITS = "0123456789"
KIT_COPIES = 5
KIT_EXTRA = {"I": 5}
"""I 的墨迹只有 0.789mm 宽、凸起 6mm，高宽比 7.6:1，是全套里最脆的一件，
所以额外多备 5 个。"""


def plan_kit() -> None:
    """方案 5：整套备料（26 字母 + 10 数字，每字符 5 个，I 额外 5 个）。"""
    out = OUT / f"05_kit_t{SAMPLE_THICKNESS:.1f}_d{SAMPLE_DEPTH:g}"
    print(f"方案 5 · 整套备料（板厚 {SAMPLE_THICKNESS} / 块深 {SAMPLE_DEPTH:g}）")
    total = 0
    for sub, chars in (("letters", KIT_LETTERS), ("digits", KIT_DIGITS)):
        for ch in chars:
            n = KIT_COPIES + (KIT_EXTRA.get(ch, 0) if sub == "letters" else 0)
            t0 = time.time()
            p = render_multi(ch, n, SAMPLE_THICKNESS, SAMPLE_DEPTH, out / sub)
            total += n
            print(f"  {sub}/{p.name:<12} {n:>2} 件  {time.time()-t0:4.1f}s")
    print(f"  合计 {total} 件")
    print(f"  输出 {out}")


TRAY_COLS = 6
TRAY_DIGIT_ROWS = 2
TRAY_LETTER_ROWS = 5
TRAY_WIDE_COL = 4
"""第 5 列（0 基）加宽到 43mm —— 全套只有 W 的 5 件放不进 37mm：
5 × 7.681 + 4 × 0.5 = 40.4mm。其余最宽的 M 只要 5 × 6.779 + 2 = 35.9mm。"""


def stl_volume(path: Path) -> float:
    """二进制 STL 的封闭体积（有符号四面体求和，mm³）。"""
    import struct

    data = path.read_bytes()
    n = struct.unpack_from("<I", data, 80)[0]
    vol = 0.0
    off = 84
    for _ in range(n):
        v = struct.unpack_from("<9f", data, off + 12)
        a = v[0:3]
        b = v[3:6]
        c = v[6:9]
        vol += (a[0] * (b[1] * c[2] - b[2] * c[1])
                - a[1] * (b[0] * c[2] - b[2] * c[0])
                + a[2] * (b[0] * c[1] - b[1] * c[0])) / 6.0
        off += 50
    return abs(vol)


def tray_labels() -> list[str]:
    """按行优先（从正面第一行往后）排出每格刻的字符，空位留空串。

    正面 = -Y 侧。数字区在前 2 行，字母区在后 5 行，中间隔墙加厚区分。
    """
    grid: list[list[str]] = [[] for _ in range(TRAY_DIGIT_ROWS + TRAY_LETTER_ROWS)]
    slots = [[""] * TRAY_COLS for _ in grid]
    for i, ch in enumerate(KIT_DIGITS):
        slots[i // TRAY_COLS][i % TRAY_COLS] = ch
    for i, ch in enumerate(KIT_LETTERS):
        r, c = divmod(i, TRAY_COLS)
        slots[TRAY_DIGIT_ROWS + r][c] = ch
    for r, row in enumerate(slots):
        grid[r] = row
    return [ch for row in grid for ch in row]


def tray_defines() -> list[str]:
    return [
        f"labels=[{','.join(chr(34) + c + chr(34) for c in tray_labels())}]",
        f"label_size={SIZE * 4.0 / CAP:.4f}",
        "label_cap=4.0",
        "label_depth=0.8",
    ]


def plan_tray() -> None:
    """方案 6：字粒收纳盘（长方形 / 数字区与字母区分开 / 每格刻字符）。"""
    print("方案 6 · 字粒收纳盘")
    out_dir = OUT / "06_tray"
    for part, name in ((0, "tray_full"), (1, "tray_left"), (2, "tray_right")):
        out = out_dir / f"{name}.stl"
        t0 = time.time()
        _run(SCAD_TRAY, out, tray_defines() + [f"part={part}"])
        ext = stl_stats(out)
        vol = stl_volume(out)
        print(f"  {out.name:<16} {ext.width:6.1f} × {ext.depth:5.1f} × {ext.height:4.1f}mm  "
              f"{ext.triangles:>6} 面  {vol/1000:5.1f} cm³ ≈ {vol/1000*1.24:3.0f}g  "
              f"{time.time()-t0:5.1f}s")
    print(f"  格 {TRAY_COLS} 列 × {TRAY_DIGIT_ROWS + TRAY_LETTER_ROWS} 行，"
          f"字母区 {TRAY_LETTER_ROWS} 行 / 数字区 {TRAY_DIGIT_ROWS} 行")
    print(f"  输出 {out_dir}")


def render_tray_preview() -> list[Path]:
    out_dir = OUT / "06_tray"
    out_dir.mkdir(parents=True, exist_ok=True)
    jobs = [("tray_top.png", "0,0,0,0,0,0,0"), ("tray_iso.png", "0,0,0,62,0,32,0")]
    made = []
    for name, cam in jobs:
        out = out_dir / name
        args = [
            str(OPENSCAD), "-o", str(out), "--imgsize=1800,1200",
            "--viewall", "--autocenter", "--projection=o",
            "--colorscheme=Tomorrow", f"--camera={cam}",
        ]
        for d in tray_defines():
            args += ["-D", d]
        args.append(str(SCAD_TRAY))
        subprocess.run(args, capture_output=True, env=_ENV, timeout=600)
        if not out.is_file():
            raise RuntimeError(f"预览渲染失败：{name}")
        made.append(out)
    return made


def plan_bar() -> None:
    """方案 7：排版长条（底板 + 压盖，6 颗 M3）。"""
    print("方案 7 · 排版长条（上下夹）")
    out_dir = OUT / "07_bar"
    for part, name in ((0, "bar_base"), (1, "bar_cover")):
        out = out_dir / f"{name}.stl"
        t0 = time.time()
        _run(SCAD_BAR, out, [f"part={part}"])
        ext = stl_stats(out)
        vol = stl_volume(out)
        print(f"  {out.name:<12} {ext.width:6.1f} × {ext.depth:5.1f} × {ext.height:4.1f}mm  "
              f"{ext.triangles:>6} 面  {vol/1000:5.1f} cm³ ≈ {vol/1000*1.24:3.0f}g  "
              f"{time.time()-t0:5.1f}s")
    widest = sum(metrics_of(c)["advance"] for c in "W" * 18)
    print(f"  排字区长 145mm；18 个 W 需 {widest:.2f}mm，余量 {145 - widest:.1f}mm")
    print(f"  输出 {out_dir}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("plan", choices=["all", "thickness", "spacing", "fit", "sample",
                                     "kit", "tray", "bar", "single", "strip", "preview"])
    ap.add_argument("letters", nargs="*")
    ap.add_argument("--thickness", type=float, default=1.2)
    args = ap.parse_args()

    if not OPENSCAD.is_file():
        sys.exit(f"找不到 OpenSCAD：{OPENSCAD}")
    print(f"字体 {_face.full_name} | cap {CAP:.3f}mm | 基线 y={BASELINE_Y:.3f}mm")
    print(write_metrics_csv())

    if args.plan == "all":
        plan_thickness()
        plan_spacing()
    elif args.plan == "thickness":
        plan_thickness()
    elif args.plan == "spacing":
        plan_spacing()
    elif args.plan == "fit":
        plan_fit()
    elif args.plan == "sample":
        plan_sample()
    elif args.plan == "kit":
        plan_kit()
    elif args.plan == "tray":
        plan_tray()
    elif args.plan == "bar":
        plan_bar()
    elif args.plan == "single":
        for ch in args.letters:
            p = render_single(ch, args.thickness, OUT / "custom")
            print(p)
    elif args.plan == "strip":
        p = render_strip("".join(args.letters), args.thickness, OUT / "custom")
        print(p)
    else:
        p = render_preview("".join(args.letters) or "AVILOW", args.thickness)
        print(p)


if __name__ == "__main__":
    main()

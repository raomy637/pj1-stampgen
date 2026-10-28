#!/usr/bin/env python3
"""GUI 冒烟测试：启动打包后的 exe，确认窗口真的起来了，并截图留证。

检查内容：

1. 进程在超时前没有退出（``--windowed`` 下启动异常会写崩溃日志并弹窗）
2. 出现了标题匹配的主窗口（说明 Tk 与 tkinterdnd2 都初始化成功）
3. 窗口尺寸合理（不是 0×0 或异常小）
4. 截一张图，供肉眼确认布局

用法::

    .venv313/Scripts/python.exe tools/gui_smoke.py                  # 测新版
    .venv313/Scripts/python.exe tools/gui_smoke.py --keep           # 不自动关窗
    .venv313/Scripts/python.exe tools/gui_smoke.py \
        --exe "dist/legacy/PJ1Program/PJ1Program.exe" --title "STL 批量生成"   # 测旧版
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXE = ROOT / "dist" / "StampGen.exe"
DEFAULT_TITLE = "印章"

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD),
        ("biWidth", wt.LONG),
        ("biHeight", wt.LONG),
        ("biPlanes", wt.WORD),
        ("biBitCount", wt.WORD),
        ("biCompression", wt.DWORD),
        ("biSizeImage", wt.DWORD),
        ("biXPelsPerMeter", wt.LONG),
        ("biYPelsPerMeter", wt.LONG),
        ("biClrUsed", wt.DWORD),
        ("biClrImportant", wt.DWORD),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]


def _setup_argtypes() -> None:
    """显式声明参数类型。

    64 位下 HWND/HDC 是 64 位指针，ctypes 默认按 c_int 传会截断，
    结果就是 SetWindowPos 之类的调用静默失败（返回 0，看起来「什么都没发生」）。
    """
    user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
    user32.SetWindowPos.argtypes = [
        wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT
    ]
    user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
    user32.GetWindowDC.argtypes = [wt.HWND]
    user32.GetWindowDC.restype = wt.HDC
    user32.PrintWindow.argtypes = [wt.HWND, wt.HDC, wt.UINT]
    user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
    gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
    gdi32.CreateCompatibleDC.restype = wt.HDC
    gdi32.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = wt.HBITMAP
    gdi32.SelectObject.argtypes = [wt.HDC, wt.HBITMAP]
    gdi32.SelectObject.restype = wt.HBITMAP
    gdi32.GetDIBits.argtypes = [
        wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT, ctypes.c_void_p,
        ctypes.POINTER(_BITMAPINFO), wt.UINT,
    ]
    gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [wt.HDC]


_setup_argtypes()


def capture_window(hwnd: int, path: Path, retries: int = 3) -> None:
    """直接把窗口内容渲染成图片，不管它有没有被别的窗口挡住。

    ImageGrab 抓的是屏幕像素，窗口一旦被浏览器/Excel 压住就拍到别人；
    PrintWindow 让窗口自己把内容画进内存 DC，遮挡无关。

    刚 ShowWindow 还原的窗口会在动画中间态被读到（高度只有几十像素），
    所以尺寸不合理时等一会儿重试。
    """
    from PIL import Image

    for attempt in range(retries):
        left, top, right, bottom = _rect(hwnd)
        w, h = right - left, bottom - top
        if w > 100 and h > 100:
            break
        if attempt == retries - 1:
            raise RuntimeError(f"窗口尺寸异常：{w}×{h}")
        time.sleep(0.5)

    hdc = user32.GetWindowDC(hwnd)
    mem_dc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    old = gdi32.SelectObject(mem_dc, bmp)
    try:
        # PW_RENDERFULLCONTENT = 2：让 DWM 合成的内容（Tk 这类）也能被画出来
        user32.PrintWindow(hwnd, mem_dc, 2)

        bi = _BITMAPINFO()
        bi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bi.bmiHeader.biWidth = w
        bi.bmiHeader.biHeight = -h  # 负值 = 自上而下，省一次翻转
        bi.bmiHeader.biPlanes = 1
        bi.bmiHeader.biBitCount = 32
        bi.bmiHeader.biCompression = 0  # BI_RGB

        buf = ctypes.create_string_buffer(w * h * 4)
        gdi32.GetDIBits(mem_dc, bmp, 0, h, buf, ctypes.byref(bi), 0)
        img = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1)
        path.parent.mkdir(parents=True, exist_ok=True)
        img.convert("RGB").save(path)
    finally:
        gdi32.SelectObject(mem_dc, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(hwnd, hdc)


def _windows_with_title(hint: str) -> dict[int, tuple[str, int]]:
    """枚举可见顶层窗口里标题含关键字的那些，返回 {hwnd: (标题, 进程 PID)}。

    不能按启动时的 PID 过滤：PyInstaller onefile 的引导程序会另起子进程，
    真正的 Tk 窗口属于子进程，父进程 PID 上什么都找不到。
    """
    found: dict[int, tuple[str, int]] = {}

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def _cb(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        if hint in buf.value:
            pid = wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            found[hwnd] = (buf.value, pid.value)
        return True

    user32.EnumWindows(_cb, 0)
    return found


def _rect(hwnd: int) -> tuple[int, int, int, int]:
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def _foreground(hwnd: int) -> None:
    """把窗口顶到最前面，否则截图抓到的是压在它上面的别的窗口。

    SetForegroundWindow 对后台进程会被 Windows 的前台锁拦掉，
    所以这里用 SetWindowPos 设成 TOPMOST —— 这个不需要前台权限，一定生效。
    """
    try:
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        HWND_TOPMOST = -1
        SWP_NOMOVE, SWP_NOSIZE, SWP_SHOWWINDOW = 0x0002, 0x0001, 0x0040
        user32.SetWindowPos(
            hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW
        )
    except Exception:  # noqa: BLE001 - 置顶失败也不该让测试失败
        pass


def _untopmost(hwnd: int) -> None:
    try:
        HWND_NOTOPMOST = -2
        SWP_NOMOVE, SWP_NOSIZE = 0x0002, 0x0001
        user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
    except Exception:  # noqa: BLE001
        pass


def _kill_tree(proc: subprocess.Popen, app_pid: int = 0) -> None:
    """彻底结束进程。

    onefile 下引导进程和 Tk 应用进程是两个，只杀父进程会留下孤儿进程占住 exe，
    下次打包覆盖时就会失败，所以窗口所属 PID 也要一并结束。
    """
    for pid in {proc.pid, app_pid}:
        if not pid:
            continue
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            timeout=30,
        )
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GUI 冒烟测试")
    parser.add_argument("--exe", default=str(DEFAULT_EXE), help="要测试的 exe 路径")
    parser.add_argument("--title", default=DEFAULT_TITLE, help="主窗口标题包含的关键字")
    parser.add_argument("--shot", default="", help="截图输出路径（默认与 exe 同目录）")
    parser.add_argument("--keep", action="store_true", help="测试完不关闭窗口")
    parser.add_argument("--timeout", type=float, default=30.0, help="等待窗口出现的秒数")
    parser.add_argument("--settle", type=float, default=1.5, help="截图前等待窗口画完的秒数")
    args = parser.parse_args(argv)

    exe = Path(args.exe)
    if not exe.is_file():
        print(f"[失败] 找不到 {exe}")
        return 1
    shot = Path(args.shot) if args.shot else exe.parent / "gui_check.png"

    crash_log = exe.parent / "stampgen_crash.log"
    if crash_log.is_file():
        crash_log.unlink()

    print(f"启动 {exe.name} …", flush=True)
    before = set(_windows_with_title(args.title))
    proc = subprocess.Popen([str(exe)], cwd=str(exe.parent))

    hwnd = 0
    title = ""
    app_pid = 0
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            print(f"[失败] 进程提前退出，返回码 {proc.returncode}")
            if crash_log.is_file():
                print(crash_log.read_text(encoding="utf-8")[-1500:])
            return 1
        new = {h: v for h, v in _windows_with_title(args.title).items() if h not in before}
        if new:
            hwnd, (title, app_pid) = next(iter(new.items()))
            break
        time.sleep(0.5)

    ok = True
    if not hwnd:
        print(f"[失败] {args.timeout:.0f} 秒内没等到标题含「{args.title}」的窗口")
        ok = False
    else:
        left, top, right, bottom = _rect(hwnd)
        w, h = right - left, bottom - top
        print(f"[通过] 主窗口已出现：{title!r}  {w}×{h}px")
        if w < 600 or h < 400:
            print(f"[失败] 窗口尺寸异常：{w}×{h}")
            ok = False
        # 截图前把窗口顶到最前，并直接用 PrintWindow 渲染窗口内容
        _foreground(hwnd)
        time.sleep(args.settle)  # 等 Tk 把首帧画完
        try:
            capture_window(hwnd, shot)
            print(f"[通过] 截图已保存：{shot}")
        except Exception as exc:  # noqa: BLE001 - 截图失败不影响功能判定
            print(f"[警告] 截图失败：{exc}")
        _untopmost(hwnd)

    if crash_log.is_file():
        print("[失败] 运行期产生了崩溃日志")
        print(crash_log.read_text(encoding="utf-8")[-1500:])
        ok = False

    if args.keep:
        print("窗口保持打开（--keep）")
    else:
        _kill_tree(proc, app_pid)
        print("已关闭窗口")

    print("\n结论：" + ("通过" if ok else "失败"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

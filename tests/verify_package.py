"""验证打包产物：把 exe 搬到干净目录、屏蔽掉系统 Python，再逐项检查。

打包方案见 PACKAGING.md 第九节。这里做的是"单机等效隔离"：

- 产物整个复制到临时目录 → 证明它不依赖源码目录
- 启动时把 PATH 换成一个不含 Python 的 → 证明它不偷偷依赖已装的解释器
- 临时目录里先不放 config.json → 证明能靠默认值起来，且配置会落在 exe 旁边

用法：
    python tests/verify_package.py                      # 默认验 dist/auto_type/auto_type.exe
    python tests/verify_package.py dist/auto_type.exe   # 验 onefile 便携版
    python tests/verify_package.py --skip-gui           # 跳过会弹窗的图形界面检查

注意：默认会启动一次图形界面（约几秒后自动关闭），那几秒里屏幕上会闪一个窗口。
"""

from __future__ import annotations

import argparse
import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import auto_type  # noqa: E402  (用它统一解码子进程输出)

u = ctypes.windll.user32
k = ctypes.windll.kernel32

PASS, FAIL, SKIP = "通过", "失败", "跳过"
results: list[tuple[str, str, str]] = []


def record(name: str, status: str, detail: str = "") -> None:
    results.append((name, status, detail))
    mark = {PASS: "OK  ", FAIL: "FAIL", SKIP: "SKIP"}[status]
    print(f"  [{mark}] {name}" + (f" —— {detail}" if detail else ""))


# ────────────────────────────────────────────────────────── 干净环境的准备


def clean_env() -> dict:
    """一个不含 Python 的环境变量表。"""
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    env = {
        "SystemRoot": system_root,
        "windir": system_root,
        "TEMP": os.environ.get("TEMP", r"C:\Windows\Temp"),
        "TMP": os.environ.get("TMP", r"C:\Windows\Temp"),
        "PATH": rf"{system_root}\System32;{system_root}",
        "NUMBER_OF_PROCESSORS": os.environ.get("NUMBER_OF_PROCESSORS", "1"),
    }
    return env


def stage(artifact: Path) -> tuple[Path, Path]:
    """把产物复制到全新的临时目录。

    返回 (沙箱里的 exe 路径, 沙箱根目录)。后面所有检查都必须用**这份副本**——
    跑原始路径的话，等于没做隔离，而且 exe 会把 config.json 写回 dist/ 去。
    """
    root = Path(tempfile.mkdtemp(prefix="auto_type_clean_"))
    target = root / artifact.name
    if artifact.is_file():
        shutil.copy2(artifact, target)
        return target, root
    shutil.copytree(artifact, target)
    return target / f"{artifact.name}.exe", root


class Output:
    """跑出来的结果，stdout/stderr 已按系统本地编码解成文本。"""

    def __init__(self, code: int, out: str, err: str) -> None:
        self.returncode = code
        self.stdout = out
        self.stderr = err


def run(exe: Path, args: list[str], cwd: Path, timeout: int = 90) -> Output:
    completed = subprocess.run(
        [str(exe), *args],
        cwd=str(cwd),
        env=clean_env(),
        capture_output=True,
        timeout=timeout,
    )
    # 子进程按系统本地编码写管道（简中即 GB18030），不能假定 utf-8
    return Output(
        completed.returncode,
        auto_type.decode_text(completed.stdout),
        auto_type.decode_text(completed.stderr),
    )


# ────────────────────────────────────────────────────────────── 各项检查


def check_artifact_layout(exe: Path) -> None:
    """onedir 形态要确认 tkinter 那套真的被收进去了，否则界面起不来。

    注意别写死 Tk 8.6 的文件名：Python 3.14 带的是 Tk 9.0，DLL 叫
    `tcl90.dll` / `tcl9tk90.dll`，而且脚本库（init.tcl 那一套）是以 zip 形式
    内嵌在 DLL 里的，所以**没有** tcl/ 数据目录是正常的，不是漏收。
    """
    internal = exe.parent / "_internal"
    if not internal.exists():
        record("产物结构", PASS, "单文件形态，没有 _internal/")
        return

    # Tk 9.0 的两个 DLL 都叫 tcl*：tcl90.dll 是 Tcl，tcl9tk90.dll 是 Tk。
    # 别去找 tk*.dll，Tk 8.6 时代才是那个命名。
    missing = []
    if not (internal / "_tkinter.pyd").exists():
        missing.append("_tkinter.pyd")
    if not any(internal.glob("tcl*.dll")):
        missing.append("tcl*.dll（Tcl/Tk 运行库）")
    if not any(internal.glob("python3*.dll")):
        missing.append("python3*.dll")

    if missing:
        record("产物结构", FAIL, f"_internal/ 里缺 {', '.join(missing)}")
        return

    found = sorted(p.name for p in internal.glob("tcl*.dll"))
    record("产物结构", PASS, f"运行库齐全（_tkinter.pyd + {', '.join(found)}）")


def check_version_and_help(exe: Path, cwd: Path) -> None:
    completed = run(exe, ["--version"], cwd)
    text = (completed.stdout + completed.stderr).strip()
    if completed.returncode == 0 and "auto_type" in text:
        record("--version", PASS, text.splitlines()[0])
    else:
        record("--version", FAIL, f"exit={completed.returncode} 输出={text!r}")

    completed = run(exe, ["--help"], cwd)
    if completed.returncode == 0 and "--dry-run" in completed.stdout:
        record("--help", PASS, "参数表正常，且说明 windowed 打包下 stdout 已接回父控制台")
    else:
        record("--help", FAIL, f"exit={completed.returncode} 输出={completed.stdout[:120]!r}")


def check_dry_run(exe: Path, cwd: Path) -> None:
    payload = ROOT / "sample.txt"
    # 把语料也拷进沙箱，彻底不碰源码目录
    staged_payload = cwd / "sample.txt"
    if not staged_payload.exists():
        shutil.copy2(payload, staged_payload)

    completed = run(exe, ["--file", "sample.txt", "--dry-run", "--countdown", "0"], cwd)
    out = completed.stdout
    if completed.returncode == 0 and "预计耗时" in out and "干跑" in out:
        first_lines = [line for line in out.splitlines() if line.strip()][:3]
        record("--dry-run", PASS, " | ".join(first_lines))
    else:
        record(
            "--dry-run",
            FAIL,
            f"exit={completed.returncode} stdout={out[:200]!r} stderr={completed.stderr[:200]!r}",
        )


def check_config_lands_next_to_exe(exe: Path, cwd: Path) -> None:
    """这一条是 config_path() 修复的判定点。

    onefile 下 __file__ 指向 %TEMP%\\_MEIxxxxxx，修之前配置会写进那个临时目录
    （退出即删，等于没写）。修之后必须落在 exe 旁边。
    """
    config = cwd / "config.json"
    if config.exists():
        config.unlink()
    completed = run(exe, ["--file", "sample.txt", "--dry-run", "--delay-min", "45"], cwd)

    if not config.exists():
        detail = (completed.stderr or completed.stdout).strip().splitlines()
        record(
            "config.json 落点",
            FAIL,
            f"跑完没生成 config.json（exit={completed.returncode}"
            + (f"，{detail[0][:100]}" if detail else "")
            + "）",
        )
        return
    text = config.read_text(encoding="utf-8")
    if '"delay_min": 45' not in text:
        record("config.json 落点", FAIL, f"落点对但内容不对：{text[:160]}")
        return
    # 顺带确认它没把干跑/0 倒计时存进去
    if '"dry_run": true' in text or '"countdown": 0' in text:
        record("config.json 落点", FAIL, "把干跑或 0 倒计时写进配置了")
        return
    record("config.json 落点", PASS, f"落在 exe 同目录（{config.name}），干跑与 0 倒计时未入库")


def check_gui_launches(exe: Path, cwd: Path, timeout: float = 25.0) -> None:
    """无参数启动 → 图形界面应该出现一个标题为 auto_type 的窗口。"""
    process = subprocess.Popen([str(exe)], cwd=str(cwd), env=clean_env())
    hwnd = 0
    deadline = time.perf_counter() + timeout
    try:
        while time.perf_counter() < deadline:
            hwnd = u.FindWindowW(None, "auto_type")
            if hwnd:
                break
            if process.poll() is not None:
                break
            time.sleep(0.25)

        if hwnd:
            record("图形界面启动", PASS, f"窗口出现（hwnd={hwnd}），进程存活")
        elif process.poll() is not None:
            record("图形界面启动", FAIL, f"进程提前退出，退出码 {process.returncode}")
        else:
            record("图形界面启动", FAIL, f"{timeout:.0f} 秒内没出现窗口")
    finally:
        if hwnd:
            u.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


# ───────────────────────────────────────────────────── 真敲：跨进程注入


def typing_check(exe: Path, cwd: Path) -> None:
    """让 exe 往本进程建的原生 Edit 控件里敲，再读回来比对。

    这是唯一能证明"打包后内核仍然好用"的检查。但它要求跨进程键盘注入可用——
    有些受限环境（服务会话、UIPI 拦截、不同桌面）会直接拒绝，那种情况报"跳过"而不是失败。
    """
    import threading

    u.CreateWindowExW.restype = wintypes.HWND
    u.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, ctypes.c_void_p]
    u.SendMessageW.restype = ctypes.c_ssize_t

    WNDPROC = ctypes.WINFUNCTYPE(
        ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
    )
    u.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    u.DefWindowProcW.restype = ctypes.c_ssize_t

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HANDLE),
            ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HANDLE),
            ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR),
        ]

    class MSG(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND), ("message", wintypes.UINT),
            ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
            ("time", wintypes.DWORD), ("pt", wintypes.POINT),
        ]

    hinst = k.GetModuleHandleW(None)
    cls = "AutoTypePkgVerifyWnd"
    wc = WNDCLASSW(0, WNDPROC(u.DefWindowProcW), 0, 0, hinst, None, None, None, None, cls)
    u.RegisterClassW(ctypes.byref(wc))

    WS_OVERLAPPEDWINDOW = 0x00CF0000
    WS_CHILD, WS_VISIBLE, WS_VSCROLL = 0x40000000, 0x10000000, 0x00200000
    ES_MULTILINE, ES_AUTOVSCROLL = 0x0004, 0x0040

    hwnd = u.CreateWindowExW(
        0, cls, "exe 真敲验证（自动关闭）", WS_OVERLAPPEDWINDOW, 80, 80, 520, 300,
        None, None, hinst, None,
    )
    edit = u.CreateWindowExW(
        0x200, "EDIT", "", WS_CHILD | WS_VISIBLE | WS_VSCROLL | ES_MULTILINE | ES_AUTOVSCROLL,
        0, 0, 500, 250, hwnd, None, hinst, None,
    )
    u.ShowWindow(hwnd, 5)
    u.SetForegroundWindow(hwnd)
    u.SetFocus(edit)
    time.sleep(0.5)

    payload_path = cwd / "sample.txt"
    expected = payload_path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")

    def pump() -> None:
        msg = MSG()
        while u.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            u.TranslateMessage(ctypes.byref(msg))
            u.DispatchMessageW(ctypes.byref(msg))

    try:
        # 把节奏压到最小，验证省时间；倒计时留 1 秒给焦点就位
        processing = subprocess.Popen(
            [
                str(exe), "--file", str(payload_path), "--countdown", "1",
                "--no-humanize", "--delay-min", "15", "--delay-max", "25",
            ],
            cwd=str(cwd),
            env=clean_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        while processing.poll() is None:
            pump()
            time.sleep(0.01)
        settle = time.perf_counter() + 1.0
        while time.perf_counter() < settle:
            pump()
            time.sleep(0.01)

        raw_out, raw_err = processing.communicate()
        out = auto_type.decode_text(raw_out)
        err = auto_type.decode_text(raw_err)
        if processing.returncode != 0:
            detail = (err or out).strip().splitlines()
            message = detail[0] if detail else f"退出码 {processing.returncode}"
            if "WinError 5" in message or "拒绝" in message or "权限" in message:
                record("exe 真敲", SKIP, f"本环境不允许跨进程注入（{message[:80]}）")
            else:
                record("exe 真敲", FAIL, message[:160])
            return

        WM_GETTEXTLENGTH, WM_GETTEXT = 0x000E, 0x000D
        length = u.SendMessageW(edit, WM_GETTEXTLENGTH, 0, None)
        buf = ctypes.create_unicode_buffer(length + 1)
        u.SendMessageW(edit, WM_GETTEXT, length + 1, ctypes.cast(buf, ctypes.c_void_p))
        got = buf.value.replace("\r\n", "\n").rstrip("\n")

        if got == expected:
            record("exe 真敲", PASS, f"{len(expected)} 字符逐字符一致（含 emoji / 𠮷）")
        else:
            diff = next(
                (f"位置 {i}: 期望 {a!r} 实际 {b!r}" for i, (a, b) in enumerate(zip(expected, got)) if a != b),
                f"长度不同：期望 {len(expected)}，实际 {len(got)}",
            )
            record("exe 真敲", FAIL, diff)
    finally:
        u.DestroyWindow(hwnd)


# ───────────────────────────────────────────────────────────────────── 主流程


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="verify_package.py", description="验证打包产物")
    parser.add_argument("artifact", nargs="?", default=None, help="exe 或 onedir 目录")
    parser.add_argument("--skip-gui", action="store_true", help="跳过会弹窗的图形界面检查")
    parser.add_argument("--skip-typing", action="store_true", help="跳过真敲检查")
    args = parser.parse_args(argv)

    artifact = Path(args.artifact) if args.artifact else ROOT / "dist" / "auto_type"
    if not artifact.is_absolute():
        artifact = (ROOT / artifact).resolve()
    if not artifact.exists():
        print(f"找不到产物：{artifact}\n先跑 build.py", file=sys.stderr)
        return 1

    print(f"验证对象：{artifact.relative_to(ROOT) if artifact.is_relative_to(ROOT) else artifact}")

    exe, sandbox = stage(artifact)
    cwd = exe.parent
    print(f"沙箱副本：{exe}")
    print(f"路径过滤后 PATH：{clean_env()['PATH']}\n")

    print("检查：")
    check_artifact_layout(exe)
    check_version_and_help(exe, cwd)
    check_dry_run(exe, cwd)
    check_config_lands_next_to_exe(exe, cwd)
    if args.skip_typing:
        record("exe 真敲", SKIP, "命令行要求跳过")
    else:
        typing_check(exe, cwd)
    if args.skip_gui:
        record("图形界面启动", SKIP, "命令行要求跳过")
    else:
        check_gui_launches(exe, cwd)

    passed = sum(1 for _, status, _ in results if status == PASS)
    failed = sum(1 for _, status, _ in results if status == FAIL)
    skipped = sum(1 for _, status, _ in results if status == SKIP)
    print(f"\n结果：{passed} 通过 / {failed} 失败 / {skipped} 跳过")
    if failed:
        print("失败项：")
        for name, status, detail in results:
            if status == FAIL:
                print(f"  - {name}：{detail}")

    shutil.rmtree(sandbox, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

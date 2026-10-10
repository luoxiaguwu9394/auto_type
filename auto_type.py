"""auto_type —— 把 txt 语料逐字符敲进任意应用当前焦点输入区。

存在的理由：有些输入框禁掉了粘贴，只认真实的键盘事件。详见 README.md。
术语见 GLOSSARY.md，为什么不用粘贴见 docs/adr/0001-full-simulation-injection.md。

用法：
    python auto_type.py                     # 图形界面
    python auto_type.py --file 文档.txt      # 命令行
    python auto_type.py --file 文档.txt --dry-run

# TODO(roadmap): 支持打包成独立 exe（PyInstaller 一行命令，等内核稳定后再加）
"""

from __future__ import annotations

import argparse
import ctypes
import json
import math
import queue
import random
import sys
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Callable, Sequence

# 图形界面是可选的：没有 tkinter 的 Python 照样能用命令行
try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    HAS_TK = True
except ImportError:  # pragma: no cover - 取决于解释器有没有带 tkinter
    tk = ttk = filedialog = messagebox = None
    HAS_TK = False

LARGE_PAYLOAD_THRESHOLD = 50_000
CONFIG_FILENAME = "config.json"

# ────────────────────────────────────────────────────────────── Win32 适配层

user32 = ctypes.WinDLL("user32", use_last_error=True)

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_BACK = 0x08
VK_RETURN = 0x0D
VK_ESCAPE = 0x1B

_ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    # 联合必须把三个成员都声明全，否则 64 位下 sizeof(INPUT) 不是 40，SendInput 会错位
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUTUNION)]


user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT
user32.GetForegroundWindow.restype = ctypes.c_void_p
user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
user32.GetAsyncKeyState.restype = ctypes.c_short


class InjectionError(Exception):
    """按键没能送进系统输入队列。"""


def _send_inputs(inputs: Sequence[INPUT]) -> None:
    array = (INPUT * len(inputs))(*inputs)
    sent = user32.SendInput(len(inputs), array, ctypes.sizeof(INPUT))
    if sent != len(inputs):
        code = ctypes.get_last_error()
        if code == 5:  # ERROR_ACCESS_DENIED，UIPI 拦下来的典型症状
            raise InjectionError(
                "系统拒绝了这次按键注入（权限不足）。最常见的原因：目标程序是「以管理员身份运行」的，"
                "而敲字的这一方不是。把两边跑在同一权限级别再试。"
            )
        raise InjectionError(
            f"按键注入失败，只发出 {sent}/{len(inputs)} 个事件"
            f"（Windows 错误 {code}：{ctypes.FormatError(code)}）"
        )


def utf16_units(ch: str) -> list[int]:
    """一个字符拆成 UTF-16 码元。增补字符（emoji 等）是两个，必须分别发。"""
    encoded = ch.encode("utf-16-le")
    return [encoded[i] | (encoded[i + 1] << 8) for i in range(0, len(encoded), 2)]


def _unicode_inputs(unit: int) -> list[INPUT]:
    """一个 UTF-16 码元的按下 + 抬起。"""
    return [
        INPUT(INPUT_KEYBOARD, _INPUTUNION(ki=KEYBDINPUT(0, unit, KEYEVENTF_UNICODE, 0, 0))),
        INPUT(
            INPUT_KEYBOARD,
            _INPUTUNION(ki=KEYBDINPUT(0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, 0)),
        ),
    ]


def send_virtual_key(vk: int) -> None:
    down = INPUT(INPUT_KEYBOARD, _INPUTUNION(ki=KEYBDINPUT(vk, 0, 0, 0, 0)))
    up = INPUT(INPUT_KEYBOARD, _INPUTUNION(ki=KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP, 0, 0)))
    _send_inputs([down, up])


def send_stroke(stroke: "Stroke") -> None:
    if stroke.kind == "char":
        # TODO(roadmap): 超长语料可在这里改走剪贴板加速（Ctrl+V），需先探测目标是否吃粘贴
        # 一个字符的所有码元放进一次 SendInput：分两次发会留缝，
        # 输入法或目标自己可能插进来，增补字符的代理对就拼坏了
        inputs: list[INPUT] = []
        for unit in utf16_units(stroke.text):
            inputs.extend(_unicode_inputs(unit))
        _send_inputs(inputs)
    elif stroke.kind == "enter":
        send_virtual_key(VK_RETURN)
    elif stroke.kind == "backspace":
        send_virtual_key(VK_BACK)
    else:
        raise ValueError(f"未知笔画类型：{stroke.kind}")


def is_escape_pressed() -> bool:
    """Esc 是否正被按下。等待切片里轮询它，用来中止。"""
    # TODO(roadmap): 换成 RegisterHotKey 全局热键，配合常驻系统托盘
    return bool(user32.GetAsyncKeyState(VK_ESCAPE) & 0x8000)


# ───────────────────────────────────────────────────────────────────── 配置


@dataclass
class Config:
    delay_min: float = 30.0
    delay_max: float = 80.0
    jitter: float = 0.3
    humanize: bool = True
    send_enter: bool = True
    retract_probability: float = 0.015
    retract_max: int = 3
    line_pause_min: float = 250.0
    line_pause_max: float = 700.0
    countdown: float = 3.0
    encoding: str = "auto"
    dry_run: bool = False

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


def config_path() -> Path:
    return Path(__file__).resolve().parent / CONFIG_FILENAME


def load_config() -> Config:
    # TODO(roadmap): 支持每个语料文件一份独立配置（同名 .autotype.json 优先）
    try:
        return Config.from_dict(json.loads(config_path().read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return Config()


def sanitise_for_persistence(config: Config) -> Config:
    """有两样东西不能按原样写进配置，否则一次操作会永久改变行为：

    - 干跑是一次性动作。写进去的话，下次打开界面会莫名其妙停在"不真敲"。
    - 倒计时是安全缓冲（留给你把焦点切到目标）。一次 `--countdown 0` 要是存下来，
      之后每次都立刻开敲，字会敲到当前窗口身上。配置里不落 0。
      真想永久关掉，手工改 config.json——那是明确的、只对本地生效的选择。
    """
    return replace(config, dry_run=False, countdown=max(config.countdown, 1.0))


def save_config(config: Config) -> None:
    try:
        config_path().write_text(
            json.dumps(sanitise_for_persistence(config).to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


# ───────────────────────────────────────────────────────────────────── 语料


class PayloadError(Exception):
    """语料读不出来，或者认不出编码。"""


def load_payload(path: str | Path, encoding: str | None = "auto") -> str:
    source = Path(path)
    try:
        raw = source.read_bytes()
    except OSError as exc:
        raise PayloadError(f"读不到语料文件：{source}（{exc}）") from exc

    if encoding in (None, "", "auto"):
        candidates = ["utf-8-sig", "utf-8", "gb18030"]
    else:
        candidates = [encoding]

    for enc in candidates:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    raise PayloadError(
        f"认不出 {source} 的编码，试过 {', '.join(candidates)}；在图形界面的编码下拉框里手动指定"
    )


# ────────────────────────────────────────────────────────── 语料 → 笔画序列


@dataclass(frozen=True)
class Stroke:
    kind: str  # char | enter | backspace
    text: str
    wait_ms: float


def _char_wait(config: Config, rng: random.Random) -> float:
    wait = rng.uniform(config.delay_min, config.delay_max)
    if config.humanize and config.jitter:
        wait *= 1 + rng.uniform(-config.jitter, config.jitter)
    return max(0.0, wait)


def build_plan(payload: str, config: Config, rng: random.Random | None = None) -> list[Stroke]:
    """把语料编译成笔画序列。纯函数：随机源由外部注入，所以可以确定性测试。

    干跑就是"打印这个序列而不执行"，拟人（节奏、抖动、回退、行间停顿）全部发生在这里。
    """
    rng = rng or random.Random()
    payload = payload.replace("\r\n", "\n").replace("\r", "\n")
    strokes: list[Stroke] = []
    recent: list[str] = []

    for ch in payload:
        # TODO(roadmap): 支持 {ENTER}/{TAB} 这类特殊按键标记，这里做转义解析
        if ch == "\n" and config.send_enter:
            wait = (
                rng.uniform(config.line_pause_min, config.line_pause_max)
                if config.humanize
                else _char_wait(config, rng)
            )
            strokes.append(Stroke("enter", "\n", wait))
            recent.clear()
            continue

        actual = " " if ch == "\n" else ch
        strokes.append(Stroke("char", actual, _char_wait(config, rng)))

        # 增补字符（emoji、生僻字）占两个 UTF-16 码元，而 recent 是按"字"计数的。
        # 目标端一个退格未必删得掉整个字——只删一半时，我们对"目标里现在有什么"的认知就错了，
        # 之后每退一次错位就放大一次，表现就是删错位置、把字打成了邻居字。
        # 所以把它当成同步屏障：屏障前的不再参与回退，它自己也不回退。
        if len(utf16_units(actual)) > 1:
            recent.clear()
            continue

        recent.append(actual)

        if config.humanize and rng.random() < config.retract_probability:
            count = rng.randint(1, min(config.retract_max, len(recent)))
            removed = recent[-count:]
            del recent[-count:]
            for _ in range(count):
                strokes.append(Stroke("backspace", "\b", _char_wait(config, rng)))
            for char in removed:
                strokes.append(Stroke("char", char, _char_wait(config, rng)))
                recent.append(char)

    return strokes


def estimate_seconds(strokes: Sequence[Stroke]) -> float:
    return sum(stroke.wait_ms for stroke in strokes) / 1000.0


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f} 秒"
    return f"{int(seconds // 60)} 分 {int(seconds % 60)} 秒"


# ───────────────────────────────────────────────────────────────────── 执行


@dataclass
class TypingResult:
    typed: int
    aborted: bool


def _countdown(seconds: float, on_status, abort: Callable[[], bool]) -> bool:
    remaining = seconds
    while remaining > 0:
        if abort():
            return False
        if on_status:
            on_status(f"{math.ceil(remaining)} 秒后开始——现在把光标放到目标里")
        step = min(0.1, remaining)
        time.sleep(step)
        remaining -= step
    return True


def _wait(seconds: float, abort, on_status, hwnd) -> bool:
    """可中断的等待，顺带做焦点监护：焦点离开就暂停，回来自动继续。"""
    deadline = time.perf_counter() + seconds
    paused = False
    while True:
        if abort():
            return False
        if hwnd is not None and user32.GetForegroundWindow() != hwnd:
            if not paused:
                paused = True
                if on_status:
                    on_status("已暂停：焦点离开了目标窗口，切回去会自动继续")
            time.sleep(0.1)
            continue
        if paused:
            paused = False
            if on_status:
                on_status("焦点回来了，继续")
        now = time.perf_counter()
        if now >= deadline:
            return True
        time.sleep(min(0.01, deadline - now))


def execute_plan(
    strokes: Sequence[Stroke],
    config: Config,
    total_chars: int | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    on_status: Callable[[str], None] | None = None,
    should_abort: Callable[[], bool] | None = None,
) -> TypingResult:
    total = len(strokes)
    goal = total_chars if total_chars is not None else total
    net = 0
    aborted = False

    def abort() -> bool:
        return bool(should_abort and should_abort())

    hwnd = None
    if not config.dry_run:
        if not _countdown(config.countdown, on_status, abort):
            return TypingResult(typed=0, aborted=True)
        # TODO(roadmap): 支持按屏幕坐标先点一下再敲、以及 UI Automation 控件定位
        # 倒计时结束后才记录前台窗口——这时使用者已经切到目标了
        hwnd = user32.GetForegroundWindow()

    for stroke in strokes:
        if abort():
            aborted = True
            break
        # 干跑只走序列：不等待、不发送，所以这里就是"一个按键都不会发出去"的唯一保证
        if not config.dry_run:
            if not _wait(stroke.wait_ms / 1000.0, abort, on_status, hwnd):
                aborted = True
                break
            send_stroke(stroke)
        net += 1 if stroke.kind == "char" else (-1 if stroke.kind == "backspace" else 0)
        if on_progress:
            on_progress(net, goal)

    return TypingResult(typed=net, aborted=aborted)


def format_dry_run(payload: str, strokes: Sequence[Stroke], config: Config) -> str:
    # 先归一化再统计，否则 CRLF 会让"字符数"比真正敲出去的多（一个 \r 是不发的）
    payload = payload.replace("\r\n", "\n").replace("\r", "\n")
    backspaces = sum(1 for s in strokes if s.kind == "backspace")
    lines = [
        "干跑：下面只是计划，一个按键都不会真的发出去",
        "",
        f"语料：{len(payload)} 个字符，{payload.count(chr(10)) + 1} 行",
        f"笔画：{len(strokes)} 笔（其中回退 {backspaces} 次）",
        f"拟人：{'开' if config.humanize else '关'}，节奏 {config.delay_min:.0f}–{config.delay_max:.0f} ms/字",
        f"预计耗时：{format_duration(estimate_seconds(strokes))}",
    ]
    preview = strokes[:8]
    if preview:
        lines.append("")
        lines.append("前几笔：")
        for stroke in preview:
            label = {"char": stroke.text, "enter": "⏎", "backspace": "⌫"}.get(stroke.kind, "?")
            lines.append(f"  等 {stroke.wait_ms:.0f} ms → {label}")
    return "\n".join(lines)


# ───────────────────────────────────────────────────────────────────── 命令行


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="auto_type",
        description="把 txt 语料逐字符敲进任意应用当前焦点输入区。",
    )
    parser.add_argument("--file", help="语料文件路径")
    parser.add_argument("--delay-min", type=float, help="节奏下限（毫秒/字）")
    parser.add_argument("--delay-max", type=float, help="节奏上限（毫秒/字）")
    parser.add_argument("--jitter", type=float, help="抖动幅度 0–1")
    parser.add_argument("--no-humanize", action="store_true", help="关闭拟人：匀速、无回退")
    parser.add_argument("--humanize", action="store_true", help="开启拟人")
    parser.add_argument("--no-enter", action="store_true", help="换行不敲回车，转成空格")
    parser.add_argument("--encoding", help="编码，默认自动检测（UTF-8 → GB18030）")
    parser.add_argument("--countdown", type=float, help="倒计时秒数")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不真发按键")
    parser.add_argument("--yes", action="store_true", help="超长语料也不再确认")
    parser.add_argument("--gui", action="store_true", help="打开图形界面")
    return parser


def run_cli(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    config = load_config()
    # 显式映射，别用"参数名 == 配置字段名"的通用覆盖：
    # --humanize / --no-humanize 默认都是 False，通用覆盖会把存好的拟人开关冲掉
    overrides = {}
    for arg_name in ("delay_min", "delay_max", "jitter", "countdown", "encoding"):
        value = getattr(args, arg_name)
        if value is not None:
            overrides[arg_name] = value
    if args.no_humanize:
        overrides["humanize"] = False
    elif args.humanize:
        overrides["humanize"] = True
    if args.no_enter:
        overrides["send_enter"] = False
    overrides["dry_run"] = bool(args.dry_run)
    config = replace(config, **overrides)
    save_config(config)

    if not args.file:
        parser.error("命令行需要 --file；想用图形界面就别带参数，或加 --gui")

    try:
        payload = load_payload(args.file, None if config.encoding == "auto" else config.encoding)
    except PayloadError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1

    # TODO(roadmap): 支持一次传入多个语料文件排队批量敲
    strokes = build_plan(payload, config)

    if config.dry_run:
        # 走同一条执行路径，"干跑不发按键"的保证只有一处实现
        execute_plan(strokes, config, total_chars=len(payload))
        print(format_dry_run(payload, strokes, config))
        return 0

    if len(payload) > LARGE_PAYLOAD_THRESHOLD and not args.yes:
        print(
            f"语料 {len(payload)} 个字符，预计 {format_duration(estimate_seconds(strokes))}。"
            f"确认要敲就加 --yes。",
            file=sys.stderr,
        )
        return 1

    print(f"共 {len(payload)} 个字符。按 Esc 中止。", flush=True)

    def on_progress(net: int, target: int) -> None:
        print(f"\r已敲 {net}/{target}", end="", flush=True)

    def on_status(message: str) -> None:
        print(f"\r{message}          ", flush=True)

    try:
        result = execute_plan(
            strokes,
            config,
            total_chars=len(payload),
            on_progress=on_progress,
            on_status=on_status,
            should_abort=is_escape_pressed,
        )
    except InjectionError as exc:
        print()
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    print()
    print("已中止" if result.aborted else "敲完了")
    return 0


# ─────────────────────────────────────────────────────────────────── 图形界面

PRESETS = {"慢": (80.0, 160.0), "中": (30.0, 80.0), "快": (5.0, 20.0), "自定义": None}


class App:
    """图形界面。敲字跑在工作线程里，结果通过队列回传给主线程——tkinter 只能主线程碰。"""

    def __init__(self, root: "tk.Tk") -> None:
        self.root = root
        self.root.title("auto_type")
        self.root.resizable(False, False)
        self.messages: "queue.Queue[dict]" = queue.Queue()
        self.abort_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.config = load_config()
        self._build()
        self.root.after(50, self._drain)

    # -- 界面 ---------------------------------------------------------
    def _build(self) -> None:
        pad = {"padx": 8, "pady": 4}
        frame = ttk.Frame(self.root, padding=12)
        frame.grid()

        self.file_var = tk.StringVar()
        ttk.Label(frame, text="语料文件").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(frame, textvariable=self.file_var, width=42).grid(row=0, column=1, **pad)
        ttk.Button(frame, text="浏览…", command=self._pick_file).grid(row=0, column=2, **pad)

        ttk.Label(frame, text="编码").grid(row=1, column=0, sticky="w", **pad)
        self.encoding_var = tk.StringVar(value=self.config.encoding)
        ttk.Combobox(
            frame,
            textvariable=self.encoding_var,
            values=("auto", "utf-8", "utf-8-sig", "gb18030"),
            width=10,
            state="readonly",
        ).grid(row=1, column=1, sticky="w", **pad)

        ttk.Label(frame, text="节奏档位").grid(row=2, column=0, sticky="w", **pad)
        self.preset_var = tk.StringVar(value="中")
        preset = ttk.Combobox(
            frame,
            textvariable=self.preset_var,
            values=tuple(PRESETS),
            width=10,
            state="readonly",
        )
        preset.grid(row=2, column=1, sticky="w", **pad)
        preset.bind("<<ComboboxSelected>>", self._apply_preset)

        ttk.Label(frame, text="节奏区间（毫秒/字）").grid(row=3, column=0, sticky="w", **pad)
        range_row = ttk.Frame(frame)
        range_row.grid(row=3, column=1, sticky="w", **pad)
        self.delay_min_var = tk.StringVar(value=str(self.config.delay_min))
        self.delay_max_var = tk.StringVar(value=str(self.config.delay_max))
        ttk.Entry(range_row, textvariable=self.delay_min_var, width=7).grid(row=0, column=0)
        ttk.Label(range_row, text="–").grid(row=0, column=1, padx=4)
        ttk.Entry(range_row, textvariable=self.delay_max_var, width=7).grid(row=0, column=2)

        ttk.Label(frame, text="抖动幅度").grid(row=4, column=0, sticky="w", **pad)
        self.jitter_var = tk.DoubleVar(value=self.config.jitter)
        ttk.Scale(
            frame, from_=0.0, to=1.0, variable=self.jitter_var, orient="horizontal", length=200
        ).grid(row=4, column=1, **pad)

        ttk.Label(frame, text="回退概率（%）").grid(row=5, column=0, sticky="w", **pad)
        self.retract_var = tk.DoubleVar(value=self.config.retract_probability * 100)
        ttk.Scale(
            frame, from_=0.0, to=10.0, variable=self.retract_var, orient="horizontal", length=200
        ).grid(row=5, column=1, **pad)

        self.humanize_var = tk.BooleanVar(value=self.config.humanize)
        ttk.Checkbutton(
            frame, text="拟人（抖动 + 回退 + 行间停顿）", variable=self.humanize_var
        ).grid(row=6, column=1, sticky="w", **pad)

        self.enter_var = tk.BooleanVar(value=self.config.send_enter)
        ttk.Checkbutton(frame, text="换行敲回车", variable=self.enter_var).grid(
            row=7, column=1, sticky="w", **pad
        )

        self.dry_var = tk.BooleanVar(value=self.config.dry_run)
        ttk.Checkbutton(frame, text="干跑（不真敲）", variable=self.dry_var).grid(
            row=8, column=1, sticky="w", **pad
        )

        ttk.Label(frame, text="倒计时（秒）").grid(row=9, column=0, sticky="w", **pad)
        self.countdown_var = tk.StringVar(value=str(self.config.countdown))
        ttk.Entry(frame, textvariable=self.countdown_var, width=7).grid(
            row=9, column=1, sticky="w", **pad
        )

        buttons = ttk.Frame(frame)
        buttons.grid(row=10, column=1, sticky="w", **pad)
        self.start_button = ttk.Button(buttons, text="开始", command=self._start)
        self.start_button.grid(row=0, column=0, padx=(0, 8))
        self.abort_button = ttk.Button(buttons, text="中止", command=self._abort, state="disabled")
        self.abort_button.grid(row=0, column=1)

        self.progress = ttk.Progressbar(
            frame, orient="horizontal", length=320, mode="determinate"
        )
        self.progress.grid(row=11, column=0, columnspan=3, **pad)

        self.status_var = tk.StringVar(value="选好语料，把光标点进目标，然后开始")
        ttk.Label(frame, textvariable=self.status_var).grid(
            row=12, column=0, columnspan=3, sticky="w", **pad
        )
        ttk.Label(frame, text="敲字过程中按 Esc 也能中止", foreground="#666666").grid(
            row=13, column=0, columnspan=3, sticky="w", **pad
        )

    # -- 交互 ---------------------------------------------------------
    def _pick_file(self) -> None:
        path = filedialog.askopenfilename(
            title="选择语料文件", filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")]
        )
        if path:
            self.file_var.set(path)

    def _apply_preset(self, _event=None) -> None:
        pair = PRESETS.get(self.preset_var.get())
        if pair is None:
            return
        self.delay_min_var.set(str(pair[0]))
        self.delay_max_var.set(str(pair[1]))

    def _collect_config(self) -> Config | None:
        try:
            delay_min = float(self.delay_min_var.get())
            delay_max = float(self.delay_max_var.get())
            countdown = float(self.countdown_var.get())
        except ValueError:
            messagebox.showerror("参数不对", "节奏区间和倒计时要填数字")
            return None
        if delay_min < 0 or delay_max < delay_min or countdown < 0:
            messagebox.showerror("参数不对", "节奏下限要 ≥ 0，上限要 ≥ 下限")
            return None
        return replace(
            self.config,
            delay_min=delay_min,
            delay_max=delay_max,
            jitter=self.jitter_var.get(),
            humanize=self.humanize_var.get(),
            send_enter=self.enter_var.get(),
            retract_probability=self.retract_var.get() / 100.0,
            countdown=countdown,
            encoding=self.encoding_var.get(),
            dry_run=self.dry_var.get(),
        )

    def _start(self) -> None:
        path = self.file_var.get().strip()
        if not path:
            messagebox.showerror("还没选语料", "先挑一个 txt 文件")
            return
        config = self._collect_config()
        if config is None:
            return
        try:
            payload = load_payload(path, None if config.encoding == "auto" else config.encoding)
        except PayloadError as exc:
            messagebox.showerror("语料读不出来", str(exc))
            return
        if not payload:
            messagebox.showerror("语料是空的", f"{path} 里没有内容")
            return

        self.config = config
        save_config(config)
        strokes = build_plan(payload, config)

        if config.dry_run:
            # 与命令行同一条路径：走一遍序列但不发送
            execute_plan(strokes, config, total_chars=len(payload))
            messagebox.showinfo("干跑结果", format_dry_run(payload, strokes, config))
            return

        if len(payload) > LARGE_PAYLOAD_THRESHOLD:
            if not messagebox.askyesno(
                "语料很长",
                f"{len(payload)} 个字符，预计 {format_duration(estimate_seconds(strokes))}。"
                "确定要开始吗？",
            ):
                return

        self.abort_event.clear()
        self.start_button.config(state="disabled")
        self.abort_button.config(state="enabled")
        self.progress.config(maximum=len(payload), value=0)
        self.worker = threading.Thread(
            target=self._run_worker, args=(strokes, config, len(payload)), daemon=True
        )
        self.worker.start()

    def _abort(self) -> None:
        self.abort_event.set()

    def _run_worker(self, strokes, config, total_chars) -> None:
        def should_abort() -> bool:
            return self.abort_event.is_set() or is_escape_pressed()

        try:
            result = execute_plan(
                strokes,
                config,
                total_chars=total_chars,
                on_progress=lambda net, total: self.messages.put(
                    {"type": "progress", "net": net, "total": total}
                ),
                on_status=lambda message: self.messages.put(
                    {"type": "status", "message": message}
                ),
                should_abort=should_abort,
            )
        except Exception as exc:  # 兜底：别让异常把界面永久卡在"运行中"
            self.messages.put({"type": "error", "message": str(exc)})
            return
        self.messages.put({"type": "done", "aborted": result.aborted})

    def _drain(self) -> None:
        try:
            while True:
                message = self.messages.get_nowait()
                kind = message["type"]
                if kind == "progress":
                    self.progress.config(value=message["net"])
                    self.status_var.set(f"已敲 {message['net']}/{message['total']}")
                elif kind == "status":
                    self.status_var.set(message["message"])
                elif kind == "done":
                    self.start_button.config(state="enabled")
                    self.abort_button.config(state="disabled")
                    self.status_var.set(
                        "已中止（敲进去的内容不会回滚）" if message["aborted"] else "敲完了"
                    )
                elif kind == "error":
                    self.start_button.config(state="enabled")
                    self.abort_button.config(state="disabled")
                    self.status_var.set(f"出错了：{message['message']}")
        except queue.Empty:
            pass
        self.root.after(50, self._drain)


def launch_gui() -> int:
    if not HAS_TK:
        print(
            "这个 Python 没带 tkinter，图形界面起不来。\n"
            "换用官方安装包装的 Python（默认带 tkinter），或者直接用命令行：\n"
            "  python auto_type.py --file 文档.txt",
            file=sys.stderr,
        )
        return 1
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0


# ─────────────────────────────────────────────────────────────────────── 入口


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        launch_gui()
        return 0
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.gui:
        launch_gui()
        return 0
    try:
        return run_cli(parser, args)
    except PayloadError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

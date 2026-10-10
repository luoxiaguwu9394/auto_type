"""在同进程里建一个原生 Win32 Edit 控件当目标。

用来区分：增补字符出错到底是"我们发错了"，还是"tkinter 自己把代理对拼错了"。
原生 Edit 控件是 Windows 最标准的目标，它说对就是对。
"""

import ctypes
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import auto_type  # noqa: E402

u = ctypes.windll.user32
k = ctypes.windll.kernel32

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
u.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
u.DefWindowProcW.restype = ctypes.c_ssize_t
u.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
]
u.CreateWindowExW.restype = wintypes.HWND
u.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, ctypes.c_void_p]
u.SendMessageW.restype = ctypes.c_ssize_t


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
wc = WNDCLASSW(0, WNDPROC(u.DefWindowProcW), 0, 0, hinst, None, None, None, None, "AutoTypeProbeWnd")
u.RegisterClassW(ctypes.byref(wc))

WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_CHILD, WS_VISIBLE, WS_VSCROLL = 0x40000000, 0x10000000, 0x00200000
ES_MULTILINE, ES_AUTOVSCROLL = 0x0004, 0x0040

hwnd = u.CreateWindowExW(0, "AutoTypeProbeWnd", "E2E 原生 Edit 探针（自动关闭）", WS_OVERLAPPEDWINDOW,
                         60, 60, 520, 300, None, None, hinst, None)
edit = u.CreateWindowExW(0x200, "EDIT", "", WS_CHILD | WS_VISIBLE | WS_VSCROLL | ES_MULTILINE | ES_AUTOVSCROLL,
                         0, 0, 500, 250, hwnd, None, hinst, None)
u.ShowWindow(hwnd, 5)
u.SetForegroundWindow(hwnd)
u.SetFocus(edit)
time.sleep(0.5)

WM_GETTEXTLENGTH, WM_GETTEXT, WM_SETTEXT = 0x000E, 0x000D, 0x000C


def pump_once():
    msg = MSG()
    while u.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
        u.TranslateMessage(ctypes.byref(msg))
        u.DispatchMessageW(ctypes.byref(msg))


def type_and_read(payload, config, label):
    expected = payload.replace("\r\n", "\n").replace("\r", "\n")  # 语料先归一化 CRLF
    empty = ctypes.create_unicode_buffer("")
    u.SendMessageW(edit, WM_SETTEXT, 0, ctypes.cast(empty, ctypes.c_void_p))
    u.SetForegroundWindow(hwnd)
    u.SetFocus(edit)
    time.sleep(0.3)

    strokes = auto_type.build_plan(payload, config)
    worker = threading.Thread(
        target=auto_type.execute_plan, args=(strokes, config),
        kwargs={"total_chars": len(payload)},
    )
    worker.start()
    while worker.is_alive():
        pump_once()
        time.sleep(0.005)
    worker.join()

    # SendInput 是异步的，敲完还要继续泵一会儿，最后几个按键才会落进控件
    settle = time.perf_counter() + 0.8
    while time.perf_counter() < settle:
        pump_once()
        time.sleep(0.01)

    n = u.SendMessageW(edit, WM_GETTEXTLENGTH, 0, None)
    buf = ctypes.create_unicode_buffer(n + 1)
    u.SendMessageW(edit, WM_GETTEXT, n + 1, ctypes.cast(buf, ctypes.c_void_p))
    # 原生 Edit 控件把回车存成 CRLF，先归一化再比
    got = buf.value.replace("\r\n", "\n")

    print(f"\n--- {label} ---")
    print("笔画:", len(strokes), "退格:", sum(1 for s in strokes if s.kind == "backspace"))
    print("期望:", repr(expected))
    print("实际:", repr(got))
    print("一致:", got == expected)
    if got != expected:
        for i, (a, b) in enumerate(zip(expected, got)):
            if a != b:
                print(f"  首个不同 位置{i}: 期望 U+{ord(a):04X} 实际 U+{ord(b):04X}")
                break
        else:
            print(f"  长度不同：期望 {len(expected)} 实际 {len(got)}")
    return got == expected


def _retracting_config():
    return auto_type.Config(
        countdown=0, delay_min=20, delay_max=30, humanize=True, jitter=0.0,
        retract_probability=1.0, retract_max=3, line_pause_min=30, line_pause_max=30,
    )


if len(sys.argv) > 1 and sys.argv[1] == "stress":
    path = sys.argv[2] if len(sys.argv) > 2 else "sample.txt"
    payload = auto_type.load_payload(path)
    ok = type_and_read(
        payload,
        auto_type.Config(countdown=0, delay_min=30, delay_max=80),  # 默认节奏、拟人全开
        f"压力测试 默认节奏30-80ms · {path}",
    )
    u.DestroyWindow(hwnd)
    print("\n压力测试一致:", ok)
    sys.exit(0 if ok else 1)

results = [
    type_and_read(
        "𠮷𠮷𠮷 中文 😀🎉 abc",
        auto_type.Config(countdown=0, delay_min=20, delay_max=30, humanize=False),
        "用例1 增补字符 + 关拟人",
    ),
    type_and_read("前段 中文 😀🎉 与 𠮷 混排 abc 尾巴", _retracting_config(), "用例2 回退100% + 增补字符混排"),
    type_and_read("第一行 中文\n第二行 😀 与 𠮷\n第三行 abc", _retracting_config(), "用例3 多行 + 回退100%"),
]

u.DestroyWindow(hwnd)
print("\n全部一致:", all(results))
sys.exit(0 if all(results) else 1)

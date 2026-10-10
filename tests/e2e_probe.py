"""受控 E2E：开一个自己能读回内容的真实窗口当目标，把语料真敲进去，再比对。

专门用来判断「回退的退格到底有没有真的删掉字符」。会短暂占用前台，跑完自动关窗。
"""

import ctypes
import random
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tkinter as tk

import auto_type

user32 = ctypes.windll.user32


def run_case(root, text, payload, config, seed, label):
    text.delete("1.0", "end")
    root.update()

    hwnd = root.winfo_id()
    user32.SetForegroundWindow(hwnd)
    text.focus_force()
    root.update()
    time.sleep(0.4)

    strokes = auto_type.build_plan(payload, config, rng=random.Random(seed))
    deadline = time.perf_counter() + 20

    worker = threading.Thread(
        target=auto_type.execute_plan,
        args=(strokes, config),
        kwargs={"total_chars": len(payload), "should_abort": lambda: time.perf_counter() > deadline},
    )
    worker.start()

    # 主线程泵消息，否则窗口收不到按键
    while worker.is_alive():
        root.update()
        time.sleep(0.01)
    worker.join()

    # SendInput 是异步的：敲完还得继续泵一会儿，最后几个按键才会落进控件
    settle_until = time.perf_counter() + 0.8
    while time.perf_counter() < settle_until:
        root.update()
        time.sleep(0.01)

    expected = payload.replace("\r\n", "\n").replace("\r", "\n")  # 语料先归一化 CRLF
    got = text.get("1.0", "end-1c")
    print(f"\n--- {label} ---")
    print("笔画数:", len(strokes), "退格数:", sum(1 for s in strokes if s.kind == "backspace"))
    if got == expected:
        print("一致: True")
    else:
        print("一致: False")
        print("期望:", repr(expected))
        print("实际:", repr(got))
        for i, (a, b) in enumerate(zip(expected, got)):
            if a != b:
                print(f"  首个不同位置 {i}: 期望 {a!r} 实际 {b!r}")
                break
        else:
            print(f"  长度不同：期望 {len(expected)}，实际 {len(got)}")
    return got == expected


def run_stress(root, text, payload_path):
    """用真实语料、按默认节奏（30–80ms）真敲一遍，看会不会丢字或重复。"""
    payload = auto_type.load_payload(payload_path)
    cfg = auto_type.Config(countdown=0, delay_min=30, delay_max=80)
    return run_case(
        root, text, payload, cfg, 1, f"压力测试 默认节奏30-80ms · {len(payload)} 字符"
    )


def main():
    root = tk.Tk()
    root.title("E2E 探针（会自动关闭）")
    root.geometry("520x220+80+80")
    root.attributes("-topmost", True)
    text = tk.Text(root, font=("Consolas", 11))
    text.pack(fill="both", expand=True)
    root.update()
    text.focus_force()

    results = []

    if len(sys.argv) > 1 and sys.argv[1] == "stress":
        stress_path = sys.argv[2] if len(sys.argv) > 2 else "sample.txt"
        ok = run_stress(root, text, stress_path)
        root.destroy()
        print("\n压力测试一致:", ok)
        return 0 if ok else 1

    # 用例 1：拟人全开、回退概率 100%——退格一定会发生
    cfg_retract = auto_type.Config(
        countdown=0,
        delay_min=5,
        delay_max=10,
        jitter=0.0,
        humanize=True,
        retract_probability=1.0,
        retract_max=3,
        line_pause_min=20,
        line_pause_max=20,
    )
    results.append(
        run_case(root, text, "abcdefghij", cfg_retract, 0, "用例1 纯英文 + 回退概率100%")
    )

    # 用例 2：中文 + emoji + 换行，同样全开回退
    results.append(
        run_case(root, text, "中文😀\n第二行", cfg_retract, 7, "用例2 中文+emoji+换行 + 回退100%")
    )

    # 用例 3：关掉拟人，匀速无回退——作为对照
    cfg_plain = auto_type.Config(
        countdown=0, delay_min=5, delay_max=10, jitter=0.0, humanize=False
    )
    results.append(run_case(root, text, "abcdefghij", cfg_plain, 0, "用例3 关拟人（对照）"))

    root.destroy()
    print("\n全部一致:", all(results))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())

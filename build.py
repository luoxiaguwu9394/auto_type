"""把 auto_type 打包成 Windows 可执行文件。

方案与取舍见 PACKAGING.md。要点：

- 必须用**带 tkinter 的 Python**运行本脚本（本机是 `C:\\Python314\\python.exe`）。
  托管 Python 3.13 没带 tkinter，打出来的 exe 图形界面起不来，脚本会提前拦住。
- 不维护 .spec：PyInstaller 的参数都在这里，单一事实来源，避免两份配置漂移。
  PyInstaller 自己生成的 .spec 落到 build/ 里，已被 .gitignore 忽略。

用法：
    python build.py                # onedir → dist/auto_type/（日常用，启动快）
    python build.py --onefile      # 再出一个 onefile → dist/auto_type.exe（发人用）
    python build.py --console      # 打一版带控制台的，专门用来排查"启动即闪退"
    python build.py --clean        # 先清掉 build/ 和 dist/
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import auto_type  # noqa: E402  (借它的 decode_text 读子进程输出，见 smoke())

DIST = ROOT / "dist"
BUILD = ROOT / "build"
ICON = ROOT / "assets" / "auto_type.ico"
VERSION_FILE = ROOT / "assets" / "version_info.txt"
ENTRY = ROOT / "auto_type.py"

APP_NAME = "auto_type"

# 本项目只用标准库。下面这些排掉，理由分三类：
# 注意：**不能**排 tkinter / _tkinter / tcl / tk，图形界面就靠它们。
EXCLUDES = [
    # 1) 被 hook 误拉进来才有意义的三方库
    "numpy",
    "pandas",
    "matplotlib",
    "scipy",
    "PIL",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
    "IPython",
    "pytest",
    "unittest",
    "setuptools",
    "pkg_resources",
    "pip",
    "wheel",
    "sqlite3",
    "curses",
    # 2) TLS / 网络栈。本项目一个字都不联网，但 random -> hashlib 之外的那条
    #    链会把 _ssl 和 _hashlib 一起拖进来，连带 OpenSSL 的 libcrypto-3.dll
    #    (6.1 MB) + libssl-3.dll (1.3 MB)。排除后 hashlib 会退回内置的
    #    _sha2/_md5 实现（CPython 里那几处 import _hashlib 都是 try/except 守卫），
    #    random 的种子初始化照常工作。
    "ssl",
    "_ssl",
    "_hashlib",
    "socket",
    "_socket",
    "select",
    "selectors",
    "ftplib",
    "http",
    "urllib",
    "email",
    "xml",
    "xmlrpc",
    "asyncio",
    # 3) 压缩编解码，只有 shutil / zipfile 用得到，且都是 try/except 守卫导入。
    #    注意 **不能**排 zipfile：PyInstaller 自己的运行时钩子 pyi_rth_inspect
    #    要 import 它，排掉会直接 ModuleNotFoundError 起不来。
    "bz2",
    "_bz2",
    "lzma",
    "_lzma",
]


def check_environment() -> None:
    """打包链的前提条件，不满足就直说，别让 PyInstaller 打到一半才报错。"""
    problems = []
    try:
        import tkinter  # noqa: F401
    except ImportError:
        problems.append(
            f"当前解释器没有 tkinter：{sys.executable}\n"
            "  换用带 tkinter 的官方 Python 打包，本机可用：C:\\Python314\\python.exe"
        )
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        problems.append(f"没装 PyInstaller，先装：{sys.executable} -m pip install pyinstaller")

    for asset in (ICON, VERSION_FILE):
        if not asset.exists():
            problems.append(f"缺资源文件：{asset.relative_to(ROOT)}")
    if not ENTRY.exists():
        problems.append(f"缺入口文件：{ENTRY.relative_to(ROOT)}")

    if problems:
        raise SystemExit("打包前提不满足：\n- " + "\n- ".join(problems))


def pyinstaller_command(variant: str, console: bool) -> list[str]:
    # 两种形态各用各的 workpath/specpath：共用一个目录时 PyInstaller 的中间产物
    # 会互相污染，产出对不上。
    work = BUILD / variant
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--name",
        APP_NAME,
        "--icon",
        str(ICON),
        "--version-file",
        str(VERSION_FILE),
        "--distpath",
        str(DIST),
        "--workpath",
        str(work),
        "--specpath",
        str(work),
        # UPX 压缩是杀软误报的头号诱因，宁可大几 MB 也不要它
        "--noupx",
    ]
    command += ["--console"] if console else ["--noconsole"]
    command += ["--onefile"] if variant == "onefile" else ["--onedir"]
    for module in EXCLUDES:
        command += ["--exclude-module", module]
    command.append(str(ENTRY))
    return command


def build(variant: str, console: bool) -> tuple[bool, str]:
    label = f"{variant}{'（带控制台）' if console else ''}"
    command = pyinstaller_command(variant, console)
    print(f"\n=== 打包 {label} ===")
    print(" ".join(command))
    started = time.perf_counter()
    completed = subprocess.run(command, cwd=ROOT)
    elapsed = time.perf_counter() - started
    if completed.returncode != 0:
        return False, f"{label} 打包失败，退出码 {completed.returncode}"
    print(f"--- {label} 完成，用时 {elapsed:.1f}s")
    return True, ""


def report() -> None:
    print("\n=== 产物 ===")
    produced = []
    for target in (DIST / APP_NAME, DIST / f"{APP_NAME}.exe"):
        if not target.exists():
            continue
        # 单目录形态要把整棵树的体积算进去，只看 exe 会严重低估
        if target.is_file():
            produced.append(("onefile（单文件）", target, target.stat().st_size))
        else:
            total = sum(item.stat().st_size for item in target.rglob("*") if item.is_file())
            produced.append(("onedir（单目录）", target, total))

    for kind, target, size in produced:
        print(f"  {target.relative_to(ROOT)}  {kind}  {size / (1024 * 1024):.1f} MB")

    if not produced:
        print("  （什么都没生成，检查上面的日志）")
        return

    # 优先冒烟 onedir，其次是 onefile
    for _, target, _size in produced:
        executable = target if target.is_file() else target / f"{APP_NAME}.exe"
        print(f"\n冒烟一遍 {executable.relative_to(ROOT)}：")
        smoke(executable)
        break


def smoke(executable: Path) -> int:
    """跑 --version 和 --help，确认产物不是个起不来的壳。"""
    if not executable.exists():
        print(f"找不到 {executable}", file=sys.stderr)
        return 1
    for flag in ("--version", "--help"):
        completed = subprocess.run([str(executable), flag], capture_output=True)
        # 子进程按系统本地编码写管道（简中即 GB18030），不能假定 utf-8
        text = auto_type.decode_text(completed.stdout or completed.stderr).strip()
        first = text.splitlines()
        print(f"  {flag}: exit={completed.returncode}  {first[0] if first else '(无输出)'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="build.py", description="打包 auto_type 为 exe")
    parser.add_argument("--onefile", action="store_true", help="额外再出一个单文件便携版")
    parser.add_argument("--console", action="store_true", help="打带控制台的版本（排查闪退用）")
    parser.add_argument("--clean", action="store_true", help="先清掉中间产物 build/")
    args = parser.parse_args(argv)

    check_environment()

    if args.clean and BUILD.exists():
        # 只清中间产物。dist/ 交给 PyInstaller 的 --noconfirm 自己覆盖，
        # 免得这里一个批量递归删除被安全策略拦下来。
        shutil.rmtree(BUILD)
        print(f"已清理 {BUILD.relative_to(ROOT)}/")

    variants = ["onedir"] + (["onefile"] if args.onefile else [])
    for variant in variants:
        ok, message = build(variant, args.console)
        if not ok:
            print(message, file=sys.stderr)
            return 1

    report()
    return 0


if __name__ == "__main__":
    sys.exit(main())

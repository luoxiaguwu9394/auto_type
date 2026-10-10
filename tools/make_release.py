#!/usr/bin/env python3
"""把 dist/ 里已经打好的产物整理成可直接上传 GitHub Release 的分发包。

产出（全部落在仓库根目录的 release/ 下）：

    release/auto_type-<ver>-windows-x64.zip           onedir 形态，顶层包一个 auto_type/ 目录
    release/auto_type-<ver>-windows-x64-portable.exe  onefile 形态，语义化文件名
    release/SHA256SUMS.txt                            GNU coreutils 风格校验值，按文件名排序

设计约束：

- **只读 dist/**：不重新打包、不改动产物，只搬运与压缩。
- **排除运行时配置**：dist/auto_type/config.json 是本机试跑生成的个人参数，
  绝不能进发布包，否则用户解压出来就带着别人的节奏/倒计时。
- 用标准库 zipfile 精确控制 zip 内容与排除项（Compress-Archive 会带多余目录条目、不好排除）。
- 不生成发布说明——RELEASE_NOTES.md 由人工按 GLOSSARY.md 术语撰写，脚本只碰二进制产物。

用法：

    C:/Python314/python.exe tools/make_release.py
    C:/Python314/python.exe tools/make_release.py --version 1.0.0
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# 与 dist/ 的布局保持一致；这些是"上一阶段已经打好"的产物，脚本只读。
DIST_ONEDIR = REPO_ROOT / "dist" / "auto_type"
DIST_ONEFILE = REPO_ROOT / "dist" / "auto_type.exe"
RELEASE_DIR = REPO_ROOT / "release"

# 运行时生成的本机配置，落进发布包会污染用户环境，必须排除。
EXCLUDED_NAMES = frozenset({"config.json"})

# zip 解压后应当得到 auto_type/auto_type.exe 这样的一层目录包裹。
ZIP_INNER_DIR = "auto_type"

PLATFORM = "windows-x64"


def sha256_of(path: Path) -> str:
    """返回文件内容的 sha256 小写十六进制摘要。"""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_onedir_files() -> list[tuple[Path, str]]:
    """枚举 onedir 产物中应当进入发布包的文件。

    返回 (绝对路径, 相对 auto_type/ 的 posix 风格相对路径) 列表，
    已按相对路径排序，并剔除排除项（config.json）。
    """
    collected: list[tuple[Path, str]] = []
    for abs_path in sorted(p for p in DIST_ONEDIR.rglob("*") if p.is_file()):
        rel = abs_path.relative_to(DIST_ONEDIR)
        if rel.name in EXCLUDED_NAMES:
            continue
        collected.append((abs_path, rel.as_posix()))
    return collected


def build_zip(zip_path: Path) -> int:
    """生成 onedir 形态的 zip，返回写入的文件条目数。"""
    files = iter_onedir_files()
    with zipfile.ZipFile(
        zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as zf:
        for abs_path, rel in files:
            zf.write(abs_path, f"{ZIP_INNER_DIR}/{rel}")
    return len(files)


def write_sums(entries: list[tuple[str, Path]]) -> Path:
    """写 SHA256SUMS.txt：`<hash>  <name>`，按文件名升序。"""
    sums_path = RELEASE_DIR / "SHA256SUMS.txt"
    lines = []
    for name, path in sorted(entries, key=lambda item: item[0]):
        lines.append(f"{sha256_of(path)}  {name}")
    sums_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return sums_path


def main() -> int:
    """命令行入口：产出三个文件并打印校验信息。"""
    parser = argparse.ArgumentParser(description="整理 auto_type 的 GitHub Release 分发包")
    parser.add_argument("--version", default="1.0.0", help="版本号（默认 1.0.0）")
    args = parser.parse_args()

    if not DIST_ONEDIR.is_dir():
        raise SystemExit(f"找不到 onedir 产物目录：{DIST_ONEDIR}")
    if not DIST_ONEFILE.is_file():
        raise SystemExit(f"找不到 onefile 产物：{DIST_ONEFILE}")

    RELEASE_DIR.mkdir(parents=True, exist_ok=True)

    zip_name = f"auto_type-{args.version}-{PLATFORM}.zip"
    portable_name = f"auto_type-{args.version}-{PLATFORM}-portable.exe"
    zip_path = RELEASE_DIR / zip_name
    portable_path = RELEASE_DIR / portable_name

    # 1) onedir -> zip
    if zip_path.exists():
        zip_path.unlink()
    entry_count = build_zip(zip_path)

    # 2) onefile -> 语义化命名的副本
    shutil.copy2(DIST_ONEFILE, portable_path)

    # 3) 校验值（zip + portable）
    sums_path = write_sums([(zip_name, zip_path), (portable_name, portable_path)])

    print(f"onedir zip      : {zip_path.name}  ({entry_count} 个文件条目)")
    print(f"onefile portable: {portable_path.name}")
    print(f"checksums       : {sums_path.name}")
    print(sums_path.read_text(encoding="utf-8").rstrip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

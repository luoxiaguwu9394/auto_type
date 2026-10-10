"""比对"敲出来的文件"和"源语料"，给出逐字符结论。

这是判定对错的唯一标准——不是"两次看起来一不一样"，而是"输出等不等于语料"。

用法：
    python tests/check_output.py sample.txt C:\\Users\\xinxi\\Desktop\\test4.txt
    python tests/check_output.py sample.txt test4.txt --exact   # 连结尾换行也要一致

退出码：0 = 一致，1 = 不一致，2 = 用法/读文件错误
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import auto_type  # noqa: E402


def normalise(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def describe(char: str) -> str:
    return f"U+{ord(char):04X} {char!r}"


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2

    source_path, output_path = argv[1], argv[2]
    exact = "--exact" in argv[3:]

    try:
        source = normalise(auto_type.load_payload(source_path))
        output = normalise(auto_type.load_payload(output_path))
    except auto_type.PayloadError as exc:
        print(f"错误：{exc}")
        return 2

    if not exact:
        source, output = source.rstrip("\n"), output.rstrip("\n")

    print(f"源语料  {source_path}：{len(source)} 字符")
    print(f"输出    {output_path}：{len(output)} 字符")

    if source == output:
        print("\n一致：逐字符相同")
        return 0

    print("\n不一致")
    for index, (expected, actual) in enumerate(zip(source, output)):
        if expected != actual:
            start = max(0, index - 12)
            print(f"  首个不同位置 {index}（行 {source.count(chr(10), 0, index) + 1}）")
            print(f"    期望 {describe(expected)}")
            print(f"    实际 {describe(actual)}")
            print(f"    上下文 期望 …{source[start:index]}[{expected}]{source[index + 1:index + 13]}…")
            print(f"    上下文 实际 …{output[start:index]}[{actual}]{output[index + 1:index + 13]}…")
            break
    else:
        if len(source) > len(output):
            print(f"  输出短了 {len(source) - len(output)} 字符，缺：{describe(source[len(output)])} 起")
            print(f"    缺失内容：{source[len(output):][:60]!r}")
        else:
            print(f"  输出长了 {len(output) - len(source)} 字符，多：{describe(output[len(source)])} 起")
            print(f"    多余内容：{output[len(source):][:60]!r}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))

# auto_type

> 我开发这个工具，是为了解决一些只能手敲键盘输入的情况。

有些目标就是不吃粘贴：网页表单禁掉了 paste 事件，某些客户端只认真实的键盘事件，远程桌面和游戏里剪贴板根本不通用。碰到这种地方，你只能一个字一个字敲。这个工具替你敲。

## 它怎么工作

1. 选一个 txt 文件（语料）
2. **手动把光标点进你要输入的那个框**——程序不猜焦点在哪，你自己放
3. 触发开始，走一段倒计时，这段时间你用来切回目标窗口
4. 程序逐字符把语料敲进去，每个字符都是一次真实的按键事件

中途按 `Esc` 或点中止按钮立即停；焦点被切走会自动暂停，切回来自动继续。

## 安装与运行

**方式一：直接用打包好的 exe**（不需要装 Python）

从 [Releases](https://github.com/luoxiaguwu9394/auto_type/releases) 下载分发包：

| 下载 | 适合 | 启动 |
| --- | --- | --- |
| `auto_type-1.0.0-windows-x64.zip` | 解压后运行 `auto_type\auto_type.exe`，日常用 | 约 0.3 秒 |
| `auto_type-1.0.0-windows-x64-portable.exe` | 单个文件，不用解压，适合发给别人 | 约 3 秒 |

完整性校验值在同页的 `SHA256SUMS.txt`。

想自己构建（详见 [PACKAGING.md](./PACKAGING.md)）：

```bash
python build.py --onefile        # 出 onedir + onefile 两个产物到 dist/
python tools/make_release.py     # 再打成可分发到 Release 的包 → release/
```

> 打包必须用**带 tkinter 的 Python**（官方安装包装的都有），本机是 `C:\Python314\python.exe`。`build.py` 会先检查，缺了直接报错。
>
> exe 未签名，首次运行可能有 SmartScreen 提示（「更多信息 → 仍要运行」），部分杀软也可能误报。发布包已关掉 UPX 压缩来降低这个概率。

**方式二：源码运行**（零第三方依赖，Windows + Python 3.10+ 即可）

```bash
# 图形界面（主要用法）
python auto_type.py

# 命令行
python auto_type.py --file 语料.txt
```

## 命令行参数

| 参数 | 说明 | 默认 |
| --- | --- | --- |
| `--file PATH` | 语料文件路径 | — |
| `--delay-min` / `--delay-max` | 节奏区间（毫秒/字） | `30` / `80` |
| `--jitter` | 抖动幅度（0–1，越大越不匀速） | `0.3` |
| `--no-humanize` | 关闭拟人：匀速敲，无抖动、无回退、无行间停顿 | 关 |
| `--no-enter` | 换行不敲回车（转成空格） | 关 |
| `--humanize` | 开启拟人（与 `--no-humanize` 相反，用来覆盖记住的配置） | 记住的值 |
| `--encoding` | 手动指定编码，默认自动检测（UTF-8 → GB18030，兼容 GBK） | 自动 |
| `--countdown` | 倒计时秒数 | `3` |
| `--dry-run` | 干跑：只打印计划，不真发按键 | 关 |
| `--yes` | 语料超过 5 万字时不再确认 | 关 |
| `--gui` | 打开图形界面 | — |
| `--version` | 显示版本后退出 | — |

命令行与图形界面共用同一套敲字内核，参数一一对应。

> 打包后的 exe 是 windowed 形态，双击不会弹黑窗；从 cmd 里运行则会把输出接回当前控制台，提示和进度照常可见。

## 图形界面

- 选文件、编码下拉框
- 节奏档位（慢 / 中 / 快）+ 自定义区间 + 抖动滑块
- 拟人总开关（控制抖动、回退、行间停顿）
- 换行敲回车开关、干跑开关、回退概率滑块
- 开始 / 中止按钮、进度条、已敲字数
- 参数记住上次的选择，存在同目录 `config.json`

> 有两个例外，写进配置时会被改掉：**干跑**不进配置（否则下次开界面会莫名停在"不真敲"）；**倒计时**在配置里不落 0（一次 `--countdown 0` 不该永久砍掉留给你切到目标的那段时间，它会被记成 1 秒）。真想永久关掉倒计时，直接编辑 `config.json`——那是明确且只对本地生效的选择。

> 图形界面需要带 `tkinter` 的 Python（官方安装包默认带）。没有的话命令行照常可用。

## 自检与验证

单元测试不动键盘，测的是计划层和 Win32 调用的内容（`FakeUser32` 替身）：

```bash
python -m unittest discover -s tests
```

真敲验证用下面两个探针，**会短暂占用前台，跑完自动关窗**：

```bash
python tests/e2e_native_edit.py                # 原生 Win32 Edit 目标，最标准的一种
python tests/e2e_native_edit.py stress 语料.txt # 用真实语料按默认节奏压一遍
python tests/e2e_probe.py                      # tkinter Text 目标，三个用例
```

敲完拿这个比对自己有没有敲错（`0` = 一致）：

```bash
python tests/check_output.py sample.txt 输出文件.txt
```

> 注意：拿 tkinter 的 `Text` 当目标时，它自己会把代理对拼错（Tk 的问题，已验证 `𠮷` 会被它拼成 `U+10BB7`），所以**不要**用增补字符判定对错；以 `e2e_native_edit.py` 的结果为准。

## 已验证的环境

分级测试计划见 [test_plan.md](./test_plan.md)。目前的状态：

| 目标 | 状态 |
| --- | --- |
| 记事本 | ✅ 逐字符一致 |
| 浏览器里的普通目标 | ✅ keydown 跟上去＝真实按键事件 |
| **禁粘贴的网页目标** | ✅ 粘贴被拦，字照样敲进去了 |
| 第三方客户端 / 远程桌面（L4） | ✅ 实测通过，具体应用清单见 [test_plan.md](./test_plan.md) |

专项也都过了：**回退高压**（10% 概率下内容仍完全一致）、**焦点监护**（切走暂停、切回续上）、**Esc 中止**（立即停、已敲内容保留）。

单元测试 46 项全绿，覆盖回退屏障、原子发送、注入失败、编码检测、持久化例外、冻结路径、输出解码与降级。

尚未验证的低风险项：`--no-enter`（换行转空格）、GB18030 编码语料、超长语料提示。

## 打包产物

打包方式、取舍与踩坑记录见 [PACKAGING.md](./PACKAGING.md)。校验产物用：

```bash
python tests/verify_package.py                     # 验 dist/auto_type/（onedir）
python tests/verify_package.py dist/auto_type.exe  # 验 onefile 便携版
```

它会把产物复制到全新临时目录、把 PATH 里的 Python 屏蔽掉，再逐项检查：产物结构、`--version`、`--help`、`--dry-run`、`config.json` 落点、**exe 真敲进一个原生 Edit 目标**、图形界面能否起来。目前两个产物都是 7/7 通过。

| | onedir `dist\auto_type\` | onefile `dist\auto_type.exe` |
| --- | --- | --- |
| 体积 / 文件数 | 18.9 MB / 56 | 9.6 MB / 1 |
| 启动（中位数） | **277 ms** | 2958 ms |
| 适用 | 日常使用 | 发给别人一个文件 |

> onefile 每次启动都要把内容解压到 `%TEMP%`，多花大约 3 秒。因为开始前本来就有一段倒计时，这个代价可以接受，但日常用还是 onedir 更顺手。

## 设计决策

- 为什么不用粘贴或直接给控件设值：见 [ADR 0001](./docs/adr/0001-full-simulation-injection.md)
- 术语定义：见 [GLOSSARY.md](./GLOSSARY.md)

## 路线图（尚未实现）

以下均已决定要做，但尚未实现，代码中以 `# TODO(roadmap):` 标注插入位置（第 1、2 项改的是同一行逻辑，共用一处标注）：

1. 按屏幕坐标点击后再敲
2. UI Automation 控件定位
3. 全局热键常驻系统托盘
4. `{ENTER}` / `{TAB}` 特殊按键标记
5. 超长语料走剪贴板加速
6. 多文件队列批量
7. 每个文件独立配置

已完成：~~打包成独立 exe~~（见 [PACKAGING.md](./PACKAGING.md)）。

## 注意

- emoji 和生僻字（增补字符）是**同步屏障**：它们之后的回退只会发生在屏障之后，不会回头删到屏障前。因为这类字符占两个 UTF-16 码元，有些目标一个退格只删得掉半个，跨过去退会让后面的内容越删越乱。
- 敲字期间不要动鼠标键盘，动了焦点就会触发暂停。
- 中止后已敲进目标的内容**不会回滚**。
- 语料超过 5 万字会先提示预计耗时再开始。

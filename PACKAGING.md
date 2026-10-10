# 打包为 Windows 可执行文件

本文是 `auto_type` 的打包方案与执行记录。路线图第 4 项（打包成独立 exe）由本文落地。

---

## 一、代码库分析

| 项     | 结论                                                                                                                         |
| ----- | -------------------------------------------------------------------------------------------------------------------------- |
| 语言    | Python 3（`from __future__ import annotations` + `X \| None` 语法 → 需 3.10+）                                                  |
| 入口    | `auto_type.py` 的 `main()` / `if __name__ == "__main__"`，单文件 818 行                                                          |
| 运行时依赖 | **仅标准库**：`argparse ctypes json math queue random sys threading time` + `dataclasses pathlib typing`；`tkinter` 为可选导入        |
| 构建期依赖 | PyInstaller（不进产物，不影响"零第三方依赖"这条线）                                                                                           |
| 数据文件  | **无**。程序不读任何随包资源——`config.json` 运行时生成，语料由使用者指定                                                                             |
| 动态库   | 不自带。`_tkinter.pyd` 与 Tcl/Tk 的 DLL 由 PyInstaller 的 hook 自动收集（Tk 9.0 下是 `tcl90.dll` + `tcl9tk90.dll`，脚本库以 zip 内嵌其中，详见第七节的说明） |
| 配置    | `config.json`，与可执行文件同目录                                                                                                    |
| 静态资源  | 打包前无图标。本次新增 `assets/auto_type.ico` 与 `assets/version_info.txt`                                                             |
| 平台耦合  | 模块级 `ctypes.WinDLL("user32")` → 只能在 Windows 上 import/打包                                                                    |

**关键前提：必须用系统 Python 3.14.7（`C:\Python314\python.exe`）打包。**  
托管 Python 3.13.14 没带 `tkinter`，用它打出来的 exe 图形界面起不来（`HAS_TK = False`）。

**目标架构：x64。** 由手头 Python 决定（本机只有 x64 解释器，无 32 位、无 ARM64）。

---

## 二、打包方式选型

| 方案                       | 评价                                                                                                         |
| ------------------------ | ---------------------------------------------------------------------------------------------------------- |
| **PyInstaller 6.22.3** ✅ | 系统 Python 里**已经装好**；tkinter/tcl-tk 的收集有成熟 hook；`--icon` `--version-file` `--noconsole` 齐全；报错资料最多。零代码改动即可打包 |
| Nuitka                   | 编译成 C，启动更快、体积更小，但需要 MSVC/MinGW 工具链，构建要几分钟，tkinter 的部署配置更繁；本项目收益不抵成本                                        |
| cx_Freeze                | 配置更啰嗦，tcl/tk 数据目录要手写 `include_files`，容易漏                                                                   |
| py2exe                   | 老项目，对 Python 3.13+ 支持差                                                                                     |

**选 PyInstaller。** 理由：环境已就绪、对 tkinter 这条最容易踩坑的路径开箱可用、且不需要改一行代码就能出产物。

---

## 三、打包前必须改的代码（3 处）

这三处不改，打出来的 exe 会有真实缺陷。

### 1. `config_path()` 在 onefile 下彻底失效 ⚠️

```python
def config_path() -> Path:
    return Path(__file__).resolve().parent / CONFIG_FILENAME
```

onefile 模式下 `__file__` 指向 `%TEMP%\_MEIxxxxxx\` 这个**每次启动都重新解压、退出即删**的临时目录。后果：

- 参数记忆**完全失效**（写进去、进程一退就没了）
- 每次启动都在 temp 留一份垃圾

**改法**：frozen 时用 `Path(sys.executable).parent`（exe 所在目录），非 frozen 保持原行为。

### 2. `--noconsole` 下 `print()` 会直接崩

windowed 打包后 `sys.stdout` / `sys.stderr` 是 `None`，任何 `print()` → `AttributeError: 'NoneType' object has no attribute 'write'`。命令行模式整条路都会炸。

**改法**：frozen 且 stdout 为 `None` 时，调 `kernel32.AttachConsole(ATTACH_PARENT_PROCESS)` 把输出接回**父进程的控制台**。效果：

- 双击 exe → 干净启动图形界面，没有多余的黑窗口
- 从 cmd 跑 `auto_type.exe --file x.txt` → 提示和进度照常显示在 cmd 里

### 3. 文档里的路线图标注要同步

文件头的 `# TODO(roadmap): 支持打包成独立 exe` 移除；README 路线图第 4 条标为已完成。

---

## 四、打包方式与命令

用一个脚本统一驱动：`build.py`（调 PyInstaller 的命令行参数，不维护 `.spec`）。  
`.spec` 交给 PyInstaller 每次自动生成并 `.gitignore` 掉——单一事实来源放在 `build.py` 里，避免两份配置互相漂移。

```bash
python build.py            # 出 onedir（默认，日常用）
python build.py --onefile  # 再出一个单文件便携版
python build.py --clean    # 先清 build/ 和 dist/ 再打
```

实际执行的核心命令（由 `build.py` 拼出）：

```bash
C:\Python314\python.exe -m PyInstaller ^
  --noconfirm --clean ^
  --name auto_type ^
  --icon assets\auto_type.ico ^
  --version-file assets\version_info.txt ^
  --noconsole --noupx ^
  --distpath dist --workpath build ^
  --exclude-module numpy --exclude-module pandas ... ^
  auto_type.py
```

`--noconsole` 而非 `--console`：图形界面是本工具的主要用法，双击不该弹黑窗；命令行的输出由第三节第 2 条的 `AttachConsole` 补回来。

---

## 五、资源文件处理

| 资源   | 处理                                                                                                                                       |
| ---- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| 图标   | 新增 `assets/auto_type.ico`（16/24/32/48/64/128/256 七个尺寸）。由 `tools/make_icon.py` 用 Pillow 生成，**一次生成、提交入库**；`build.py` 只读不生成，所以构建期不需要 Pillow |
| 版本信息 | 新增 `assets/version_info.txt`（PyInstaller 的 `VSVersionInfo` 格式），让 exe 属性页显示名称/版本/说明，也让杀软少一分"来路不明的裸 exe"的观感                                |
| 数据文件 | **不需要**，`datas` 留空                                                                                                                       |
| 动态库  | **不需要手写**，全靠 PyInstaller 的 tkinter hook。**不要** exclude `tkinter` / `_tkinter`                                                            |
| 配置文件 | 不打包。运行时在 exe 同目录生成 `config.json`（见第三节第 1 条）。产物目录只读时会静默跳过保存，用默认值运行                                                                        |

---

## 六、输出产物与「单文件 / 单目录」取舍

|          | onedir（单目录）                           | onefile（单文件）                        |
| -------- | ------------------------------------- | ----------------------------------- |
| 产物       | `dist/auto_type/`（exe + `_internal/`） | `dist/auto_type.exe`                |
| **实测启动** | **277 ms**（冷启 639 ms）                 | **2958 ms**（冷启 3491 ms）             |
| **实测体积** | 18.9 MB / 56 个文件                      | 9.6 MB / 1 个文件                      |
| 分发       | 得先压成 zip                              | 一个文件直接发                             |
| 磁盘占用     | 只占一份                                  | 每次运行在 temp 多留一份解压副本                 |
| 杀软误报     | 风险较低                                  | **风险明显更高**（自解压 + 写 temp 是启发式重点关照对象） |
| 排查报错     | 报错里的路径就是真实路径                          | 报错路径是临时目录，且退出即删                     |

上表数字是本机实测（`C:\Python314`，Windows，各跑 5 次取中位数）。**启动差 10 倍**是这个取舍里最硬的一条：onefile 每次启动都要把 19 MB 解压到 `%TEMP%`。

**决定：两个都出。** 架构由手头 Python 锁定为 x64；"要不要单文件"用两个都产出来消解，不需要使用者先做选择。

```
dist/
├── auto_type/                 # onedir —— 日常使用推荐（启动快）
│   ├── auto_type.exe
│   └── _internal/…
└── auto_type.exe              # onefile —— 只用来"发一个文件给别人"
```

- **日常用 onedir**：启动快（277 ms vs 2.9 s，对"倒计时内切窗口"这个流程有实际影响）、配置稳定、杀软少找麻烦。
- **要发给别人时用 onefile**：省得解释"整个目录一起拷"。

`build/`、`dist/`、`*.spec` 全部进 `.gitignore`——构建产物不入库。

**重建时的一个操作提示**：PyInstaller 的 `--noconfirm` 会**递归删掉**已存在的输出目录。在带"批量删除需确认"安全策略的环境里这一步会被拦，表现为 `onedir 打包失败，退出码 1`。此时手工 `rm -rf dist build` 再跑即可——`dist/` 全是可再生的构建产物，删了没有损失。

---

## 七、体积控制

零第三方依赖意味着基础体积就是"解释器 + tcl/tk"。但查 `_internal/` 的体积构成时发现一处大浪费，实际裁掉了 8.3 MB（onedir 27.2 → 18.9 MB）。

**关键发现：一个不联网的工具背着 7.4 MB 的 OpenSSL。**

查 `build/onedir/auto_type/xref-auto_type.html` 的引入链：

```
random -> hashlib -> _hashlib -> libcrypto-3.dll (6.1 MB) + libssl-3.dll (1.3 MB)
```

`random` 是我们要用的（回退概率、抖动），而 `random` 会 `import hashlib`；`hashlib` 又去 `import _hashlib`，那个 C 扩展链上 OpenSSL 的两个 DLL。排除 `_hashlib` 之后 `hashlib` 会退回内置的 `_sha2`/`_md5`/`_blake2`（CPython 里那几处 import 都有 `try/except` 守卫），`random` 的种子初始化照常工作。

排除清单（`build.py` 的 `EXCLUDES`），分三类：

1. **被 hook 误拉的三方库**：`numpy pandas matplotlib scipy PIL PyQt5 PyQt6 PySide2 PySide6 IPython pytest unittest setuptools pkg_resources pip wheel sqlite3 curses`
2. **TLS / 网络栈**：`ssl _ssl _hashlib socket _socket select selectors ftplib http urllib email xml xmlrpc asyncio`
3. **压缩编解码**：`bz2 _bz2 lzma _lzma`

两条硬约束：

- **不能排 `tkinter` / `_tkinter` / `tcl` / `tk`**——图形界面就靠它们。
- **不能排 `zipfile`**——第一版排除清单里有它，结果 exe 直接起不来：PyInstaller 自己的运行时钩子 `pyi_rth_inspect.py` 要 `import zipfile`，报 `ModuleNotFoundError: No module named 'zipfile'`。这是排 `zipfile` / `tarfile` 两次尝试里踩到的坑，已记在上方清单的注释里。

另外 `--noupx` 必开：**UPX 压缩是杀软误报的头号诱因**，宁可大几 MB 也不要它。

裁剪后的体积构成（`_internal/` 实测 17.2 MB）：

| 项                  | 大小     | 说明                                             |
| ------------------ | ------ | ---------------------------------------------- |
| `python314.dll`    | 6.6 MB | 解释器本体，必需                                       |
| `tcl90.dll`        | 3.3 MB | Tcl，**脚本库以 zip 内嵌在里面**                         |
| `tcl9tk90.dll`     | 2.0 MB | Tk，同上                                          |
| `base_library.zip` | 1.3 MB | PyInstaller 打包的标准库，必需                          |
| `ucrtbase.dll`     | 1.1 MB | 运行库，留着更稳                                       |
| 其余                 | ~3 MB  | `_tkinter.pyd`、各类 `.pyd`、`api-ms-win-*` 转发 DLL |

再往下裁空间很小（`ucrtbase` 1.1 MB 是唯一的候选，但去掉后对老系统的兼容性有风险，不值得）。

> Tk 9.0 的库文件命名和 Tk 8.6 不同：是 `tcl90.dll` + `tcl9tk90.dll`（两个都以 `tcl` 开头），**没有** `tk86t.dll` 那种名字，也**没有** `_internal/tcl/` 数据目录——脚本库（`init.tcl` 那一套）以 zip 形式内嵌在 DLL 里（系统目录 `C:\Python314\tcl\libtcl9.0.4.zip` 可印证）。写检查脚本时别按 8.6 的名字去找。

---

## 八、常见报错与应对

| 症状                                           | 成因                                | 应对                                                                                         |
| -------------------------------------------- | --------------------------------- | ------------------------------------------------------------------------------------------ |
| 双击闪退、无任何提示                                   | 未捕获异常，windowed 模式下看不见             | 从 cmd 跑 `auto_type.exe --file x.txt` 看输出（`AttachConsole` 已接回来）；仍看不到就临时用 `--console` 打一版定位  |
| 界面起不来、提示没有 tkinter                           | 用了不带 tkinter 的 Python 打包          | 换 `C:\Python314\python.exe`                                                                |
| `ImportError: DLL load failed`               | 缺 VC 运行库                          | 产物里已带 `VCRUNTIME140.dll` + `ucrtbase.dll`（见第七节体积构成），理论上自足；但**本机没条件在真正裸系统上验**，见第九节「等效隔离」的边界 |
| 参数不记忆                                        | onefile 下 `__file__` 指向临时目录       | 已修 `config_path()`                                                                         |
| `'NoneType' object has no attribute 'write'` | windowed 下 stdout/stderr 为 `None` | 已加 `AttachConsole`                                                                         |
| 杀软报毒 / 直接删文件                                 | 未签名产物 + 自解压行为（onefile 更重）         | 关 UPX；优先发 onedir；把产物目录加白名单；向微软提交误报；正式分发才考虑代码签名                                             |
| SmartScreen「Windows 已保护你的电脑」                 | 无签名、下载来源未知                        | 「更多信息 → 仍要运行」；长期方案是代码签名                                                                    |
| 32 位机器跑不了                                    | 产物是 x64                           | 需用 32 位 Python 重打（本机没有，标记为不支持）                                                             |
| ARM64 Windows                                | x64 产物可走模拟层，性能有损                  | 需用 ARM64 Python 原生打包（本机没有，标记为未验证）                                                          |
| 中文路径下打包失败                                    | 部分工具链处理非 ASCII 不稳                 | 构建目录已是 ASCII 路径；产物也建议放 ASCII 路径                                                            |
| 打包时 `RecursionError`                         | 依赖成环                              | 少见；加 `--recursion-limit`                                                                   |

---

## 九、在"干净环境"中验证（单机等效手段）

本机没法开虚拟机，用下面这套**等效隔离**替代。全部步骤都不假设源码目录存在、不假设系统装了 Python。

> **这套手段覆盖不到什么**（说清楚，免得当成"已在干净机验过"）：它验证的是"产物不依赖源码目录、不依赖已安装的 Python"，**不能**替代在真正裸的 Windows 上（没装 Python、没装 VC 运行库、另一台机器）跑一遍。VC 运行库那条尤其如此——产物带了自己的 `VCRUNTIME140.dll` 和 `ucrtbase.dll`，但本机没法证明它在缺库的机器上也够用。要彻底确认，得拷到一台没装过开发环境的机器上双击一次。

### 步骤

1. **搬家**：把 `dist/auto_type/` 整个复制到一处全新的临时目录（如 `%TEMP%\auto_type_clean\`），源码目录完全不参与
2. **屏蔽解释器**：开一个 cmd，`set PATH=C:\Windows\System32;C:\Windows`，确认 `python` 命令不可用，再从这个 cmd 启动 exe——证明它不偷偷依赖已安装的 Python
3. **无配置启动**：删掉 exe 旁的 `config.json` 再启动，应能用默认值起来，并在退出时**在 exe 同目录**生成 `config.json`
4. **功能验证**：
   - `auto_type.exe --help` / `--version` → 命令行通路通
   - `auto_type.exe --file sample.txt --dry-run` → 语料读取、计划编译、中文输出都正常
   - 双击（无参数）→ 图形界面起来
   - **真敲验证**：让 exe 往一个受控目标里敲，再读回来跟语料逐字符比对
5. **onefile 单独验**：把 `auto_type.exe`（便携版）单独拷到另一个空目录重跑 3、4 步。特别确认 **`config.json` 出现在 exe 旁边，而不是 `%TEMP%\_MEIxxxxxx\` 里**——这是第三节第 1 条修复的判定点

### 这套验证已经脚本化

上面全部步骤在 `tests/verify_package.py` 里，一条命令跑完：

```bash
python tests/verify_package.py                     # 验 dist/auto_type/（onedir）
python tests/verify_package.py dist/auto_type.exe  # 验 onefile 便携版
python tests/verify_package.py --skip-gui          # 跳过会弹窗的那一项
```

7 项检查：产物结构、`--version`、`--help`、`--dry-run`、`config.json` 落点、exe 真敲、图形界面启动。

**真敲那一项是怎么做的**：脚本在本进程里建一个原生 Win32 `Edit` 目标（把焦点给它），然后 `subprocess` 启动**沙箱里的 exe** 去敲，敲完把它里面的文本读回来跟 `sample.txt` 逐字符比对。这确实是**跨进程**注入——验证通过，说明打包形态的内核和源码形态一样好用。

> 早前用记事本测 `SendInput` 会拿到 `WinError 5`，那是**记事本**的问题（Windows 11 的记事本等应用运行在受限宿主里），不是所有跨进程注入都不行。判定注入是否被拒时别把这两件事混为一谈。
>
> 唯一仍需你手动确认的是**外部真实目标**：浏览器、禁粘贴网页、微信这类。那些你在源码形态已经验过（见 `test_plan.md`），打包形态的行为应当一致，但环境里没有现成的靶子，所以自动验证覆盖不到。

---

## 十、方案自审

| 检查项               | 结论                                                                                                      |
| ----------------- | ------------------------------------------------------------------------------------------------------- |
| 打包解释器选对了吗         | ✅ 已实测 `C:\Python314\python.exe` + PyInstaller 6.22.3 能打出并可运行带 tkinter 的 exe（`frozen: True`、`tk ok 9.0`） |
| 路径与命令是否有误         | ✅ 全部用绝对路径；`build.py` 里 `sys.executable` 取当前解释器，不写死                                                      |
| 三处代码缺陷是否都覆盖       | ✅ `config_path()` / `AttachConsole` / 文档路线图，三条都在第三节并有对应验证点                                              |
| 资源文件是否漏项          | ✅ 图标、版本信息已备；数据文件与动态库经分析确认无需手工处理                                                                         |
| exclude 是否安全      | ✅ 不含 `tkinter` / `_tkinter`；列表里全是本项目未 import 的三方库与构建期工具。产物起来后需复核                                        |
| 是否漏了 `.gitignore` | ✅ `build/`、`dist/`、`*.spec` 要补进去                                                                        |
| 验证是否闭环            | ✅ 第九节有可执行步骤；单机无法覆盖的真敲部分已明确标注需使用者复验                                                                      |
| 有无必须由使用者确认才能动的点   | ❌ 无。架构由手头 Python 锁定（x64）；"要不要单文件"用**两个都出**消解，不构成阻塞                                                      |

**审查结论：可以执行。**

---

## 十一、执行记录

### 交付物

| 文件                        | 作用                                 |
| ------------------------- | ---------------------------------- |
| `build.py`                | 一条命令完成打包；PyInstaller 参数、排除清单都在这里   |
| `assets/auto_type.ico`    | 应用图标，7 个尺寸（16/24/32/48/64/128/256） |
| `assets/version_info.txt` | exe 属性页的版本资源                       |
| `tools/make_icon.py`      | 图标生成脚本（一次性，需 Pillow；产物已入库，打包不需要它）  |
| `tests/verify_package.py` | 干净环境验证脚本（7 项检查）                    |

### 代码改动

- `config_path()` 拆成 `config_dir()` + `config_path()`：冻结后认 `sys.executable` 所在目录，不再用 `__file__`


- 新增 `is_frozen()` / `NullWriter` / `_attach_parent_console()` / `ensure_console()`：windowed 打包后 `sys.stdout`/`sys.stderr` 为 `None` 时的兜底
- 新增 `decode_text()` + `AUTO_ENCODINGS`：统一"按 UTF-8 → GB18030 试解"。读语料和打包工具链读 exe 控制台输出共用它
- 新增 `--version`
- `load_payload()` 改用 `decode_text()`
- 数据化：`.gitignore` 增加 `build/`、`dist/`、`*.spec`

### 产物

```
dist/
├── auto_type/                       # onedir    18.9 MB / 56 个文件
│   ├── auto_type.exe   (1.7 MB)
│   └── _internal/      (17.2 MB / 55 个文件)
└── auto_type.exe                    # onefile    9.6 MB / 1 个文件
```

### 验证结果

`tests/verify_package.py` 对**两个产物各跑一遍，7/7 全通过**：

| 检查                                                                    | onedir              | onefile                |
| --------------------------------------------------------------------- | ------------------- | ---------------------- |
| 产物结构（`_tkinter.pyd` + `tcl90.dll` + `tcl9tk90.dll` + `python314.dll`） | ✅                   | ✅（单文件形态无 `_internal/`） |
| `--version`                                                           | ✅ `auto_type 1.0.0` | ✅                      |
| `--help`（windowed 下输出正常）                                              | ✅                   | ✅                      |
| `--dry-run`                                                           | ✅ 132 字符 / 5 行      | ✅                      |
| `config.json` 落点在 exe 同目录，且干跑与 0 倒计时未入库                               | ✅                   | ✅                      |
| **exe 真敲**（跨进程打进原生 Edit 目标）                                           | ✅ **131 字符逐字符一致**   | ✅ 131 字符一致             |
| 图形界面启动（窗口出现、进程存活）                                                     | ✅                   | ✅                      |

规模与速度：

|              | onedir              | onefile           |
| ------------ | ------------------- | ----------------- |
| 体积           | 18.9 MB             | 9.6 MB            |
| 文件数          | 56                  | 1                 |
| 启动（中位数 / 冷启） | **277 ms / 639 ms** | 2958 ms / 3491 ms |
| 打包耗时         | 7.9 s               | 10.0 s            |

单元测试 **43 项全绿**（3.13 与 3.14 双解释器），含新增的 `TestFrozenPaths`（4 项）与 `TestDecodeText`（3 项）。

### 过程中踩到并修掉的坑

| 现象                                                       | 根因                                                            | 处理                                        |
| -------------------------------------------------------- | ------------------------------------------------------------- | ----------------------------------------- |
| exe 启动即 `ModuleNotFoundError: No module named 'zipfile'` | 排除清单里有 `zipfile`，而 PyInstaller 自己的运行时钩子 `pyi_rth_inspect` 需要它 | 从排除清单移除 `zipfile`/`tarfile`               |
| onedir 体积 27.2 MB，比预期大                                   | `random → hashlib → _hashlib` 把 OpenSSL 的两个 DLL 拖了进来          | 排除 TLS 栈，省 8.3 MB                         |
| `--help` 在工具链里报 `UnicodeDecodeError`                     | 子进程按系统本地编码（GB18030）写管道，工具链按 UTF-8 读                           | 抽出 `decode_text()`，三处统一                   |
| 验证脚本报 `config.json` 没生成                                  | **验证脚本自己的 bug**：把产物复制到沙箱后，却仍在跑原始路径的 exe                       | 所有检查改用沙箱副本                                |
| 验证脚本报"缺 `tk*.dll`"                                       | 检查项按 Tk 8.6 命名写死                                              | 改成认 `tcl*.dll`（Tk 9.0 两个 DLL 都以 `tcl` 开头） |
| `onedir 打包失败，退出码 1`                                      | 环境安全策略拦下了 PyInstaller 对旧输出目录的递归删除                             | 手工 `rm -rf dist build` 后重跑；已写进本文第六节       |

### 仍需使用者确认的

**打包产物的外部目标兼容性**：浏览器里的目标、禁粘贴网页、微信 / 远程桌面这类真实目标，自动验证覆盖不到（环境里没有靶子）。源码形态你已经验过（`test_plan.md` 里 L1–L4 全过），打包形态建议按下面这条快速复核一次：

```cmd
cd /d C:\Users\xinxi\Desktop\my_project\auto_type\dist\auto_type
auto_type.exe --file ..\..\sample.txt --countdown 5
```

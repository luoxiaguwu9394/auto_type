# 测试计划

按目标应用的"宽容程度"分级往上攻。每一级只解决一个问题，别跳级——在记事本上失败和在网页上失败是完全不同的两回事，跳级会让你分不清是内核错还是目标不吃。

## 唯一判定标准

**输出逐字符等于语料。** 不是"两次看起来一不一样"——回退是随机的，笔画数和退格数每次必然不同（实测同一份语料两次跑是 140 笔/4 次退格 和 150 笔/9 次退格），这是设计如此。

每次敲完用这个比：

```cmd
cd /d C:\Users\xinxi\Desktop\my_project\auto_type
C:\Python314\python.exe tests\check_output.py sample.txt C:\Users\xinxi\Desktop\test4.txt
```

它会告诉你字符数、一致与否，不一致时给出首个不同位置、行号和上下文。退出码 0 = 一致。

## 环境准备

| 事项 | 说明 |
| --- | --- |
| GUI | 必须用 `C:\Python314\python.exe`（托管 Python 没带 tkinter） |
| 命令行 | 两个 Python 都行 |
| 参数记忆 | `config.json` 会记住上次参数，带过 `--delay` 之后，不带参数的运行也会沿用。想回默认就显式写 `--delay-min 30 --delay-max 80` |
| 输出文件 | 每次换一个新编号（`test4.txt`、`test5.txt`…），方便回溯比对 |
| ⚠️ 别用 `--countdown 0` | 倒计时是留给你把焦点切到目标的。设成 0 会**立刻开敲**，字会敲到当前窗口（命令行自己）身上 |

## 通用开场

```cmd
cd /d C:\Users\xinxi\Desktop\my_project\auto_type
type nul > C:\Users\xinxi\Desktop\test4.txt
start notepad C:\Users\xinxi\Desktop\test4.txt
```

`start notepad` 之后**手动点进窗口把光标放好**，再跑下一条；`--countdown 5` 是留给你切窗口的。

---

## L0 · 干跑

**目标**：确认计划和预计耗时，一个按键都不发。

```cmd
C:\Python314\python.exe auto_type.py --file sample.txt --dry-run
```

**通过**：打印计划，头一行是"干跑：下面只是计划，一个按键都不会真的发出去"，目标里没有任何字。

---

## L1 · 记事本（最宽容）

**目标**：验内核本身——中文、换行、emoji、增补字符、回退。

```cmd
C:\Python314\python.exe auto_type.py --file sample.txt --countdown 5
C:\Python314\python.exe tests\check_output.py sample.txt C:\Users\xinxi\Desktop\test4.txt
```

**通过**：`一致：逐字符相同`（132 字符）。

**状态**：✅ 已通过（`test3.txt`，132/132）。

---

## L2 · 浏览器普通输入框

**目标**：验 JS 事件有没有被真实触发（keydown / input / 字数统计走没走）。

```cmd
start "" "C:\Users\xinxi\Desktop\my_project\auto_type\tests\fixtures\no-paste.html"
```

点进左边的**「对照：普通输入框」**，然后：

```cmd
C:\Python314\python.exe auto_type.py --file sample.txt --countdown 5
```

**通过**：字数 = 132，**keydown 计数跟上去**（这证明是真按键事件，不是给控件塞值——塞值不产生 keydown）。

---

## L3 · 禁粘贴的网页输入框（核心场景）

**目标**：这工具存在的理由——粘贴失效的地方能不能敲进去。

同一个页面，点进右边的**「禁粘贴：单行输入框」**或**「禁粘贴：多行文本框」**：

1. 先按 `Ctrl+V` 试一下，确认**什么都粘不进来**、"拦截"计数 +1
2. 再跑：

```cmd
C:\Python314\python.exe auto_type.py --file sample.txt --countdown 5
```

**通过**：字数 = 132，keydown 跟上去，拦截计数没有额外增加（说明它不是靠粘贴进去的）。

把页面里的内容全选复制出来存成文件，用 `check_output.py` 比对。

> 那个测试页屏蔽了 `paste` / `copy` / `cut` / `drop` / 右键菜单 / `Ctrl+V` / `Ctrl+C` / `Ctrl+X` / `Ctrl+A` / `Shift+Insert` / `Ctrl+Insert`。只禁 `paste` 事件的页面强度不够，测不出真东西。

---

## L4 · 其他应用（兼容性边界）

命令同 L1，只换目标：微信输入框、QQ、远程桌面、游戏、各类客户端。**这级是赚到，不通过不算失败**，记下哪个应用不吃、什么症状即可。

---

## 专项测试

### 回退高压（修复就改在这里，必须压）

回退概率只能在图形界面调，走 GUI：

```cmd
C:\Python314\python.exe auto_type.py
```

「回退概率」滑块拉到 **10%**，敲 `sample.txt`。

**通过**：仍完全一致，且肉眼能看到偶尔退一格再打回来。

### 换行转空格

```cmd
C:\Python314\python.exe auto_type.py --file sample.txt --countdown 5 --no-enter
```

**通过**：四行变一行，换行处是空格。

### GB18030 编码（编码回退路径还没真验过）

```cmd
C:\Python314\python.exe -c "open('gb.txt','w',encoding='gb18030').write('中文GB18030编码测试'+chr(10)+'第二行 abc 123')"
C:\Python314\python.exe auto_type.py --file gb.txt --countdown 5
```

**通过**：中文正常，不是乱码。

### 焦点监护

```cmd
C:\Python314\python.exe auto_type.py --file sample.txt --countdown 5 --delay-min 200 --delay-max 400
```

敲到一半点一下别的窗口，停 3 秒，再点回来。

**通过**：显示"已暂停：焦点离开了目标窗口"，回来自动继续，最终内容完整。

### Esc 中止

同上命令，敲到一半按 **Esc**。

**通过**：立刻停，已敲进去的内容保留不回滚。

### 超长语料提示

```cmd
C:\Python314\python.exe -c "open('big.txt','w',encoding='utf-8').write(('中文测试 abc 123'+chr(10))*4000)"
C:\Python314\python.exe auto_type.py --file big.txt --dry-run
```

**通过**（干跑这步）：显示约 52000 字符、预计耗时几十分钟。

要验真正的拦截，**先删掉 `--yes` 跑一次**，应该被拦下并提示加 `--yes`：

```cmd
C:\Python314\python.exe auto_type.py --file big.txt --countdown 10
```

别真去敲 5 万字——那要 40 多分钟，且期间你不能碰电脑。

> ⚠️ 倍数别写小了：`3500` 行只有 45500 字符（Windows 会写成 CRLF，也就 49000），**触发不了 5 万阈值**。用 `4000`。

---

## 出问题怎么归因

| 症状 | 原因 | 怎么办 |
| --- | --- | --- |
| 错在 emoji / 生僻字附近，形态是"打成邻居字、多字、少字" | 回退跨越了增补字符 | 已修（同步屏障）。还有就发我 |
| 不在 emoji 附近的单字丢失（`!`、`@`、`#` 这类） | 目标端丢按键事件 | 先放慢到 `--delay-min 200 --delay-max 400` 再试；放慢后正常＝速度问题 |
| 中文变乱码或问号 | 编码 | GUI 编码下拉框指定，或 `--encoding gb18030` |
| 一个字都没进去 | 光标没放对 / 倒计时没切过去 | 确认倒计时结束时焦点在目标里 |
| 报"权限不足 / 拒绝访问" | 目标是**以管理员身份运行**的 | 两边跑在同一权限级别 |
| 敲到一半停了，提示焦点离开 | 焦点监护生效（正常） | 点回目标窗口 |

---

## 已完成的验证

| 项目 | 结果 |
| --- | --- |
| L1 记事本（`test3.txt` vs `sample.txt`） | ✅ 132/132 逐字符一致 |
| 原生 Win32 Edit 控件真敲（含 31/34 次退格 + emoji/𠮷 混排） | ✅ 3/3 一致 |
| 真实语料 × 300 随机种子 | ✅ 不一致 0 次 |
| 单元测试 | ✅ 33 项全绿（3.13 与 3.14 双解释器） |

## 自动化工具

| 命令 | 用途 |
| --- | --- |
| `python -m unittest discover -s tests` | 单元测试，不碰键盘 |
| `python tests\check_output.py <源> <输出>` | 比对敲出来的文件和源语料 |
| `python tests\e2e_native_edit.py` | 原生 Edit 控件真敲 3 个用例（占屏约 15 秒） |
| `python tests\e2e_native_edit.py stress sample.txt` | 用真实语料按默认节奏压一遍 |
| `python tests\e2e_probe.py` | tkinter Text 控件 3 个用例 |

> tkinter 的 `Text` 控件自己会把代理对拼错（Tk 的 bug，`𠮷` 会被它拼成 `U+10BB7`），拿它当目标时**不要**用增补字符判定对错。

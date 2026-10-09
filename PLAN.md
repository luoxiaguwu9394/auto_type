# 实施计划：auto_type 第一版

来源：三轮 grill-with-docs 达成的共识（`README.md` + `GLOSSARY.md` + `docs/adr/0001`）。
本文档是实施路线，不是需求；需求已定，这里只拆"怎么做"。

## 范围（第一版）

敲字内核 + tkinter GUI + CLI + 干跑。路线图里的 8 项**不做**，在代码里标 `# TODO(roadmap):`。

## 关键 seam：语料 → 笔画序列

整个设计围绕一条缝：

```
load_payload(path, encoding) -> str          # 编码检测
build_plan(text, config, rng) -> [Stroke]    # 纯函数，不碰 Windows API
execute(strokes, ...)                        # 真发按键
```

`build_plan` 是纯函数，随机源由外部注入，因此**可确定性测试**；干跑只是"打印这个序列而不执行"。所有拟人逻辑（节奏、抖动、回退、行间停顿）都发生在这里，不发生在执行器里。

## 文件清单

| 文件 | 职责 |
| --- | --- |
| `auto_type.py` | 单文件主体：Win32 封装、Config、load_payload、build_plan、execute、CLI、GUI |
| `tests/test_auto_type.py` | unittest 标准库，覆盖 build_plan 与编码检测等纯逻辑 |
| `.gitignore` | 追加 `config.json`、`__pycache__/` |

## 任务分解（按依赖顺序）

1. **Win32 层**：`INPUT`/`KEYBDINPUT` 结构体（Union 保证 64 位下 stride=40）、`SendInput`、Unicode 按键（`KEYEVENTF_UNICODE` + UTF-16 码元逐个发）、虚拟键（Enter/Backspace）、`GetForegroundWindow`（焦点监护）、`GetAsyncKeyState`（Esc 中止）
2. **Config**：dataclass + `to_dict/from_dict`，持久化到 `config.json`
3. **load_payload**：BOM 优先 → UTF-8 → GB18030 回退，失败给明确报错
4. **build_plan**：纯函数，产出 `[Stroke]`
5. **execute**：倒计时 → 记录起始前台窗口 → 逐笔画发送，每笔画的等待切成 10ms 切片以便轮询 Esc 与焦点
6. **CLI**：argparse，参数见 README（`--file --delay-min --delay-max --jitter --no-humanize --no-enter --encoding --countdown --dry-run --yes --gui`）
7. **GUI**：tkinter，选文件 / 编码 / 节奏档位+区间 / 抖动 / 拟人 / 回退概率 / 倒计时 / 干跑；开始停止、进度条、状态；敲字跑在工作线程，通过 queue 回传 UI
8. **测试**：`tests/test_auto_type.py`
9. **自查**：`py_compile` + 跑测试 + 全局一致性审查
10. **提交**：commit 到当前分支

## 实现要点

- **代理对**：emoji 等增补字符拆成两个 UTF-16 码元分别发，否则目标收到乱码
- **回退**：只在当前行、只对已敲出的字符退格 1–3 个再重打；`\r\n` 先归一化成 `\n`
- **焦点监护的取值时机**：倒计时结束后、发第一笔之前才记录前台窗口——此时使用者已经切到目标了（若在开始时就记，记到的是 GUI 自己）
- **暂停不等于中止**：焦点离开 → 暂停等待（每 100ms 轮询）；焦点回来 → 自动继续
- **中止不回滚**：已敲进目标的内容保留
- **超长语料**：> 50000 字提示预计耗时，GUI 弹确认，CLI 需 `--yes`（README 参数表补一行）
- **线程安全**：tkinter 只能在主线程碰，工作线程一律走 queue + `after`

## 测试计划（unittest，固定随机种子）

- UTF-16 码元拆分：BMP 字符 1 个、emoji 2 个
- 换行：`send_enter=True` 产 enter 笔画；`False` 产空格笔画
- 回退：概率设 1.0 时序列中出现 backspace 且后续重打相同字符；`humanize=False` 时一个 backspace 都没有
- 节奏：关掉抖动时等待落在 `[delay_min, delay_max]`；拟人开启时 enter 前的等待 ≥ 行间停顿下限
- 编码检测：UTF-8 与 GB18030 临时文件都能正确读出
- Config 往返：to_dict → JSON → from_dict 一致
- 干跑：不调用 `SendInput`（用 monkeypatch 断言零调用），输出含预计耗时

## 验收标准

- `python auto_type.py` 弹出 GUI
- `python auto_type.py --file x.txt --dry-run` 打印计划且**不发送任何按键**
- 真实敲字：光标放在记事本 → 倒计时 → 文字逐字出现，中文正确
- `python -m unittest discover -s tests` 全绿
- 零第三方依赖（只用标准库 + ctypes）

## 不在本次范围

坐标点击定位、UIA 定位、托盘热键、打包 exe、`{ENTER}`/`{TAB}` 标记、剪贴板加速、多文件队列、单文件独立配置 —— 全部标 `# TODO(roadmap)`。

# mattpocock/skills 安装清单

- **来源**：https://github.com/mattpocock/skills
- **安装位置**：`C:\Users\xinxi\.workbuddy\skills\`（用户级，所有项目可用）
- **上游副本**：`C:\Users\xinxi\Desktop\my_project\auto_type\mattpocock-skills\`（完整仓库，可用于 `git pull` 更新）
- **安装数量**：27 个（engineering 20 + productivity 7），已跳过 misc / in-progress / deprecated
- **安装时间**：2026-10-09

## 安全审计结论：P2（可安全使用）

| 检查项 | 结果 |
|---|---|
| 网络外传（curl/wget 上传、base64 解码执行、/dev/tcp） | 无 |
| 破坏性命令（rm -rf、git push --force、--no-verify） | 无 |
| 凭据窃取（ssh key、~/.aws、env 读取外发） | 无 |
| 提示词注入（忽略前序指令、绕过安全、隐瞒用户） | 无 |
| 附带脚本 | 仅 2 个 `*.sh` 模板，非自动执行 |
| frontmatter 完整性 | 27/27 均含 name + description |

**唯一需知悉项（信息级）**：`wizard` 技能会生成 bash 脚本，把人工输入的密钥写入 `.env` 并调用 `gh secret set` 写到 GitHub Secrets。这是它的设计目的，且要求人工逐步确认后才执行，不会自动运行。

## 已安装技能

### engineering（20）

| 技能 | 用途 |
|---|---|
| `ask-matt` | 路由：不确定用哪个技能时问它 |
| `code-review` | 双轨审查：规范轴 + 规格轴，并行子代理 |
| `codebase-design` | 深模块设计的共享词汇与方法 |
| `diagnosing-bugs` | 硬 bug / 性能回归的排障闭环（最小化→假设→插桩→修复） |
| `domain-modeling` | 建立并打磨领域模型，维护 GLOSSARY.md 与 ADR |
| `grill-with-docs` | 反复追问方案，同时产出 ADR 与术语表 |
| `implement` | 按 spec 或工单实现 |
| `implement-spec` | 在一条集成分支上并发实现整个 spec |
| `improve-codebase-architecture` | 扫描代码库找"加深模块"机会，出 HTML 报告 |
| `pr` | 生成易评审的 PR 描述 |
| `prototype` | 一次性原型，回答状态机/逻辑/UI 的设计问题 |
| `research` | 对一手来源做调研，产出带引用的 Markdown |
| `retro` | 会话结束后复盘 agent 环境，按严重度排序 |
| `setup-matt-pocock-skills` | **每个仓库首次使用前跑一次**：配置 issue tracker、triage 标签、领域文档布局 |
| `tdd` | 红-绿-重构循环 |
| `to-spec` | 把当前对话合成成 spec 并发布到 issue tracker |
| `to-tickets` | 把计划/spec 拆成带阻塞依赖的工单 |
| `triage` | 用角色状态机处理 issue 与外部 PR |
| `wayfinder` | 超大规模工作的决策工单地图，逐个解决 |
| `wizard` | 生成交互式 bash 向导，引导人工完成只能人工做的步骤 |

### productivity（7）

| 技能 | 用途 |
|---|---|
| `grill-me` | 非代码场景的反复追问，直到设计树每个分支都有结论 |
| `grilling` | 上面那个的可复用内核，grill-me / triage / wayfinder 都依赖它 |
| `handoff` | 压缩当前对话成交接文档给另一个 agent |
| `teach` | 多会话教学，把当前目录当状态化教学空间 |
| `to-questionnaire` | 把答不了的决策变成给关键人的问卷 |
| `wait-what` | 上一句话没听懂时，用你的术语表重新讲一遍 |
| `writing-for-agents` | 给 agent 写文档（技能、AGENTS.md/CLAUDE.md） |

## 使用注意

1. 这套技能原为 Claude Code / Codex 编写，正文中的 `/xxx` 是斜杠命令、子代理派发是宿主机制。在 WorkBuddy 里正文内容可正常加载，但依赖宿主机制的少数技能（`wizard` 生成 bash 向导、`setup-matt-pocock-skills` 探测 issue tracker）效果会打折。
2. 建议首次使用时先执行 `setup-matt-pocock-skills`，它会问你用哪个 issue tracker、triage 用什么标签、文档存哪里。
3. `ask-matt` 是入口路由器，拿不准用哪个技能时先问它。

## 更新与卸载

```bash
# 更新：拉上游后重跑复制
cd C:/Users/xinxi/Desktop/my_project/auto_type/mattpocock-skills && git pull

# 卸载：删除对应用户级目录即可，例如
rm -rf "C:/Users/xinxi/.workbuddy/skills/tdd"
```

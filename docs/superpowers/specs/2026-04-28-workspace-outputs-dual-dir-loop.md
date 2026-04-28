# workspace/outputs 双目录设计触发 agent 死循环

- **状态**:🟡 已定位,未修复
- **日期**:2026-04-28
- **影响**:任意"先生成产物 → 用户要求修改"的场景(HTML/MD/任何文档)。第二轮修改大概率触发反复重试直至撞 recursion 或 token 上限。

## 现象

用户测试两个会话:

1. **会话 1**(HTML 编码):`http://localhost:2026/workspace/chats/f1ead09a-a789-49b6-a0de-c2d55a028dd6`
   - 第一轮:模型生成完整 HTML 表单,可点开预览 ✓
   - 用户要求"补全字段" → 模型反复 `write_file`,每次都自我反馈"上次截断了"再写,直到崩溃
   - 隐藏思考里的链接点击后 Artifact 面板空白

2. **会话 2**(MD 修改,排除上下文截断假设):`http://localhost:2026/workspace/chats/0c04d857-ad09-44ab-8a76-40adbd85615f`
   - 第一轮:生成 MD 文件,链接可点开 ✓
   - 用户要求"删除某章节" → 模型表面顺利完成,但前端 Artifact 面板空白
   - 第一轮的链接仍能点开,看到的是"修改后"的内容(后来证实是个误读,见下)

3. **会话 3**(主动复现):`http://localhost:2026/workspace/chats/a4bfda7e-c2f2-44e7-9535-dbc2d03d1490`
   - 第一轮:模型 `write_file` 到 `/mnt/user-data/workspace/xiaohongshu_rental.html`
   - 模型在思考里告诉用户"在 `/mnt/user-data/outputs/xiaohongshu_rental.html` 预览"
   - **前端给出的可点击链接 URL 实际指向 `workspace/`,不是 `outputs/`**——口头说一套,链接是另一套
   - 用户要求"主题色改蓝" → 模型连续 4 次 `str_replace` `/mnt/user-data/outputs/xiaohongshu_rental.html`,但**那条路径下根本没文件**
   - 进入死循环

## 根因

[backend/packages/harness/deerflow/agents/lead_agent/prompt.py:441-452](../../../backend/packages/harness/deerflow/agents/lead_agent/prompt.py#L441-L452) 教给模型一套**双目录工作流**:

```
- User workspace: /mnt/user-data/workspace - Working directory for temporary files
- Output files:   /mnt/user-data/outputs   - Final deliverables must be saved here
- All temporary work happens in /mnt/user-data/workspace
- Treat /mnt/user-data/workspace as your default current working directory for coding and file-editing tasks
- Final deliverables must be copied to /mnt/user-data/outputs and presented using `present_files` tool
```

子 agent 的 prompt 也复制了同一套规则:
- [backend/packages/harness/deerflow/subagents/builtins/general_purpose.py:38-42](../../../backend/packages/harness/deerflow/subagents/builtins/general_purpose.py#L38-L42)
- [backend/packages/harness/deerflow/subagents/builtins/bash_agent.py:38-42](../../../backend/packages/harness/deerflow/subagents/builtins/bash_agent.py#L38-L42)

部分 skill 也是这种风格(image-generation、podcast-generation):workspace 写脚本/中间产物 → 命令行工具产出最终文件到 outputs。

### 为什么这个设计在第二轮崩

| 步骤 | 模型实际行为 | 文件系统状态 |
|---|---|---|
| 第一轮 | `write_file` workspace/x.html | workspace/x.html ✓,outputs/x.html 不存在 |
| 复制步骤 | **经常被模型偷懒跳过**(prompt 没强约束) | outputs 仍为空 |
| `present_files` | 模型按 prompt 调用,虚拟出"产物在 outputs"的认知 | — |
| 用户要求修改 | 模型坚信"产物在 outputs",对 `outputs/x.html` 做 `str_replace` | outputs 那份不存在 → 工具失败 |
| 死循环 | 模型换 `old_str`/`new_str`/`description` 重试,**path 一直错** | 持续失败直到撞 recursion_limit=1000 或 token 上限 |

**关键脆弱点:**
1. 双源 + 复制步骤 = 心智负担。LLM 不能稳定执行多步同步流程。
2. 模型嘴上说的路径 vs. 工具实际写入的路径 vs. 前端渲染的链接路径,**三方可能不一致**。
3. `str_replace` 对不存在文件的失败,对模型不是致命错误,只是"再试一次"信号——没有外力打断,死循环停不下来。
4. `LoopDetectionMiddleware` 存在(`spec_loop_detection_orphan_tool_msg.md` 里修过它),但**没拦住"同 path 不同 args 的反复 str_replace"**——可能它只检测"完全相同 tool_call"。

## 排除掉的非根因

### React Query 5min 缓存(本次修过,但不是主因)

调查初期怀疑前端 `useArtifactContent` 用 `staleTime: 5 * 60 * 1000` 缓存导致"修改后看到旧内容"。已修复:在 `useThreadStream.onLangChainEvent` 里识别 `write_file`/`str_replace` 工具结束时,调 `queryClient.invalidateQueries({ queryKey: ["artifact", path], exact: false })`。

实现:
- [frontend/src/core/artifacts/invalidation.ts](../../../frontend/src/core/artifacts/invalidation.ts) — 纯函数 `extractWriteFilePath(name, data)`,失败时返回 null
- [frontend/tests/unit/core/artifacts/invalidation.test.ts](../../../frontend/tests/unit/core/artifacts/invalidation.test.ts) — 7 单元测试
- [frontend/src/core/threads/hooks.ts](../../../frontend/src/core/threads/hooks.ts) — wiring

这个修复仍然有价值(防止"覆盖现有 outputs 文件"的场景被缓存挡住),但**修不好本次现象**——因为本次现象是 outputs 那份文件**根本没被写入**,缓存里也没有内容可挡。

### Skill 路径硬编码(独立隐患,本次无关)

调查中发现 [skills/types.py:40-50](../../../backend/packages/harness/deerflow/skills/types.py#L40-L50) 把 `/mnt/skills/public/...` 硬编码进 system prompt,且 `_load_enabled_skills_sync()` 不传 tenant 上下文 [lead_agent/prompt.py:22-23](../../../backend/packages/harness/deerflow/agents/lead_agent/prompt.py#L22-L23)。

但 `/mnt/skills/` 是 skill 文件本身,跟用户产物 `/mnt/user-data/outputs/` 不在一条路径上,**本次 bug 与之无关**。该问题用户已点出修复路径:"public skill 只读,自定义 skill 才允许编辑",作为独立 P2 处理。

## 修复方向(待用户决定)

### 方案 Z(轻量,主因修复)— 简化心智模型

让"产物"只有一个位置 = `/mnt/user-data/outputs/`。改 prompt:

- [prompt.py:449](../../../backend/packages/harness/deerflow/agents/lead_agent/prompt.py#L449):"default current working directory" → 限定为"用于中间脚本/临时数据"
- [prompt.py:452](../../../backend/packages/harness/deerflow/agents/lead_agent/prompt.py#L452):"must be copied to outputs" → 改成"final deliverables write directly to outputs with `write_file`"
- 同步改 [general_purpose.py](../../../backend/packages/harness/deerflow/subagents/builtins/general_purpose.py) 和 [bash_agent.py](../../../backend/packages/harness/deerflow/subagents/builtins/bash_agent.py)
- skill 里 image-generation / podcast-generation 那种"中间产物 + 命令行产出"的双目录用法保留(它们用工具同步,不靠模型自觉),**只改通用对话场景的指令**

### 方案 1(防御网)— 修 LoopDetection

调查 `LoopDetectionMiddleware` 实现,看为什么没拦住"同 path、变 args 的反复 str_replace"。可能需要把检测维度从"完全相同 tool_call"放宽到"同 tool name + 同 path"。

### 方案 3(可选,辅助)— 改 str_replace 失败提示

工具失败时,在 error message 里附上 `workspace/` 和 `outputs/` 的实际文件列表,帮模型自我纠错。

### 推荐组合

**方案 1 + 方案 Z 同步做。**1 是防御网(防 LLM 不遵守指令的边缘情况),Z 是主因修复(消除"双源同步"心智负担)。两条腿走路。

## 用户已表达的偏好

- 倾向方案 Z 的方向(简化产物路径)
- 同时提了"模型会一致运行到崩溃才结束"——确认了防御网的紧迫性,因此 1+Z 组合方案被推到必做
- 公共 skill 只读、自定义可写 = 修复 skill 路径硬编码的方向(独立 P2,不在本 spec 范围)

## 用户的四个验证问题(2026-04-28)

### Q1:upstream 是否针对 prompt 做了修改?

**没有结构性修改。**

- 最近相关 commit `563383c6 fix(agent): file-io path guidance in agent prompts (#2019)`(2026-04-09)只是措辞润色,保留双目录设计
- `git diff cc-main upstream/main -- prompt.py` 输出 **0 行差异**——cc-main 与 upstream 同步,bug 是 upstream 设计自带
- 这反而成为修复价值:**upstream 没意识到/没修,我们修等于对开源项目的实质贡献**,可考虑 PR 回去

### Q2:跟不使用 standard mode 有无关系?

**完全无关。** prompt.py 是 LangGraph agent runtime 的核心,standard 和 gateway 两种模式共用同一份 prompt/工具/中间件——死循环两种模式下都发生。gateway mode 修过的 event loop closed bug 在异步执行层,跟 prompt 设计正交。

### Q3:LoopDetection 是否被关了?之前你修过它

**没关,但当前设计有意"漏报"本次模式**——你之前的修复(0d749119)修的是 hard stop **触发后**的善后(orphan ToolMessage),不是触发条件。

LoopDetection 当前两层:
- Layer 1(hash-based):同一组 tool_calls hash ≥ 5 次 hard stop。但 [loop_detection_middleware.py:89-95](../../../backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py#L89-L95) 对 `write_file`/`str_replace` **用完整 args 哈希(含 content/old_str/new_str)而非 path**,这是有意设计——"模型迭代同一文件,每次内容不同"是合法行为,避免误杀。代价就是模型每次微调 args 哈希就不同,**Layer 1 永远不命中本次 case**。
- Layer 2(per-tool-type frequency):同 tool name 累计 ≥ 50 次 hard stop。本次会话 4 次就停了,**远低于阈值**。

不能简单改 hash 策略(会误伤合法迭代),需要加**新的窄检测维度**:同 path 连续失败 N 次(以 `Error:` 开头的返回值)。这是个**新签名**,跟现有 Layer 1/2 正交,不会误伤合法 case。

### Q4:1+2+3 可能都需要

精确化:

| | 是否必须 | 形态 |
|---|---|---|
| 1. prompt 简化(产物直写 outputs) | ✅ 主因 | 改 3 个文件的几行文案,纯 ceremony 简化 |
| 2. standard mode 切换 | ❌ 不需要 | — |
| 3. LoopDetection 补漏 | ✅ 防御网 | **新加**"同 path 连续失败 N 次"窄检测,**不动**现有 hash 策略 |

**推荐执行顺序**:先 1(改 prompt + 跑回归),再 3(加新窄检测 + 单元测试),分两个 commit 便于回滚。

## 暂存的 React Query 缓存修复

本会话已落地 + 测试通过 + lint 通过,**暂未 commit**(因为本次主因不在前端,这个修复属于"二阶 bug 顺手修")。等用户决定主因方案后,可以一起或单独 commit。

涉及文件:
- 新增 [frontend/src/core/artifacts/invalidation.ts](../../../frontend/src/core/artifacts/invalidation.ts)
- 新增 [frontend/tests/unit/core/artifacts/invalidation.test.ts](../../../frontend/tests/unit/core/artifacts/invalidation.test.ts)
- 修改 [frontend/src/core/threads/hooks.ts](../../../frontend/src/core/threads/hooks.ts)(import + onLangChainEvent 内调 invalidateQueries)

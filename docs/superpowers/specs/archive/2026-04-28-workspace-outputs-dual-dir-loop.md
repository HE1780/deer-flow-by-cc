> 📦 **归档于 2026-04-29 — 已 ship**：3 个根因（onLangChainEvent 死代码、`str_replace` URL 伪 scheme、MiniMax max_tokens 不足）全部修复（commits `b62d35bc` + `d67e0e13` + 用户改 `config.yaml`）。教训"假死循环先排查 max_tokens"已写入 [docs/lessons.md](../../../lessons.md)。

---

# workspace/outputs 双目录设计触发 agent 死循环

- **状态**:✅ 全部闭环(2026-04-28 晚,用户 smoke 通过)
  - 分支 1 (frontend cache invalidation):✅ 已合入 cc-main —— 但 onLangChainEvent 是死代码,**实际不工作**(见文末"晚间追查")
  - 分支 2 (prompt simplification — direct write to outputs):✅ 已合入 cc-main —— **死循环消除,模型不再崩溃**
  - 分支 3 (LoopDetection path-failure narrow detector):✅ 已合入 cc-main(7 新测试 + 50 老测试全绿)
  - 分支 4 (messages-watcher invalidation,替换分支 1 的死代码):✅ 已合入 cc-main(commit `d67e0e13`,14 新测)
  - 分支 5 (str_replace 切纯路径 URL,触发 HTTP fetch):✅ 已合入 cc-main + 用户 smoke 通过(commit `b62d35bc`)
  - 配套观察 (LLM `max_tokens` 偏小):✅ 用户已自行调整 `config.yaml`(MiniMax → 184096),HTML 生成截断问题消除

### 用户手工 smoke 反馈(2026-04-28)

- 第一次生成 MD:点链接 → artifact 面板正确显示 ✓
- **第一次编辑**:点链接 → artifact 面板**正确显示更新内容** ✓ (分支 1 的 invalidate 在首次编辑时生效)
- **第二次编辑**:artifact 面板**无变化**,**刷新页面后才更新** ❌

**残留 bug 假设**:
1. (a) `useArtifactContent` 在第一次编辑后某个 re-render 路径上 unmount 了,第二次 invalidate 时无 active observer → 只 mark stale,不触发 refetch,要等下次 mount(刷新)
2. (b) React Query 的 staleTime/dedupe 把第二次 invalidate 当作"已经在更新中"忽略
3. (c) 第二次 path 的 query key 形态跟第一次不严格匹配(`exact: false` 没救到),导致 invalidate 没命中正确 cache

**待办**:用户继续 HTML 测试,在 Network 面板观察第二次编辑时是否有 artifact 请求被发出。Network 静默 → (a)/(c);Network 有请求但 UI 不变 → 渲染层问题。
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

---

## 2026-04-28 (晚间) 主线追查:第二次编辑空白的真正根因

### 时间线

1. **第一波修复(已合入 cc-main)**:把 `onLangChainEvent` 内的 invalidate 写在 `extractWriteFilePath` 上,假设事件流会触发 invalidate。✅ 单元测试通过。
2. **MCP smoke 验证**:在浏览器跑一遍 write_file → str_replace,**`__capturedWarns` 数组空**——`onLangChainEvent` 回调**根本没 fire**。
3. **根因 #1(已修)**:[frontend/src/core/threads/hooks.ts:205-214](../../../frontend/src/core/threads/hooks.ts#L205-L214) 的 `useStream` 配置**没有传 `streamMode`**。LangGraph SDK 默认的 streamMode 不包括 `"events"`,所以 `on_tool_end` LangChain 事件根本不会被推到客户端。整个 `onLangChainEvent` 分支属于死代码——把它换成"watch `thread.messages`,看到新的 ToolMessage 就 invalidate"才是稳的实现。
   - **修复 commit**: `d67e0e13` `fix(frontend): invalidate artifact cache via thread.messages, not events`
   - 新增 `extractInvalidatedPathsFromNewMessages` + `extractToolEndEventsFromNewMessages`(共 14 个新单测);把 `useThreadStream` 改成 `useEffect` 监听 `thread.messages` 长度增长。
   - **同时修复了 agents/new 页面的 `onToolEnd` 死回调**(它也依赖同一个事件流)——现在通过 messages-watcher 派发合成事件。
4. **第二波 MCP smoke**:重跑 write_file → str_replace,**仍然空白**。但这次 `count: 0` 的不是 warn 数组,是 `/artifacts/` fetch 数组——也就是说 invalidate 调了,但**根本没人 refetch**。
5. **根因 #2(刚修,未验证)**:看了 [frontend/src/components/workspace/messages/message-group.tsx:327-360](../../../frontend/src/components/workspace/messages/message-group.tsx#L327-L360) 和 [frontend/src/core/artifacts/loader.ts:26-47](../../../frontend/src/core/artifacts/loader.ts#L26-L47):
   - 模型每次 `write_file` / `str_replace` 时,前端把 artifact viewer 的 URL 设成 `write-file:<path>?message_id=...&tool_call_id=...`(伪 URL scheme)。
   - `useArtifactContent` 见到 `write-file:` 前缀就走 `loadArtifactContentFromToolCall`——直接读 AIMessage 的 `tool_call.args.content`,**不发 HTTP**。
   - 对 `write_file` 这是合理的:`args` 里有完整 `content`,流式过程中文件还没落盘也能展示。
   - 对 `str_replace` 这是**致命的**:`args = {path, old_str, new_str}`,**没有 `content` 字段**。函数返回 `undefined` → 面板渲染空。
   - **修复 commit**: `b62d35bc` `fix(frontend): str_replace artifact viewer fetches from disk, not tool args`
   - 改动只在 [message-group.tsx:327-372](../../../frontend/src/components/workspace/messages/message-group.tsx#L327-L372):`write_file` 仍走 `write-file:` URL,`str_replace` 改用纯路径 → 触发 `useArtifactContent` 的 HTTP 分支 → 与新的 messages-watcher invalidate 串起来,正好闭环。
6. **未做的事**:**MCP smoke 还没回归 step 5 的修复**。merge 进 cc-main 但**没 push**。

### 当前主分支状态(截至本会话结束)

```
git branch: cc-main (ahead of origin/cc-main by 2 commits)
last 3 commits:
  - Merge feat/artifact-str-replace-uses-plain-path (str_replace viewer fetches from disk)
  - Merge feat/artifact-invalidation-via-messages (rewire artifact invalidation via thread.messages)
  - <pre-existing>
```

### 给下一个会话的交班

**目标**:验证 `b62d35bc` 是否真的解决"第二次编辑后 artifact 面板空白"。

**复现路径**(用 `deerflow-web-testing` skill):
1. 服务在 2026/3110/2024/8100,登录 `tsamilijohn206@gmail.com / ChangeMe!2026`
2. 让模型创建一个 md(走 `write_file`)→ 验证 artifact 面板能显示
3. 让模型用 `str_replace` 改这个 md → **关键验证点**:
   - 面板自动切到新的 viewer(URL 应该是纯路径,不是 `write-file:...`)
   - 面板内容应该是改后的版本
   - 网络面板里能看到一个 `GET /api/threads/<id>/artifacts/<path>` 请求

**如果验证失败,可能的下一层根因**:
- (a) `select(buildUrl())` 调用时,`path` 字段在 str_replace 的 `args` 里命名不一致(可能是 `target_file` 等),需要改适配。验证方式:在 hooks.ts 的 messages-watcher 里临时加 console.warn 打 `tm.name + JSON.stringify(args)`。
- (b) `useArtifactContent` 在 isMock=undefined 时 enabled 没传,query 不执行。看 hook 调用处。
- (c) 第一次 write_file 的 `write-file:` URL 在新 ToolMessage 到来后没被 select 替换——也就是 `autoOpen && autoSelect && !result` 这几个 guard 在第二次工具完成时不再成立(`isLast` 跟新消息身份匹配吗?)。这是最有可能的——auto-open 那一层逻辑在第二轮可能根本不重新触发 select。

**如果是 (c)**,修复方向应该是:在 messages-watcher 那边检测到新 ToolMessage 是 str_replace + 当前 selectedArtifact 是同 path 的 `write-file:` URL,主动把 selectedArtifact 切到纯路径(或者 invalidate `loadArtifactContentFromToolCall` 的源头——但那不是 react-query 管的)。

**已知的清晰事实**(不要再去验证):
- `onLangChainEvent` 不会 fire(deer-flow streamMode 不含 "events")——这是 D。
- write_file 用 `write-file:` URL 是**正确**的,不要改。
- str_replace 在 ToolMessage 内容是 "OK" / "Error: ..." 的简单字符串,新文件内容只在磁盘上。
- 后端那条路径 `/api/threads/<id>/artifacts/<path>` 已经能正确返回最新内容(本次磁盘验证过 `第二版内容 v2`)。

**还没做的小尾巴**:
- `git push origin cc-main` ——push 之前先做完上面的 smoke。
- 如果 (c) 是真的,记得把这一层根因 append 到本 spec,不要覆盖前面的诊断历史。

---

## 2026-04-28 闭环 + 排查清单

### 用户 smoke 结果

`b62d35bc` 落地后,用户复测:write_file → str_replace 整个流程,artifact 面板第二次编辑后**正确显示新内容**。本 spec 标记为 ✅ 闭环。

### 排查附录:LLM `max_tokens` 偏小导致 HTML 生成"假死循环"

本次会话排查过程中,用户额外指出**会话 1 (HTML 编码场景)** 反复 `write_file` 还有一个独立诱因:

- [config.yaml:16-27](../../../config.yaml#L16-L27) 中 `minimax-m2.7` 的 `max_tokens` 配得偏小,模型生成完整 HTML 时被服务端在中段截断。
- 截断后的 HTML 不是合法文档,模型自己读到"上次没写完",于是再写一次,再被截断——表现上像死循环,但**根因是输出长度上限**,不是 prompt 设计或 LoopDetection 失灵。
- **修复**:用户已把 `max_tokens` 调整到 184096(MiniMax 上限附近);HTML 生成不再截断,该路径的"假死循环"消除。
- **教训**:遇到"模型反复写同一个文件直到崩溃"先看两条线索——
  1. 工具调用的 `output` 是不是 `Error: ...`(prompt / 路径设计问题,LoopDetection Layer 3 处理)
  2. AIMessage 的 `content` / 上一次 tool args 是不是被截断在中间(`max_tokens` 不够,需要调 config.yaml,**不是 bug**)
- 这条记到 `docs/lessons.md` 比较合适,但不要在 LoopDetection Layer 3 里加 token-truncation 检测——那是模型容量问题,不是 agent 行为问题。

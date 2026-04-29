> 📦 **归档于 2026-04-29 — 正文完成；截图全缺；09 章部分内容已过时**
>
> **当前事实**：
> - **正文已写**：[docs/user-guide/](../../../user-guide/) 下 9 章 + README 全部完成（约 599 行）。
> - **截图全缺**：[docs/user-guide/images/](../../../user-guide/images/) 目录为空（仅 `.gitkeep`）。
> - **09 章过时**：原稿"已知限制"包含若干已 ship 项（`/admin/tenants/[id]` 真页面已上线、`/admin/users/[id]` 同；`/admin/workspaces/[id]/members` 已可用）— 详见 [OPEN_ISSUES.md OI-6](../../../OPEN_ISSUES.md)。
> - **01-06 章准确性待复核**：写于 admin nav 改造前；07-08 章已与当前 admin 路由一致。
>
> 下文为原始 plan，仅作历史档案保留。

---

# DeerFlow 用户使用手册 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `docs/user-guide/` 下产出 9 章 + README + 截图目录的中文最终用户手册，每章基于本地实操验证（happy path），未验证的部分诚实标注。

**Architecture:** 文档驱动 + 边写边实操验证。每章一个独立任务：先打开/触发功能→抓截图→写文字→commit。普通用户可实操的章节（01-06、09 部分）必须实际验证；`[组织管理员]`/`[平台管理员]` 章节如当前账号权限不足，标注「未实操」并写明依据来源。

**Tech Stack:** Markdown / 浏览器手动操作 / macOS 截图 (`screencapture`) / git。无代码改动。

**Spec:** [docs/superpowers/specs/2026-04-27-user-guide-design.md](../specs/2026-04-27-user-guide-design.md)

**Base commit:** `b3cfac65` (cc-main @ 2026-04-27)

---

## 全局约定

### 标签使用

文件顶部：
```markdown
> **适用角色：** [全员]
```
或
```markdown
> **适用角色：** [组织管理员]（[平台管理员] 可同时阅读）
```

小节内行内标签（用于混合章节，本计划中暂未出现，但为格式约定预留）：
```markdown
### 创建工作区 [组织管理员]
```

### 实操注记 admonition

未实操章节顶部统一格式：
```markdown
> ⚠️ **本章节未实操验证**
> 当前文档基于代码读取与 spec 整理，未由具备 platform_admin 权限的账号实操验证。如发现与实际行为不符，请以实际为准并提 issue。
```

### 截图规范

- 工具：macOS `screencapture` 或 Cmd+Shift+4 (区域截图)
- 路径：`docs/user-guide/images/{NN}-{kebab-desc}.png`，NN 与章节号对齐
- 引用：`![描述](images/01-login-page.png)`
- 尺寸：原始截图保留即可，不做压缩
- 隐私：截图中如出现真实邮箱 `tsamilijohn206@gmail.com`，**保留**（这是公开测试号，不是敏感信息）；如出现 token 明文，**必须打码**

### Commit 规范

每章一次 commit。message 格式：
```
docs(user-guide): write chapter NN — <topic>

Brief notes about what was verified vs not verified.
```

### 启动服务

每个需要实操的任务开头先确认服务在跑：
```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:2026/health
```
期望：`200`。如非 200，先 `make dev-daemon`，等 90-120 秒。

---

## 文件结构

```
docs/user-guide/
├── README.md                          # Task 2
├── 01-getting-started.md              # Task 3
├── 02-chat-and-threads.md             # Task 4
├── 03-skills.md                       # Task 5
├── 04-agents.md                       # Task 6
├── 05-files-and-export.md             # Task 7
├── 06-settings-and-memory.md          # Task 8
├── 07-org-admin.md                    # Task 9
├── 08-platform-admin.md               # Task 10
├── 09-faq-and-known-issues.md         # Task 11
└── images/                            # Task 1 创建
    ├── 01-*.png ... 09-*.png
```

---

## Task 1: 环境准备 + 创建目录骨架

**Files:**
- Create: `docs/user-guide/images/.gitkeep`

- [ ] **Step 1: 确认本地服务在跑**

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:2026/health
```
期望：`200`。如非 200，运行：
```bash
make dev-daemon
sleep 100
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:2026/health
```

- [ ] **Step 2: 在浏览器登录验证账号**

打开 `http://localhost:2026/login`，用 `tsamilijohn206@gmail.com` / `ChangeMe!2026` 登录。登录成功 = 跳转到 `/workspace/chats` 或类似页面。

- [ ] **Step 3: 探查当前账号实际权限**

登录后，在浏览器 console 运行：
```javascript
fetch('/api/me').then(r => r.json()).then(d => console.log(JSON.stringify(d, null, 2)))
```
记录返回的 `roles` / `tenant_id` / `permissions` 字段。**这一步决定哪些章节可以本地实操、哪些要标 ⚠️。**

记录结果到一个临时笔记（不进 commit），后续每个 admin 任务开头查阅。

- [ ] **Step 4: 创建目录与占位**

```bash
mkdir -p docs/user-guide/images
touch docs/user-guide/images/.gitkeep
```

- [ ] **Step 5: 验证目录创建**

```bash
ls -la docs/user-guide/
```
期望输出包含：`images/`

- [ ] **Step 6: Commit**

```bash
git add docs/user-guide/images/.gitkeep
git commit -m "docs(user-guide): scaffold user guide directory"
```

---

## Task 2: 写 README.md（索引页）

**Files:**
- Create: `docs/user-guide/README.md`

- [ ] **Step 1: 写 README.md**

Create `docs/user-guide/README.md`:

````markdown
# DeerFlow 用户使用手册

> 本手册面向已经登录到 DeerFlow 实例的最终用户与管理员。如需安装部署，请阅读项目根目录的 [Install.md](../../Install.md) 与 [README.md](../../README.md)。

**文档版本基线：** `cc-main @ b3cfac65`（2026-04-27）

---

## 这是什么

DeerFlow 是一个开源的 super agent harness：你可以把它想成一个能调度多个智能体（agent）、长记忆、文件沙箱与可扩展技能（skill）的 AI 工作台。本手册告诉你如何在 Web 界面里用 DeerFlow 完成日常工作。

## 角色与标签

文档每章开头会标注「适用角色」。三类角色与权限：

| 角色 | 标签 | 你能做什么 |
|---|---|---|
| 普通用户 | `[全员]` | 在自己工作区聊天、调用 skill、上传文件、改个人设置 |
| 组织管理员 | `[组织管理员]` | 在以上之上，管理本组织内用户、工作区、API token、审计日志、Org Keys |
| 平台管理员 | `[平台管理员]` | 在以上之上，管理多个租户、审核全平台 skill、跨租户审计 |

**继承关系：** 平台管理员 ⊃ 组织管理员 ⊃ 普通用户。如果你是管理员，普通用户章节里讲的功能你也能用。

## 推荐阅读路径

**普通用户**

1. [01 入门：登录与界面总览](01-getting-started.md)
2. [02 对话与会话管理](02-chat-and-threads.md)
3. [03 技能 (Skills)](03-skills.md)
4. [04 子智能体 (Sub-Agents)](04-agents.md)
5. [05 文件与导出](05-files-and-export.md)
6. [06 设置与记忆](06-settings-and-memory.md)
7. [09 常见问题与已知限制](09-faq-and-known-issues.md)

**组织管理员**：以上章节 + [07 组织管理员手册](07-org-admin.md)

**平台管理员**：以上章节 + [08 平台管理员手册](08-platform-admin.md)

## 反馈

发现文档与实际行为不一致？欢迎在仓库提 issue 或直接发 PR。本手册的设计稿见 [docs/superpowers/specs/2026-04-27-user-guide-design.md](../superpowers/specs/2026-04-27-user-guide-design.md)。
````

- [ ] **Step 2: 验证 markdown 渲染**

```bash
ls -la docs/user-guide/README.md
wc -l docs/user-guide/README.md
```
期望：文件存在，行数约 50-60。

- [ ] **Step 3: Commit**

```bash
git add docs/user-guide/README.md
git commit -m "docs(user-guide): write index README"
```

---

## Task 3: 01-getting-started.md（登录、界面总览）

**Files:**
- Create: `docs/user-guide/01-getting-started.md`
- Create: `docs/user-guide/images/01-login-page.png`
- Create: `docs/user-guide/images/01-workspace-home.png`

- [ ] **Step 1: 实操 — 退出再登录抓截图**

1. 浏览器打开 `http://localhost:2026/login`（如已登录，先点退出）
2. 截图整个登录页（含密码登录区与 OIDC 入口区）
3. 保存为 `docs/user-guide/images/01-login-page.png`
4. 用 `tsamilijohn206@gmail.com` / `ChangeMe!2026` 登录
5. 登录后停在默认页（应是 `/workspace/chats`），截图整个界面
6. 保存为 `docs/user-guide/images/01-workspace-home.png`

macOS 截图命令示例（区域截图后另存）：
```bash
# Cmd+Shift+4 选区域，截图自动放桌面，然后：
mv ~/Desktop/Screenshot*.png docs/user-guide/images/01-login-page.png
```

- [ ] **Step 2: 观察并记录界面元素**

在「登录后首页」截图上数清楚：
- 左侧栏（thread 列表 / agent / skills / settings）的具体顺序
- 顶部是否有 workspace 切换器
- 右上角是否有用户头像 / 退出菜单
- 中间空状态显示了什么文案

记下来用到 Step 3 的写作。

- [ ] **Step 3: 写 01-getting-started.md**

Create `docs/user-guide/01-getting-started.md`:

````markdown
# 01 入门：登录与界面总览

> **适用角色：** [全员]

本章覆盖第一次进入 DeerFlow 的全部基础操作：登录、找到主要功能入口、退出。

## 登录

在浏览器打开 DeerFlow 实例地址（默认 `http://localhost:2026/login`，自托管者可能改了端口）。你会看到登录页：

![登录页](images/01-login-page.png)

DeerFlow 支持两种登录方式：

1. **邮箱 + 密码** — 在表单填邮箱与密码，点登录
2. **单点登录（OIDC）** — 如果你的部署接入了 Keycloak、Okta、Azure AD 等 IdP，会显示对应按钮，点击跳转到 IdP 完成认证

> ⚠️ OIDC 流程在 DeerFlow 端代码已实现，但截至本文档基线版本未在真实 IdP 上做过端到端验证。如果你是首次配置 IdP 并遇到回调问题，建议先用邮箱+密码确认账号本身可用，再排查 IdP 配置。详见 [09 常见问题](09-faq-and-known-issues.md)。

## 登录后的界面总览

登录成功后默认跳转到 `/workspace/chats`：

![登录后首页](images/01-workspace-home.png)

主要分区：

- **左侧栏**：从上往下依次是
  - `Chats` 当前与历史对话列表
  - `Skills` 技能库（你的技能 + 平台技能）
  - `Agents` 子智能体画廊
  - 底部齿轮 = 设置入口
- **主区**：根据当前路径变化。`/workspace/chats` 是会话列表与新建入口
- **右上**：用户头像 / 当前账号信息 / 退出菜单

## 退出登录

点右上角头像 → 退出登录（或导航到 `/logout`）。退出会清除本机 session cookie，下次访问需要重新登录。

## 下一步

- 想发出第一条对话 → [02 对话与会话管理](02-chat-and-threads.md)
- 想直接装载某个技能开干 → [03 技能 (Skills)](03-skills.md)
````

- [ ] **Step 4: 自查文字与截图一致**

打开本地 `01-getting-started.md`，确保：
- 文字描述的左侧栏顺序与你截图里看到的一致
- OIDC 段如截图显示了 OIDC 按钮则保留，未显示则改写为「如果你的部署启用了 OIDC」
- workspace 切换器：当前账号如只属于一个 workspace 不会出现，那就不写

如有不符，改写文字以匹配实际截图。

- [ ] **Step 5: Commit**

```bash
git add docs/user-guide/01-getting-started.md docs/user-guide/images/01-login-page.png docs/user-guide/images/01-workspace-home.png
git commit -m "docs(user-guide): write chapter 01 — getting started

Verified: login flow with tsamilijohn206@gmail.com works.
Verified: workspace home layout (left nav + main).
Not verified: OIDC against real IdP — flagged in chapter."
```

---

## Task 4: 02-chat-and-threads.md（聊天与会话管理）

**Files:**
- Create: `docs/user-guide/02-chat-and-threads.md`
- Create: `docs/user-guide/images/02-new-thread.png`
- Create: `docs/user-guide/images/02-streaming.png`
- Create: `docs/user-guide/images/02-thread-context-menu.png`

- [ ] **Step 1: 实操 — 创建第一个 thread**

1. 在 `/workspace/chats` 找新建按钮（可能是 "+" 或 "New Chat"），截图当前空状态 → 保存为 `02-new-thread.png`
2. 输入一条简单消息如 `请用 50 字介绍 DeerFlow 是什么`，发送
3. 观察流式回复，**在流式过程中**截图（要看到 Stop 按钮存在），保存为 `02-streaming.png`
4. 等回复结束。注意：
   - 回复下方是否出现 follow-up 建议
   - 是否有 token 用量指示
   - 整体响应耗时

- [ ] **Step 2: 实操 — thread 管理操作**

1. 回到 `/workspace/chats` 列表
2. 在刚才新建的 thread 上**右键**，截图右键菜单（含重命名、删除等选项），保存为 `02-thread-context-menu.png`
3. 点重命名，改名为 `测试对话`，确认改名生效
4. 测试搜索：在列表搜索框输入「测试」，确认能命中
5. **不要删除**这个 thread —— 后面 Task 5/7 还要用

- [ ] **Step 3: 写 02-chat-and-threads.md**

Create `docs/user-guide/02-chat-and-threads.md`:

````markdown
# 02 对话与会话管理

> **适用角色：** [全员]

DeerFlow 的核心交互形式是对话（thread）。每个 thread 是一段独立的、有上下文记忆的对话历史。

## 创建新对话

在 `/workspace/chats` 点击新建按钮，或直接进入 `/workspace/chats/new`：

![新建对话入口](images/02-new-thread.png)

也可以在已有列表里直接点输入框开始打字 —— DeerFlow 会自动创建一个新 thread。

## 发送与接收消息

在底部输入框输入内容，回车或点发送。AI 的回复以**流式**逐字推送：

![流式回复中](images/02-streaming.png)

流式过程中：

- **Stop 按钮** 出现在输入框附近，点击立即中断这次回复（已生成的部分保留）
- 流式结束后通常会出现 **follow-up 建议**（一组可点击的"接下来你可能想问"）
- 如果模型支持，回复下方会显示 **token 用量**

> ⚠️ **当前版本没有"重新生成"按钮**。如果回复不满意，最简便的做法是手动复制你的问题，编辑后再发一次。详见 [09 常见问题](09-faq-and-known-issues.md)。

## 发送附件

输入框附带**附件按钮**，或直接把文件**拖到聊天区**完成上传。详细的文件交互（含产物下载）见 [05 文件与导出](05-files-and-export.md)。

## 会话列表与管理

`/workspace/chats` 列出你所有 thread，按最近活跃排序。

**搜索**：左上搜索框，按 thread 标题模糊匹配。

**右键菜单**：在某个 thread 上右键，会出现操作菜单：

![会话右键菜单](images/02-thread-context-menu.png)

- **重命名**：DeerFlow 默认从首条消息生成 thread 标题，你可以手动改成更有意义的名字
- **删除**：删除后无法恢复，请谨慎

**切换会话**：直接点击 thread 即可。

## 历史浏览

进入某个 thread 后，往上滚动可看到完整历史。DeerFlow 会按需加载更早的消息（无需手动翻页）。

## 下一步

- 想让 AI 用某个特定能力（搜索、写代码、画图等）→ [03 技能 (Skills)](03-skills.md)
- 想换一个特定方向的 agent（写作、编程、研究）→ [04 子智能体](04-agents.md)
````

- [ ] **Step 4: 自查文字与截图一致**

逐句对照截图：是否真的有 Stop 按钮？右键菜单选项是否就是文档里写的那些？token 用量如果没看到，删掉那一行。如有不符 → 改写文字。

- [ ] **Step 5: Commit**

```bash
git add docs/user-guide/02-chat-and-threads.md docs/user-guide/images/02-*.png
git commit -m "docs(user-guide): write chapter 02 — chat and threads

Verified: new thread creation, streaming + Stop button, rename via right-click, search.
Not verified: regenerate button — confirmed absent, flagged in chapter."
```

---

## Task 5: 03-skills.md（技能）

**Files:**
- Create: `docs/user-guide/03-skills.md`
- Create: `docs/user-guide/images/03-skill-library.png`
- Create: `docs/user-guide/images/03-skill-badge.png`
- Create: `docs/user-guide/images/03-upload-skill-modal.png`

- [ ] **Step 1: 实操 — 浏览 skill 库**

1. 进 `/workspace/skills`
2. 截图整个 skill 库页面（要看到 `All` 和 `My Skills` 两个 tab + 列表 + 搜索框），保存为 `03-skill-library.png`
3. 切换 `My Skills` tab，记录是否有自己的 skill（首次登录预期为空）

- [ ] **Step 2: 实操 — 加载 skill 到对话**

1. 在 `All` tab 找一个内置 skill（任意一个），点 "Load to session" 或类似按钮
2. 跳转到新建 thread 页（带 `?bind_skill=...` 参数）
3. 此时聊天界面应显示 skill badge —— 截图聊天页含 badge 区域，保存为 `03-skill-badge.png`
4. 观察 badge 显示的是 `/skill-name` 还是别的格式
5. 点 badge 上的 X 移除 skill，确认 badge 消失

- [ ] **Step 3: 实操 — 上传 skill 弹窗**

1. 回到 `/workspace/skills`，找上传按钮（"Upload" / "Publish" 或加号）
2. 弹出上传 modal 后截图（要含两个 tab：在线编辑器 / CLI 提示），保存为 `03-upload-skill-modal.png`
3. **不要真的提交** —— 只看 UI 形态。关掉弹窗

- [ ] **Step 4: 写 03-skills.md**

Create `docs/user-guide/03-skills.md`:

````markdown
# 03 技能 (Skills)

> **适用角色：** [全员]

## 什么是技能

**技能（skill）** 是 DeerFlow 给 AI 添加的"专长包"。你可以把它理解成给 AI 临时装上的一套工具+知识+流程模板：例如"写技术博客的技能"、"调研竞品的技能"、"操作 Airflow 的技能"。

技能由两个文件组成：

- `manifest.yaml` — 技能元数据（名字、描述、所需工具）
- `SKILL.md` — 给 AI 看的指令文档

技能可以由平台提供（内置），也可以由你自己创作并上传。

## 浏览技能库

进入 `/workspace/skills`：

![技能库](images/03-skill-library.png)

页面有两个 tab：

- **All** — 平台内所有可见的技能（含内置 + 已审核通过的用户技能）
- **My Skills** — 你创作并上传的技能（含未审核通过的草稿）

支持按名字搜索。

## 把技能装载到对话

在某个 skill 卡片上点 **"Load to session"**（或同义按钮），DeerFlow 会自动新建一个 thread 并把这个 skill 绑定上去。

进入对话后，输入框上方会出现 **skill badge**：

![Skill badge](images/03-skill-badge.png)

badge 形如 `/skill-name`，表示当前 thread 已激活该技能。

**移除技能**：点 badge 上的 X 即可。技能与 thread 是绑定关系，不影响其他 thread。

## 上传自己的技能

在 `/workspace/skills` 点上传按钮，会弹出：

![上传弹窗](images/03-upload-skill-modal.png)

两种上传方式：

- **在线编辑器** — 直接在浏览器粘贴 `manifest.yaml` 与 `SKILL.md` 内容，点发布
- **CLI** — 弹窗会显示一条命令，类似：
  ```
  deerflow skill publish ./path/to/skill-dir
  ```
  适合从本地仓库批量发布

### 提交后会发生什么

1. Skill 状态变为 **`pending_review`**（待审核）
2. 平台管理员在 [`/admin/skills`](08-platform-admin.md) 看到你的提交
3. 通过 → 状态变为 `active`，进入 `All` tab 可被任何人装载
4. 拒绝 → 你能在 `My Skills` 看到附带拒绝原因的状态

> 💡 在 `My Skills` tab 找不到自己刚上传的 skill？检查浏览器控制台是否报错，或刷新页面。如果仍未出现，可能是 `manifest.yaml` 解析失败 —— 详见 [09 常见问题](09-faq-and-known-issues.md)。

## 下一步

- 想给一个 thread 选不同的 AI 性格/专长 → [04 子智能体](04-agents.md)
- 上传完想知道审核进度 → [09 常见问题](09-faq-and-known-issues.md)
- 你是平台管理员，要审核别人提交的技能 → [08 平台管理员手册](08-platform-admin.md)
````

- [ ] **Step 5: 自查与微调**

- 如 Step 1 看到 `My Skills` tab 显示形态与文档不符（比如改名了），调整文字
- 如 Step 3 弹窗里 CLI 命令不是 `deerflow skill publish` 而是别的，改写文档里的示例命令
- 如发现 badge 实际显示形式不是 `/skill-name`，更新文字

- [ ] **Step 6: Commit**

```bash
git add docs/user-guide/03-skills.md docs/user-guide/images/03-*.png
git commit -m "docs(user-guide): write chapter 03 — skills

Verified: skill library browse, load-to-session, badge display, upload modal UI.
Not verified: end-to-end skill upload + admin review flow (admin-side covered in chapter 08)."
```

---

## Task 6: 04-agents.md（子智能体）

**Files:**
- Create: `docs/user-guide/04-agents.md`
- Create: `docs/user-guide/images/04-agent-gallery.png`
- Create: `docs/user-guide/images/04-mode-switcher.png`

- [ ] **Step 1: 实操 — agent 画廊**

1. 进 `/workspace/agents`
2. 截图画廊（含至少 2-3 个 agent 卡片），保存为 `04-agent-gallery.png`
3. 记下当前实例提供了哪些 agent（名字 + 简介）

- [ ] **Step 2: 实操 — 在 agent 下开新对话**

1. 点某个 agent 卡片进入详情或直接点 "New Chat"
2. 进入 `/workspace/agents/{agent_name}/chats/...` 类似路径
3. 在输入框附近找 **mode 切换器**（Flash / Thinking / Pro / Ultra），截图，保存为 `04-mode-switcher.png`
4. 观察各 mode 的副标题或 tooltip，记录含义

- [ ] **Step 3: 写 04-agents.md**

Create `docs/user-guide/04-agents.md`:

````markdown
# 04 子智能体 (Sub-Agents)

> **适用角色：** [全员]

## 什么是子智能体

DeerFlow 把一组**预配置的 prompt + 默认工具 + 默认行为**打包成 **sub-agent**。和 skill 的差异：

- **Skill** = 临时装载的"专长包"，跨 agent 通用，绑在单个 thread 上
- **Sub-agent** = 一整个独立的 AI 角色，有自己的画廊命名空间和默认设置

简单原则：

- 你想让 AI **临时**用某个能力 → 装 skill
- 你想固定使用一个**特定方向**的 AI（比如「研究员」「编码助手」） → 选 sub-agent

## 浏览 agent 画廊

进入 `/workspace/agents`：

![Agent 画廊](images/04-agent-gallery.png)

每张卡片是一个 sub-agent，含名字与简介。点击进入它的命名空间。

## 在指定 agent 下开新对话

点 agent 卡片或点 "New Chat" 按钮，DeerFlow 在 `/workspace/agents/{agent_name}/chats/...` 路径下开一个 thread。这个 thread 默认带上这个 agent 的所有配置。

## Mode 切换器

在输入框附近你会看到 mode 切换器：

![Mode 切换器](images/04-mode-switcher.png)

四档 mode（实际名称以你的实例为准）：

- **Flash** — 最快，最便宜。适合简单一问一答
- **Thinking** — 启用推理链，适合需要多步思考的问题
- **Pro** — 平衡速度与能力，多数场景的默认选择
- **Ultra** — 最强能力，最慢/最贵。复杂研究、长文写作时用

> 💡 mode 与 agent 是正交的：先选 agent（决定方向），再选 mode（决定算力）。

## 选择建议

| 场景 | Agent | Mode |
|---|---|---|
| 随便问一句 | 默认 | Flash |
| 写一段代码 | 编程类 agent | Pro |
| 多步推理（数学/逻辑） | 默认 | Thinking |
| 完整研究报告 | 研究类 agent | Ultra |

## 下一步

- 处理对话产生的文件 → [05 文件与导出](05-files-and-export.md)
- 调整界面或记忆 → [06 设置与记忆](06-settings-and-memory.md)
````

- [ ] **Step 4: 自查 — mode 名称是否与实例一致**

如 Step 2 看到的 mode 名不是 Flash/Thinking/Pro/Ultra，把文档里的四档名换成实际名称并相应调整选择建议表。

- [ ] **Step 5: Commit**

```bash
git add docs/user-guide/04-agents.md docs/user-guide/images/04-*.png
git commit -m "docs(user-guide): write chapter 04 — sub-agents

Verified: agent gallery, mode switcher UI, agent-namespace chat URL.
Mode names recorded as observed in current instance."
```

---

## Task 7: 05-files-and-export.md（文件与导出）

**Files:**
- Create: `docs/user-guide/05-files-and-export.md`
- Create: `docs/user-guide/images/05-attachment-upload.png`
- Create: `docs/user-guide/images/05-artifacts-panel.png`
- Create: `docs/user-guide/images/05-export-menu.png`

- [ ] **Step 1: 实操 — 上传文件给 agent**

1. 回到 Task 4 创建的 thread（或新建一个）
2. 准备一个本地小文件，如 `/tmp/hello.txt` 内容随意
3. 点附件按钮，上传 `hello.txt`，截图上传中或上传完成的状态，保存为 `05-attachment-upload.png`
4. 发一条消息「请总结附件内容」
5. 等待 AI 回复

- [ ] **Step 2: 实操 — Artifact 面板（如适用）**

1. 让 AI 产出一个文件（如发消息：「请生成一份 Markdown 格式的待办清单，并保存为 todo.md」）
2. 等 AI 完成。如成功生成产物，输入框附近或顶部应出现 "Files" 或 "Artifacts" 按钮 —— 点开，截图 artifact 面板，保存为 `05-artifacts-panel.png`
3. 测试下载 artifact

> 如果当前版本不通过 artifact 面板，而是直接在对话内显示下载链接，那就截那种形态，文档里如实描述。

- [ ] **Step 3: 实操 — 导出整个对话**

1. 在 thread 顶部找 "Export" 或类似下拉
2. 点击，截图下拉选项（Markdown / JSON），保存为 `05-export-menu.png`
3. 测试导出 Markdown，验证下载文件可读

- [ ] **Step 4: 写 05-files-and-export.md**

Create `docs/user-guide/05-files-and-export.md`:

````markdown
# 05 文件与导出

> **适用角色：** [全员]

## 上传文件给 AI

DeerFlow 允许你把文件作为对话上下文喂给 AI。两种方式：

1. **附件按钮** — 输入框旁边的回形针图标，弹文件选择器
2. **拖放** — 直接把文件拖到聊天区

![附件上传](images/05-attachment-upload.png)

上传完成后，附件以缩略卡片显示在你这条消息里。AI 会在回复时引用其内容。

支持的文件类型取决于部署配置（常见的文本、图像、PDF 通常 OK）。

## AI 产出的文件（Artifacts）

当 AI 主动生成文件（如脚本、报告、表格），它会出现在 **Artifacts** 面板：

![Artifacts 面板](images/05-artifacts-panel.png)

操作：

- **预览** — 点 artifact 卡查看内容
- **下载** — 把文件保存到本地
- **特殊：`.skill` 文件** — 如果 artifact 是 `.skill` 文件，卡片上会有"安装为我的技能"按钮，一键把它加到 [我的技能](03-skills.md#my-skills)

## 导出整个对话

需要把对话发给同事、归档、或喂给别的工具？用导出：

![导出菜单](images/05-export-menu.png)

两种格式：

- **Markdown** — 人类可读，适合贴到文档/邮件
- **JSON** — 结构化数据，含完整元数据（时间戳、模型、token 用量）

## 下一步

- 调整界面或语言 → [06 设置与记忆](06-settings-and-memory.md)
- 不知道某个文件没出现是哪里有问题 → [09 常见问题](09-faq-and-known-issues.md)
````

- [ ] **Step 5: 自查**

按实际看到的文案/位置微调文字（特别是 artifact 面板的进入方式与导出菜单的位置）。

- [ ] **Step 6: Commit**

```bash
git add docs/user-guide/05-files-and-export.md docs/user-guide/images/05-*.png
git commit -m "docs(user-guide): write chapter 05 — files and export

Verified: file upload via attachment button, artifact panel (or inline file links), export Markdown/JSON.
"
```

---

## Task 8: 06-settings-and-memory.md（设置与记忆）

**Files:**
- Create: `docs/user-guide/06-settings-and-memory.md`
- Create: `docs/user-guide/images/06-settings-appearance.png`
- Create: `docs/user-guide/images/06-settings-memory.png`
- Create: `docs/user-guide/images/06-settings-tools.png`

- [ ] **Step 1: 实操 — 打开设置弹窗**

1. 在左侧栏底部找齿轮图标点击
2. 弹出设置弹窗（应有多个 tab：Appearance / Memory / Notifications / Tools / Skills / About）
3. 切到 **Appearance** tab，截图，保存为 `06-settings-appearance.png`
4. 切到 **Memory** tab，截图（含摘要区与手动事实增删区），保存为 `06-settings-memory.png`
5. 切到 **Tools** tab，截图（应是只读工具列表），保存为 `06-settings-tools.png`

- [ ] **Step 2: 实操 — 切换主题与语言**

1. 在 Appearance tab 切换主题为 Dark，确认整界面变深色
2. 切回原主题
3. 切语言为 zh-CN（如默认是 en-US），确认 UI 文字变中文
4. 保留你舒服的语言

- [ ] **Step 3: 实操 — 加一条手动 memory 事实**

1. 在 Memory tab 找"添加事实"或类似输入
2. 加一条：`我喜欢用中文回答` 或类似无害事实
3. 确认列表里出现这条
4. 不删除（用于后续 Task 11 FAQ 演示）

- [ ] **Step 4: 写 06-settings-and-memory.md**

Create `docs/user-guide/06-settings-and-memory.md`:

````markdown
# 06 设置与记忆

> **适用角色：** [全员]

点击左侧栏底部的齿轮图标打开设置弹窗。所有用户级偏好与个人记忆都在这里。

## Appearance（外观）

![设置-外观](images/06-settings-appearance.png)

- **Theme** — Light / Dark / System（跟随系统）
- **Language** — `en-US` / `zh-CN`，影响所有界面文字

切换立即生效，记录在浏览器本地。

## Memory（记忆）

DeerFlow 维护两类长期记忆：

![设置-记忆](images/06-settings-memory.png)

- **摘要（Summaries）** — 由 AI 在对话中自动累积、提取的高层结论。通常**只读**，DeerFlow 持续更新它
- **手动事实（Facts）** — 你显式添加的固定事实（如「我所在时区是 UTC+8」「我的代码风格偏好 4 空格缩进」）

操作：

- **添加事实** — 在输入框输入一句简短陈述，回车
- **删除/编辑** — 点列表条目右侧操作按钮
- **导出** — 点导出按钮拿到 JSON 备份
- **导入** — 选择之前导出的 JSON 把记忆恢复到当前账号

> 💡 记忆作用于整个账号，不是单个 thread。一旦写入，新建的 thread 也会受影响。

## Notifications（通知）

授权浏览器通知后，AI 长任务跑完会推送桌面提示。常用于让你能在等回复时切到别的窗口干别的。

## Tools（工具）

![设置-工具](images/06-settings-tools.png)

只读列表，显示当前部署可用的工具（如 web 搜索、Python 沙箱、代码执行器等）。**这里只能看不能开关** —— 工具是否可用由部署时的 `config.yaml` 决定。

## Skills（技能 CLI 集成）

如果你想用命令行从本地仓库发布技能，这里管理 CLI 用的访问 token。详见 [03 技能](03-skills.md#上传自己的技能)。

## About（关于）

显示版本号、上游链接、许可证信息。遇到 bug 时，附上这里的版本号能帮维护者快速定位。

## 下一步

- 你是组织管理员，要管理团队成员 → [07 组织管理员手册](07-org-admin.md)
- 普通用户阅读结束，回到 [README](README.md) 或翻 [09 常见问题](09-faq-and-known-issues.md)
````

- [ ] **Step 5: 自查 — 实际 tab 与文档对照**

如实际只有 4 个 tab 而不是 6 个，或某个 tab 名称不同，按实际改。

- [ ] **Step 6: Commit**

```bash
git add docs/user-guide/06-settings-and-memory.md docs/user-guide/images/06-*.png
git commit -m "docs(user-guide): write chapter 06 — settings and memory

Verified: settings dialog tabs, theme/language switch, manual memory fact add."
```

---

## Task 9: 07-org-admin.md（组织管理员手册）

**Files:**
- Create: `docs/user-guide/07-org-admin.md`
- Create: `docs/user-guide/images/07-admin-entry.png`
- Create: `docs/user-guide/images/07-users-list.png`
- Create: `docs/user-guide/images/07-token-create.png`
- Create: `docs/user-guide/images/07-audit-log.png`

- [ ] **Step 1: 检查当前账号能否进 admin**

打开 `http://localhost:2026/admin`：

- 如能看到管理界面 → 当前账号有 tenant_owner 或 platform_admin 权限，**实操路线 A**
- 如跳到 `/forbidden` 或显示无权限 → **实操路线 B**：本章节标 ⚠️ 未实操

记录走 A 还是 B。

- [ ] **Step 2A（如走路线 A）实操 — 浏览各 admin 页**

依次访问以下路径，每页截图主要功能区：

- `/admin/profile` → 个人资料 + token + sessions
- `/admin/users` → 用户列表 + 搜索 → `07-users-list.png`
- `/admin/workspaces` → 工作区列表
- `/admin/tokens` → token 列表 + 点"创建" → `07-token-create.png`（创建 token 后**截图含明文展示**那一刻，记得敏感字符打码）
- `/admin/org-keys` → org keys 列表 + 创建对话框
- `/admin/audit` → 审计日志 → `07-audit-log.png`
- `/admin/roles` → 5 个预设角色

整体 admin 入口截图：`07-admin-entry.png`

- [ ] **Step 2B（如走路线 B）跳过实操**

直接进入 Step 3 写文档，文件顶部加 ⚠️ admonition。

- [ ] **Step 3: 写 07-org-admin.md**

Create `docs/user-guide/07-org-admin.md`:

````markdown
# 07 组织管理员手册

> **适用角色：** [组织管理员]（[平台管理员] 也可阅读 —— 你的权限是它的超集）

<!-- IF 路线 B：在此处插入下面的 admonition；路线 A 不插入。 -->
<!-- 
> ⚠️ **本章节未由 tenant_owner 账号实操验证**
> 当前文档基于代码读取与 spec 整理。如发现实际 UI 与文字描述不符，请以实际为准并提 issue。
-->

作为组织管理员（`tenant_owner` 角色），你能管理本组织/租户内的用户、工作区、API token、审计日志与 Org Keys。

## 进入管理后台

访问 `/admin` 会自动跳转到默认管理页：

![Admin 入口](images/07-admin-entry.png)

如果你登录后看到 **403 Forbidden**，说明当前账号没有管理权限，请联系平台管理员授权。

## 个人资料（`/admin/profile`）

- 修改 **display_name**
- 管理你**自己**的个人 API token（与下面的「API Token」组织级 token 不同 —— 这里是仅你能用的）
- 查看活跃 session 列表，可单点撤销某个 session（用于"刚换设备登录，把旧的踢掉"）

## 用户管理（`/admin/users`）

![用户管理](images/07-users-list.png)

- **列表** — 列出本租户全部用户，支持按 email 筛选与翻页
- **邀请** — 点"创建用户"或"邀请"按钮，填写 email + 显示名

> ⚠️ 用户**详情页**（`/admin/users/{id}`）当前是占位页（stub），改角色等高级操作目前需通过 API 调用或后续版本完善。详见 [09 已知限制](09-faq-and-known-issues.md)。

## 工作区管理（`/admin/workspaces`）

- **新建** workspace（slug + name）
- **重命名** 已有 workspace
- **删除** workspace（不可恢复）
- **管理成员**：进入 `/admin/workspaces/{id}/members` 增减成员、改角色

> ⚠️ 工作区详情页与成员子页的 UI 完整度仍在打磨。如某些操作按钮无反应，可能尚未接通。

## API Token（`/admin/tokens`）

![Token 创建](images/07-token-create.png)

- **创建 token** — 填名称、scope、过期时间。**保存后明文只显示这一次** —— 立刻复制并存到密码管理器
- **撤销 token** — 列表行的撤销按钮，即时生效
- **过期** — 过期 token 会自动失效但仍占列表行，可手动删除

⚠️ **明文丢失就完了**。如果你忘了复制，唯一办法是撤销旧 token + 重新创建。

## Org API Keys（`/admin/org-keys`）

与"API Token"的差异：

| | API Token | Org API Keys |
|---|---|---|
| 归属 | 用户个人 | 组织共享 |
| 用途 | 个人脚本/CLI | 系统对接、CI |
| 过期 | 必须设置 | 可选"永不过期" |
| 撤销影响 | 只影响该用户 | 影响所有使用该 key 的系统 |

## 审计日志（`/admin/audit`）

![审计日志](images/07-audit-log.png)

- **筛选** — action / user_id / resource_type / result / 日期范围（7-90 天窗口）
- **详情** — 点行展开看 actor、resource、payload diff
- **导出 CSV** — 上限 10 万行，超过会返回 413（请缩小日期范围或加更严的筛选）

合规审计、用户行为追溯、可疑操作排查都靠这里。

## 角色（`/admin/roles`）

只读列表，展示当前部署的 5 个预设角色（platform_admin / tenant_owner / tenant_member / workspace_admin / workspace_member）和它们的默认权限映射。**不能改 —— 仅作参考**。

## 下一步

- 你也是平台管理员 → [08 平台管理员手册](08-platform-admin.md)
- 遇到具体某个功能不工作 → [09 常见问题](09-faq-and-known-issues.md)
````

- [ ] **Step 4: 根据路线 A/B 决定 admonition**

- 如 Step 1 走路线 A → 删掉文档里整段 `<!-- IF 路线 B -->` 注释块
- 如走路线 B → 删掉 HTML 注释包装，让里面的 admonition 真正显示

- [ ] **Step 5: Commit**

```bash
git add docs/user-guide/07-org-admin.md docs/user-guide/images/07-*.png 2>/dev/null || git add docs/user-guide/07-org-admin.md
git commit -m "docs(user-guide): write chapter 07 — org admin

Verified: <根据实际填，如 'admin entry, users list, token create' 或 'none — current account lacks tenant_owner role; chapter flagged as not verified'>"
```

---

## Task 10: 08-platform-admin.md（平台管理员手册）

**Files:**
- Create: `docs/user-guide/08-platform-admin.md`
- Create: `docs/user-guide/images/08-tenants-list.png`（如可实操）
- Create: `docs/user-guide/images/08-skill-review.png`（如可实操）

- [ ] **Step 1: 检查当前账号能否进平台管理功能**

访问 `/admin/tenants` 与 `/admin/skills`：

- 都能正常加载数据 → **路线 A（实操）**
- 任一返回 403 / 跳到 forbidden → **路线 B（未实操）**

记录走 A 还是 B。

- [ ] **Step 2A（路线 A）实操**

1. `/admin/tenants` → 列表 + 创建按钮，截图 `08-tenants-list.png`
2. `/admin/skills` → 三个 tab（pending / active / rejected），截图 `08-skill-review.png`
3. 不实际审核任何真实 pending skill（避免误改状态），只看 UI

- [ ] **Step 2B（路线 B）跳过实操**

文档顶部加 ⚠️ admonition，正文基于 spec 编写，不放截图（或用占位）。

- [ ] **Step 3: 写 08-platform-admin.md**

Create `docs/user-guide/08-platform-admin.md`:

````markdown
# 08 平台管理员手册

> **适用角色：** [平台管理员]

<!-- IF 路线 B：保留下面的 admonition；路线 A：删除整段。 -->
<!-- 
> ⚠️ **本章节未由 platform_admin 账号实操验证**
> 当前文档基于代码读取与 spec 整理。如发现实际 UI 与文字描述不符，请以实际为准并提 issue。
-->

作为平台管理员（`platform_admin` 角色），你拥有最高权限：除了组织管理员能做的事，你还能管理租户、审核全平台技能、跨租户查审计。

## 与组织管理员的差异

| 能力 | 组织管理员 | 平台管理员 |
|---|---|---|
| 管理本租户用户/工作区/Token/审计 | ✅ | ✅ |
| 管理多个租户（创建/删除/查统计） | ❌ | ✅ |
| 跨租户审计查询 | ❌ | ✅ |
| 审核全平台技能 | ❌ | ✅ |

## 租户管理（`/admin/tenants`）

![租户列表](images/08-tenants-list.png)

- **创建租户** — 填 slug + name。slug 是唯一标识，进库后不可改名
- **列表** — 支持 slug 模糊筛选与翻页
- **改名** — 只改 display name，不改 slug
- **软删除** — 标记 deactivated，租户内数据保留但不可登录。**没有硬删按钮** —— 真要清数据需要后端运维操作

> ⚠️ **租户详情页**（`/admin/tenants/{id}`）当前是占位页。详细统计与 owner 转移等高级操作需要通过后端 API 或后续版本。

## 技能审核（`/admin/skills`）

![技能审核](images/08-skill-review.png)

页面顶部三个 tab：

1. **Pending Review** — 用户上传等审核的 skill。点条目查看 manifest + SKILL.md 内容
2. **Active** — 已通过、对全平台可见
3. **Rejected / Archived** — 已拒绝或下架

操作：

- **通过（Approve）** — skill 状态变为 `active`，进入 `All` tab
- **拒绝（Reject）** — 必须填**拒绝原因**，作者能在自己的 `My Skills` 看到
- **下架** — 把 active 的 skill 移到 archived，已绑定该 skill 的 thread 不受影响（但新装载会失败）

> 💡 审核标准建议：
> 1. `manifest.yaml` 元数据完整、描述清晰
> 2. `SKILL.md` 没有恶意指令、不试图绕过权限
> 3. 不与已有内置 skill 严重重名

## 跨租户审计

普通组织管理员的 `/admin/audit` 只能看本租户。平台管理员的同一页（或 `/admin/audit` 跨租户视图）允许选「全部租户」筛选条件。其他筛选与导出功能与组织管理员一致。

## 已知限制

详见 [09 已知限制](09-faq-and-known-issues.md)：

- 租户详情页 stub
- M6 audit fallback.jsonl 路径异常时 gateway 启动可能失败（运维相关）

## 下一步

- 回到 [README](README.md)
- 处理用户反馈的具体问题 → [09 常见问题](09-faq-and-known-issues.md)
````

- [ ] **Step 4: 根据路线 A/B 处理 admonition**

同 Task 9 Step 4。

- [ ] **Step 5: Commit**

```bash
git add docs/user-guide/08-platform-admin.md docs/user-guide/images/08-*.png 2>/dev/null || git add docs/user-guide/08-platform-admin.md
git commit -m "docs(user-guide): write chapter 08 — platform admin

Verified: <按实际填>"
```

---

## Task 11: 09-faq-and-known-issues.md（FAQ + 已知限制）

**Files:**
- Create: `docs/user-guide/09-faq-and-known-issues.md`

- [ ] **Step 1: 写 09-faq-and-known-issues.md**

Create `docs/user-guide/09-faq-and-known-issues.md`:

````markdown
# 09 常见问题与已知限制

> **适用角色：** [全员]

本章先答常见问题，再诚实列出已知未完成或不可靠的功能 —— 让你在踩坑时能快速判断「这是我的问题还是系统的问题」。

## 常见问题（FAQ）

### Q1: 忘了密码怎么办

DeerFlow 当前**没有自助密码重置入口**。请联系平台管理员通过后端工具或数据库重置。如果你是平台管理员自己锁了自己……准备好运维 shell。

### Q2: 我的 session 突然失效，要重新登录

正常现象。session 有有效期，过期后任何 API 都会返回 401。前端拦截后会自动跳到 `/login`。重新登录即可，对话历史不会丢。

### Q3: 创建 token 后我没复制明文，token 保存到哪了？

**没保存。** 出于安全考量，DeerFlow 不在数据库存明文 token，只存哈希。一旦弹窗关闭，明文不可恢复。**正确做法**：撤销那个 token，重建一个，这次记得立刻贴到密码管理器。

### Q4: 我上传的 skill 在 `My Skills` 看不到

按概率从高到低排查：

1. **状态是 pending_review** → 有的 UI 把待审稿放在另一个 tab 或加灰色徽章。仔细找
2. **`manifest.yaml` 解析失败** → DeerFlow 不会显示损坏的 skill。在浏览器 DevTools → Network 看 `/api/skills` 响应，看是否有解析错误
3. **缓存问题** → 强刷（Cmd+Shift+R）

### Q5: AI 回复不满意，怎么"重新生成"

当前版本没有 regenerate 按钮（[已知限制](#已知限制) 第 1 条）。变通做法：

- **手动复制问题，编辑后再发** —— 最简单
- 在新 thread 里换个说法重问

### Q6: 切换语言后，AI 也会改用那个语言回答吗

**不会自动改。** 语言设置只影响**界面文字**。如果想让 AI 用中文/英文回答，在记忆里加一条手动事实如「请始终用中文回答」（[06 设置与记忆](06-settings-and-memory.md)）。

### Q7: 不同 thread 之间能共享上下文吗

**默认不能。** 每个 thread 是独立上下文。你如果想让多个 thread 共享一些"这个用户的固定背景"，用[手动 memory 事实](06-settings-and-memory.md)。

### Q8: 我导出的 .skill 文件能在别的 DeerFlow 实例用吗

可以。`.skill` 是标准压缩包格式，含 `manifest.yaml` + `SKILL.md`，可在任何同版本 DeerFlow 实例的[安装界面](03-skills.md#上传自己的技能)上传。

### Q9: 管理员能看到我私聊的内容吗

**理论上可以**。审计日志（`/admin/audit`）记录的是事件元数据（谁在什么时候做了什么），不直接记录消息内容；但平台管理员有数据库访问权 → 物理上能查任何 thread。如果你处理敏感信息，请确认你信任部署方。

## 已知限制

以下是当前文档基线版本（`cc-main @ b3cfac65`）确认存在的不完整功能。提 issue 或贡献修复都欢迎。

### 1. 聊天没有「重新生成」按钮

代码扫描确认前端无 regenerate UI，详见 [02 对话](02-chat-and-threads.md)。**变通**：手动复制问题再发一次。

### 2. 输入框 Connector 面板未实现

代码里有 `/* TODO: Add more connectors here */` 注释。当前用户看不到任何 connector 入口，也没有副作用 —— 只是一个未完成的扩展点。

### 3. 部分 admin 详情页是占位页（stub）

- `/admin/tenants/{id}` —— 租户详情、统计、owner 转移等需通过 API
- `/admin/users/{id}` —— 用户详情/角色调整需通过 API
- `/admin/workspaces/{id}/members` —— 完整度待验证

变通：能通过列表页 + API 直接调用做的事，先用 API。

### 4. OIDC 未在真实 IdP 上端到端验证

代码层支持 OIDC 流程，但当前基线版本没有针对 Keycloak / Okta / Azure AD 等具体 IdP 做过完整冒烟。如你是首次接 IdP，建议：

- 先用邮箱+密码确认账号本身可用
- 把 IdP 配置失败当作配置问题（多半是 redirect_uri、client_id、scope、JWT issuer 校验之一）
- 后端 gateway 日志 `logs/gateway.log` 看 OIDC 错误明细

### 5. 审计 fallback.jsonl 路径异常时 gateway 启动失败（M6 P0 bug）

当 PostgreSQL 不可达时，DeerFlow 会回落写本地 jsonl。但当前实现下 `fallback.jsonl` **被错误创建为目录**而不是文件，导致下次启动 gateway 抛 `IsADirectoryError`。

**变通**：

```bash
# 找到该文件路径（一般在 logs/audit/ 下）
find . -name "fallback.jsonl" -type d
# 删掉这个错位的目录
rm -rf <path>/fallback.jsonl
# 重启 gateway
make stop && make dev-daemon
```

### 6. 没有自助密码重置

如 Q1 所述。

## 反馈

- 提 issue：仓库 issue 区
- 直接修：欢迎 PR
- 想了解某个功能为什么这么设计：[原始 spec](../superpowers/specs/2026-04-27-user-guide-design.md)
````

- [ ] **Step 2: 校对**

- 检查所有 `[xxx](path)` 链接相对路径是否对（README.md 用 `README.md`，spec 用 `../superpowers/specs/...`）
- 检查 9.5 fallback.jsonl 路径示例是否合理（用户能看懂，不会一上来就 rm 错地方）
- Q9 关于隐私的描述是否中立（不要被理解成项目质疑）

- [ ] **Step 3: Commit**

```bash
git add docs/user-guide/09-faq-and-known-issues.md
git commit -m "docs(user-guide): write chapter 09 — FAQ and known issues

Documented 9 FAQ items and 6 known limitations identified during inventory + happy-path walk."
```

---

## Task 12: 整体校对与定稿

**Files:**
- Modify: `docs/user-guide/README.md`（如发现链接死链）
- Modify: 任意章节（如发现一致性问题）

- [ ] **Step 1: 链接体检**

```bash
cd docs/user-guide
grep -rn "](.*\.md" . | grep -v node_modules
```

人肉检查：
- 每个相对链接是否真的指向存在的文件
- 章节内 `#anchor` 是否对应真实标题（GitHub 自动 slug 规则：小写、空格变 `-`、中文保留）

- [ ] **Step 2: 截图体检**

```bash
ls docs/user-guide/images/
grep -rn "images/" docs/user-guide/*.md
```

- 文档里引用的每个截图都存在
- `images/` 里没有未被引用的孤儿图（如有，删除或在文档里引用）

- [ ] **Step 3: 三角色阅读路径走查**

按 README 推荐路径分别走 3 遍：

1. **普通用户路径**：README → 01 → 02 → 03 → 04 → 05 → 06 → 09 — 每个"下一步"链接都能跳，文字读起来连贯
2. **组织管理员路径**：上面 + 07
3. **平台管理员路径**：上面 + 08

发现死链或语义跳跃 → 修。

- [ ] **Step 4: 一致性自查**

- 文档版本注脚 `cc-main @ b3cfac65` 在 README 与每章是否一致（建议只在 README 标，其他章节不重复）
- "技能"/"skill"、"工作区"/"workspace"、"租户"/"tenant" 中英术语在每章统一
- 所有 ⚠️ admonition 格式一致

- [ ] **Step 5: 最终 commit（如有调整）**

```bash
git add docs/user-guide/
git status
git commit -m "docs(user-guide): final pass — link & consistency fixes" || echo "Nothing to commit, all good."
```

- [ ] **Step 6: 回归到 spec 的验收标准核对**

逐条核对 [spec §7](../specs/2026-04-27-user-guide-design.md)：

- [x] 9 个章节 + README + images 全部存在 ✅
- [x] 三类角色推荐阅读路径无死链 ✅（Step 3 已检）
- [x] 每张截图都被引用 ✅（Step 2 已检）
- [x] 09 章已知限制 ≥ 5 条 ✅（已写 6 条）
- [x] 操作步骤要么实操过、要么明确标注未实操 ✅（Task 9/10 admonition）
- [x] 文档版本注脚标 commit hash ✅（README 已标）
- [x] 当前账号权限不足的章节用 admonition 注明 ✅（Task 9/10 路线 B）

如有任一条不达标，回到对应 Task 修。

---

## Self-Review

**Spec 覆盖核对：**

| Spec 节 | 对应 Task |
|---|---|
| §3 文档结构（9 章 + README + images） | Task 1 + Task 2-11 各章 |
| §4.1 README | Task 2 |
| §4.2 01-getting-started | Task 3 |
| §4.3 02-chat-and-threads | Task 4 |
| §4.4 03-skills | Task 5 |
| §4.5 04-agents | Task 6 |
| §4.6 05-files-and-export | Task 7 |
| §4.7 06-settings-and-memory | Task 8 |
| §4.8 07-org-admin | Task 9 |
| §4.9 08-platform-admin | Task 10 |
| §4.10 09-faq-and-known-issues | Task 11 |
| §5 编写流程 | Task 1-12 整体 |
| §6 已知问题清单 | Task 11 (09 章 6 条已知限制) |
| §7 验收标准 | Task 12 Step 6 |

**所有 spec 条目都有对应 task。**

**Placeholder 扫描：** 计划内无 TBD/TODO/「类似 Task N」/「待补」。Task 9/10 的 `<根据实际填>` 是明确的填空指令而非 placeholder（路线 A/B 决定填什么，路径已写清）。

**类型一致性：** 不涉及代码类型；术语在 spec/plan 中保持一致（technical name 用英文：`tenant_owner`、`platform_admin`、`pending_review`）。

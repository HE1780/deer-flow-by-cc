> 📦 **归档于 2026-04-29 — 正文完成；截图全缺；09 章部分内容已过时**
>
> 详见 [OPEN_ISSUES.md OI-6](../../../OPEN_ISSUES.md)。

---

# DeerFlow 用户使用手册 — 设计稿

- **Date**: 2026-04-27
- **Status**: 🟡 正文完成 / 截图待补 / 09 章待修订（详见上方 banner）
- **Companion plan**: [../../plans/archive/2026-04-27-user-guide-implementation.md](../../plans/archive/2026-04-27-user-guide-implementation.md)
- **剩余工作**: ① 补 10+ 张截图（每章 1-2 张），可逐章增量提交；② 任何 UI 改动后回滚的章节复核（07/08 章已实操验证，01-06 写于 frontend/admin nav 改造前，需要确认仍然准确）
- **Author**: Brainstorm via Claude Code
- **Audience for this doc**: 自己（spec 评审） + 后续 implementation plan 作者

---

## 1. 背景与目标

### 1.1 背景

DeerFlow 是一个开源 super agent harness。当前仓库（`HE1780/deer-flow-by-cc`）是 ByteDance 上游的 fork，已经在上面叠加了 P0 identity foundation（M1-M7：身份、RBAC、storage 隔离、audit、admin UI）和若干前端改进。当前阶段定位为「私有化自托管开源项目」，需要一份给最终用户看的系统使用说明 —— **不是测试报告、不是技术文档、不是 spec**，而是面向「装好之后真的要用 DeerFlow 干活的人」的产品手册。

### 1.2 目标

1. 给三类角色（普通用户 / 组织管理员 / 平台管理员）提供清晰的"怎么用 DeerFlow"说明文档。
2. 文档内容 100% 与当前代码一致 —— 写文档的过程包含一次实际的 happy path 走查（用 `tsamilijohn206@gmail.com` / `ChangeMe!2026` 登录，沿步骤实操），保证文档不说谎。
3. 路径外的高级功能（IM channels / MCP 集成 / Langfuse / sandbox 高级配置）暂不进本手册 —— 留作后续运维篇。
4. 已知未完成功能（详见 §6）在 FAQ / Known Issues 一章诚实列出，不糊弄读者。

### 1.3 非目标

- ❌ 安装部署文档 — 假设运维或自托管者已经把 DeerFlow 装好、模型配好（这部分 `Install.md` 已覆盖）。
- ❌ 给开发者看的架构 / API / spec 文档。
- ❌ 测试报告、验证矩阵、pass-fail 表格。
- ❌ IM channels / MCP / Langfuse / sandbox 高级章节。
- ❌ 上游 ByteDance 文档的中文翻译。

---

## 2. 角色定义

| 角色 | 文档内标签 | RBAC 角色键 | 大致权限 |
|---|---|---|---|
| 普通用户 | `[全员]` | `workspace_member` | 在自己工作区聊天、用 skill、传文件、改个人设置 |
| 组织管理员 | `[组织管理员]` | `tenant_owner` | 管理租户内用户、工作区、token、审计、org keys |
| 平台管理员 | `[平台管理员]` | `platform_admin` | 在「组织管理员」之上额外能管理租户、审核 skill、跨租户审计 |

**继承关系**：平台管理员 ⊃ 组织管理员 ⊃ 普通用户。文档章节按「最低能看到该功能的角色」打标签 —— 平台管理员能看到所有 `[全员]` 和 `[组织管理员]` 章节。

---

## 3. 文档结构

```
docs/user-guide/
├── README.md                       # 索引 + 角色标签说明 + 阅读路径
├── 01-getting-started.md           # 登录、首次进入、界面总览              [全员]
├── 02-chat-and-threads.md          # 聊天、thread 管理、附件、流式、停止   [全员]
├── 03-skills.md                    # 浏览 / 上传 / 绑定 skill              [全员]
├── 04-agents.md                    # Sub-agent 画廊、mode 切换             [全员]
├── 05-files-and-export.md          # 文件上传下载、artifact、聊天导出     [全员]
├── 06-settings-and-memory.md       # 设置面板、记忆、语言、主题、个人 token [全员]
├── 07-org-admin.md                 # 用户、工作区、Token、审计、Org Keys   [组织管理员]
├── 08-platform-admin.md            # 租户管理、Skill 审核、跨租户审计      [平台管理员]
├── 09-faq-and-known-issues.md      # 常见问题 + 已知限制                   [全员]
└── images/
    ├── 01-*.png                    # 与章节编号对齐
    └── ...
```

### 3.1 章节内的角色标签约定

文件顶部统一用：

```markdown
> **适用角色：** [全员] / [组织管理员] / [平台管理员]
```

混合章节内的小节顶部用行内标签：

```markdown
### 创建工作区 [组织管理员]
### 审核待批 skill [平台管理员]
```

普通用户读到带 `[组织管理员]` / `[平台管理员]` 标签的章节就知道这是越权内容，不会困惑。

---

## 4. 各章节详细规划

每章节大致按「这是什么 → 在哪里 → 怎么操作 → 常见问题」组织。每章 1500-3000 字，配 2-4 张关键截图。

### 4.1 README.md

- DeerFlow 是什么（一段话）
- 三种角色定义 + 标签说明
- 推荐阅读路径：
  - 普通用户：01 → 02 → 03 → 04 → 05 → 06 → 09
  - 组织管理员：以上 + 07
  - 平台管理员：以上 + 08
- 文档版本与代码版本对齐说明（写明是基于 `cc-main` 分支某个 commit 的）

### 4.2 01-getting-started.md `[全员]`

- 登录页面：邮箱密码登录、OIDC 登录入口
- 登录成功后的默认落地页 = `/workspace/chats`
- 整体界面布局（左侧栏 / 主区 / 右侧设置入口）
- 顶部导航说明 + workspace switcher（如果用户跨多个 workspace）
- 退出登录在哪

**截图**：登录页、登录后首页（标注左中右三区）

### 4.3 02-chat-and-threads.md `[全员]`

- 新建 thread（点 New / 直接发第一条消息）
- 发送消息、流式回复观察、Stop 按钮
- Token 用量指示（如果模型支持显示）
- Follow-up 建议
- Thread 列表：搜索、按时间排序
- 切换 / 重命名（右键）/ 删除（右键）
- 历史浏览

**截图**：新建 thread、聊天进行中（标注 Stop）、thread 列表 + 右键菜单

### 4.4 03-skills.md `[全员]`

- 什么是 skill（一段话非技术解释）
- Skill 库页面：浏览、搜索、All vs My Skills tab
- 加载 skill 到对话（"Load to session" 按钮）
- 在聊天里看到 skill badge / `/skill-name` 前缀
- 移除 skill
- 上传自己的 skill：在线编辑器 tab（粘贴 manifest.yaml + SKILL.md）/ CLI tab（`deerflow skill publish`）
- Skill 提交后的状态：pending_review → 等管理员审 → active / rejected（审核流程详见 4.9 08-platform-admin.md，普通用户问"为啥还没过"看 09 FAQ）

**截图**：skill 库、skill badge、上传弹窗

### 4.5 04-agents.md `[全员]`

- 什么是 sub-agent（与 skill 的差异：一段话）
- Agent 画廊：`/workspace/agents`
- 在 agent namespace 下开新对话
- 输入框里的 Mode 切换器（Flash / Thinking / Pro / Ultra）含义
- 如何选择合适的 agent + mode 组合（一段建议）

**截图**：agent 画廊、mode 切换器

### 4.6 05-files-and-export.md `[全员]`

- 上传文件给 agent：附件按钮 / 拖放
- Artifact 面板：什么时候出现、怎么看产物
- 下载 agent 产出的文件
- `.skill` 文件特殊处理：可一键安装为个人 skill
- 导出聊天：Markdown / JSON

**截图**：上传中、artifact 面板、导出菜单

### 4.7 06-settings-and-memory.md `[全员]`

- Settings 入口（左侧栏底部齿轮）
- **Appearance**：主题（亮/暗/系统）、语言（en-US / zh-CN）
- **Memory**：摘要查看（只读）、手动事实增删改、JSON 导入导出
- **Notifications**：浏览器通知开关
- **Tools**：可用工具列表（只读）
- **Skills**：CLI token 管理（如果暴露给最终用户）
- **About**：版本号、链接

**截图**：Settings 弹窗（每个 tab 各一张关键示意）

### 4.8 07-org-admin.md `[组织管理员]`

- 进入入口：`/admin`（默认重定向到 `/admin/tenants`，组织管理员看到的是当前租户内容）
- **个人资料**（`/admin/profile`）：改 display_name、个人 API token、活跃 session 撤销
- **用户管理**（`/admin/users`）：邀请、列表、按 email 筛选 — 详情页是 stub，请见 §6
- **工作区管理**（`/admin/workspaces`）：创建、改名、删除、成员管理（成员子页面状态见 §6）
- **API Token**（`/admin/tokens`）：创建（明文一次性显示！）、撤销、过期管理
- **Org API Keys**（`/admin/org-keys`）：与 Token 的差异、创建（可设过期或永不过期）、撤销
- **审计日志**（`/admin/audit`）：分页 / 多维筛选（action / user / resource / result / 日期窗口 7-90 天）/ 详情 / CSV 导出（上限 10 万行）
- **角色查看**（`/admin/roles`）：5 个预设角色只读概览（用来理解权限模型）

**截图**：admin 入口、用户管理、token 创建明文展示、审计日志

### 4.9 08-platform-admin.md `[平台管理员]`

- 与组织管理员的差异
- **租户管理**（`/admin/tenants`）：创建、列表、改名、软删 — 详情页 stub 见 §6
- **Skill 审核**（`/admin/skills`）：3 个 tab（待审 / 通过 / 拒绝归档）、通过/拒绝 + 原因、`.skill` 文件直接安装
- **跨租户审计**：`/admin/audit` 在平台管理员视角下能跨租户查询

**截图**：租户列表、skill 审核三个 tab、跨租户审计

### 4.10 09-faq-and-known-issues.md `[全员]`

- **常见问题**：忘记密码？session 过期？token 丢了怎么办？skill 上传后没看到？
- **已知限制**（诚实列出）：
  - 聊天没有 regenerate 按钮 — 需要重新发送
  - Connector 面板未实现（输入框 TODO）
  - `/admin/tenants/[id]`、`/admin/users/[id]` 详情页是 stub，部分信息需通过列表/API 查
  - `/admin/workspaces/[id]/members` 子页面完整性待验证
  - OIDC 未在 Keycloak / Okta 等真实 IdP 上做过端到端测试
  - 审计 fallback.jsonl 路径异常时 gateway 启动可能失败 — 部署前需确认目录结构

---

## 5. 编写流程（implementation plan 的纲要）

实际的 implementation plan 由后续 writing-plans 阶段产出，这里只列纲要：

1. **环境准备**：用 `make dev-daemon` 起本地服务，用 `tsamilijohn206@gmail.com` / `ChangeMe!2026` 登录验证账号可用、确认角色。
2. **创建文档骨架**：建 `docs/user-guide/` 目录、所有 md 占位文件、`images/` 目录、README.md 索引。
3. **按章节顺序编写**（每章一个独立任务）：
   - 进对应页面 / 触发对应功能
   - 抓截图存到 `images/{章节号}-{描述}.png`
   - 边操作边写文档
   - 操作中如发现行为与预期不符 → 记入 09 已知限制 而不是写假
4. **角色覆盖**：组织管理员 / 平台管理员章节如果当前账号权限不够，记录"需要 platform_admin 账号验证"作为已知 gap，不强行编造。
5. **校对**：从 README 走一遍推荐阅读路径，确保跳转、术语、截图路径都对。
6. **commit**：分章节 commit，每章一次，commit message 用 `docs(user-guide): write chapter NN — <topic>` 形式。

---

## 6. 已知问题清单（在 09 章诚实公开）

| 问题 | 来源 | 对手册的处理方式 |
|---|---|---|
| 聊天无 regenerate 按钮 | 前端代码扫描 | 09 已知限制 + "可手动复制问题重发" workaround |
| Connector 面板 TODO | `/* TODO: Add more connectors here */` | 09 已知限制；不出现在 04 主线 |
| `/admin/tenants/[id]` 详情页 stub | 代码扫描 | 07 / 08 章对应位置注脚 + 09 列出 |
| `/admin/users/[id]` 详情页 stub | 代码扫描 | 07 章对应位置注脚 + 09 列出 |
| `/admin/workspaces/[id]/members` 完整性未确认 | 代码扫描 | 走 happy path 时实测，按结果归类 |
| OIDC 未真实 IdP 测试 | P0 audit | 09 列出，标注"按部署文档配置 IdP 后请自行验证" |
| Audit fallback.jsonl 是目录非文件 | M6 P0 bug | 09 列出，提示运维确认目录结构（这条偏运维但用户也可能踩到） |

---

## 7. 验收标准

文档完成视为达成下列全部条件：

- [ ] 9 个章节文件 + README + images 目录全部存在并 commit
- [ ] 三类角色推荐阅读路径都能从 README 跳转无死链
- [ ] 每个截图都能在对应章节看到引用
- [ ] 09 章已知限制不少于 5 条
- [ ] 所有「在哪/怎么做」操作步骤要么本机实操过、要么明确标注「未实操，待具备相应权限的账号验证」 —— 不允许「猜的但写得像实操过的」
- [ ] 文档版本注脚标明对应的 git commit hash
- [ ] 当前账号（`tsamilijohn206@gmail.com`）权限不足以验证的章节（特别是平台管理员章节），在该章节顶部用 admonition 注明「本章节内容基于代码读取，未由 platform_admin 账号实操验证」

---

## 8. 不在本设计内的事

- **写哪个语言版本**：默认中文（与项目已有 P0 文档语言一致）。如果将来要英文版，单独立项。
- **如何把文档发布到外部站点**（GitHub Pages / Docusaurus 等）：暂不考虑，文件本身在 repo 内可读即可。
- **文档与代码同步机制**：暂不上 doctest / CI 校验，仅依赖人工 review。
- **运维篇**：IM / MCP / Langfuse / sandbox / 部署相关，作为后续独立 spec。

# DeerFlow 用户使用手册

> 本手册面向已经登录到 DeerFlow 实例的最终用户与管理员。如需安装部署，请阅读项目根目录的 [Install.md](../../Install.md) 与 [README.md](../../README.md)。

**文档版本基线：** `cc-main @ 9b362f8a`（2026-04-28）

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

发现文档与实际行为不一致？欢迎在仓库提 issue 或直接发 PR。本手册的设计稿见 [docs/superpowers/specs/archive/2026-04-27-user-guide-design.md](../superpowers/specs/archive/2026-04-27-user-guide-design.md)。

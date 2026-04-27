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

> 📷 **截图占位**：`images/04-agent-gallery.png` — Agent 画廊

每张卡片是一个 sub-agent，含名字与简介。当前实例提供 3 个 agent：`123`（默认）、`brainstorm`（写作大师）、`writer`。

## 在指定 agent 下开新对话

点 agent 卡片或点 "New Chat" 按钮，DeerFlow 在 `/workspace/agents/{agent_name}/chats/...` 路径下开一个 thread。这个 thread 默认带上这个 agent 的所有配置（SOUL.md、默认工具组、绑定技能等）。

## Mode 切换器

在输入框附近你会看到 mode 切换器：

> 📷 **截图占位**：`images/04-mode-switcher.png` — Mode 切换器

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

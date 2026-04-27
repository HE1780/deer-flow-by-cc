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

> 📷 **截图占位**：`images/03-skill-library.png` — 技能库页面

页面有两个 tab：

- **All** — 平台内所有可见的技能（含内置 + 已审核通过的用户技能）
- **My Skills** — 你创作并上传的技能（含未审核通过的草稿）

支持按名字搜索。当前实例提供的技能涵盖学术论文审阅、数据分析、PPT 生成、前端设计、深度研究、图表可视化等方向（共 21 个公共技能）。

## 把技能装载到对话

在某个 skill 卡片上点 **"Load to session"**（或同义按钮），DeerFlow 会自动新建一个 thread 并把这个 skill 绑定上去。

进入对话后，输入框上方会出现 **skill badge**：

> 📷 **截图占位**：`images/03-skill-badge.png` — 聊天页 skill badge 显示

badge 形如 `/skill-name`，表示当前 thread 已激活该技能。

**移除技能**：点 badge 上的 X 即可。技能与 thread 是绑定关系，不影响其他 thread。

## 上传自己的技能

在 `/workspace/skills` 点上传按钮，会弹出：

> 📷 **截图占位**：`images/03-upload-skill-modal.png` — 上传弹窗

两种上传方式：

- **在线编辑器** — 直接在浏览器粘贴 `manifest.yaml` 与 `SKILL.md` 内容，点发布
- **CLI** — 弹窗会显示一条命令，适合从本地仓库批量发布：
  ```
  deerflow skill publish ./path/to/skill-dir
  ```

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

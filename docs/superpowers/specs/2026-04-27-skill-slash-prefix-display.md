# Skill Badge 显示 "/技能名" 前缀 — 需求记录

**记录日期：** 2026-04-27
**来源：** 用户对话需求
**状态：** 待 brainstorm + 写实施计划

---

## 用户诉求原文

> 如果用户选择了一个技能加载到前端会话，前端页面的会话窗口，能否显示 "/技能名称"，当用户删除时，则该技能会话的加载被取消。

## 拆解

1. **加载技能 → 会话窗口显示 "/技能名"**
   - 用户在技能广场点击"加载到会话"或在已有会话中绑定技能
   - 会话窗口（输入框附近）出现一个 badge：`/skill-name`（带斜杠前缀）
   - 这是模仿 Claude Code / GitHub Copilot 的 slash command 视觉风格

2. **删除 badge → 解绑技能**
   - 用户点 badge 上的 × 按钮
   - 该技能从当前 thread 的 `bound_skills` 列表中移除
   - 下一次 agent run 时不再加载该技能

## 当前已有基础

需求已经有 80% 落地（[2026-04-25-skill-mgmt-v2-remaining.md](../plans/2026-04-25-skill-mgmt-v2-remaining.md)）：

- ✅ 后端 `POST/DELETE /api/threads/{tid}/skills` 端点（[backend/app/gateway/routers/thread_skills.py](../../../backend/app/gateway/routers/thread_skills.py)）
- ✅ 前端 `useBoundSkills` / `useBindSkill` / `useUnbindSkill` hooks（[frontend/src/core/skills/hooks.ts](../../../frontend/src/core/skills/hooks.ts)）
- ✅ `SkillBadgeBar` 组件（[frontend/src/components/workspace/skill-badge-bar.tsx](../../../frontend/src/components/workspace/skill-badge-bar.tsx)）已显示 badge + × 按钮 + unbind 调用
- ✅ 已集成到 [chat 页面](../../../frontend/src/app/workspace/chats/[thread_id]/page.tsx) 的 `extraHeader`
- ✅ "加载到会话" 跳转 + auto-bind URL param

**剩余差距（这个需求要做的）：**

1. **视觉**：badge 文本从 `{skill.name}` 改为 `/{skill.name}`
   - 当前：`✨ data-analyst ×`
   - 目标：`✨ /data-analyst ×`（或者 `/ data-analyst`，看视觉效果定）

2. **可选交互改进（用户原文未要求，但属于 slash command 风格的延伸）：**
   - 在输入框直接输入 `/` 时弹出技能选择菜单（slash command palette）—— 这是更完整的 slash command 体验，但当前需求只要求"显示 + 删除"
   - 决定：本期需求**不做** slash palette，只做最小改动；后续如果要做，独立写 spec

## 需要 brainstorm 的边界问题

在写实施计划前，应当跟用户确认：

1. **`/` 前缀的字体/颜色与 name 一致还是区分？**
   - 选项 A：完全一致 `/data-analyst`（最简）
   - 选项 B：`/` 灰色弱化、`name` 加重（更像 slash command）
   - 选项 C：`/` 在前面单独一个图标位（替换当前 `<SparklesIcon>`）
   - 倾向：A（一行代码改动），让用户拍板

2. **Badge 还要保留 `<SparklesIcon>` 闪光图标吗？**
   - 当前是闪光图标 + name + X
   - 如果加 `/`，是否还保留闪光图标？还是把闪光替成更"命令"风的图标（`SlashIcon` 或 `TerminalIcon`）？
   - 倾向：保留闪光，前缀 `/` 紧贴 name 一起显示。视觉测试后再调

3. **是否需要 hover 显示版本号 / 描述？**
   - 当前只显示 name；BoundSkill 数据里有 `version` 和 `bound_at`
   - 需求未涉及，但 hover tooltip 是低成本、有用的增强
   - 倾向：本期**不做**，等用户反馈再加

4. **删除时是否要二次确认？**
   - 当前直接 `unbind`，无确认对话框
   - 用户原文："删除时则技能会话的加载被取消"——隐含语义是直接生效
   - 倾向：本期**不做**二次确认（解绑可重新绑定，不是破坏性操作）

## 实施粗估

如果采用上面的"倾向"方案，改动是**单文件单行**：
- `frontend/src/components/workspace/skill-badge-bar.tsx:26` 把 `{skill.name}` 改成 `/{skill.name}`

如果采用更完整的视觉方案（B/C），需要 1-2 小时，含 e2e 测试。

## 待确认事项

请用户回答上面 4 个 brainstorm 问题（哪怕只回 "都用 A，开始做"），然后我写正式实施计划 → 执行 → commit。

## 后续延伸（不在本期）

如果用户喜欢这个 slash command 风格，可以考虑：
- 输入框 `/` 触发技能 palette（fuzzy 匹配技能名 + 描述）
- 已绑定技能的 `/cmd args` 可以是技能特定的参数（类似 Claude Code 的 slash command）—— 但这需要 skill manifest 声明 `args_schema`
- 这些都是计划 C（[skill 三层可见性 + 运行时验证](../../../.claude/projects/-Users-lydoc-projectscoding-deer-flow/memory/project_skill_agent_i18n.md)）之后再考虑的方向

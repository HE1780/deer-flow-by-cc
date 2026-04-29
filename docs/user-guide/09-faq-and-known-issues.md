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

**理论上可以。** 审计日志（`/admin/audit`）记录的是事件元数据（谁在什么时候做了什么），不直接记录消息内容；但平台管理员有数据库访问权 → 物理上能查任何 thread。如果你处理敏感信息，请确认你信任部署方。

## 已知限制

以下是当前文档基线版本（`cc-main @ 9b362f8a`，2026-04-28）确认存在的不完整功能。提 issue 或贡献修复都欢迎。

### 1. 聊天没有「重新生成」按钮

代码扫描确认前端无 regenerate UI，详见 [02 对话](02-chat-and-threads.md)。**变通**：手动复制问题再发一次。

### 2. 输入框 Connector 面板未实现

代码里有 `/* TODO: Add more connectors here */` 注释。当前用户看不到任何 connector 入口，也没有副作用 —— 只是一个未完成的扩展点。

### 3. OIDC 未在真实 IdP 上端到端验证

代码层支持 OIDC 流程，但当前基线版本没有针对 Keycloak / Okta / Azure AD 等具体 IdP 做过完整冒烟。如你是首次接 IdP，建议：

- 先用邮箱+密码确认账号本身可用
- 把 IdP 配置失败当作配置问题（多半是 redirect_uri、client_id、scope、JWT issuer 校验之一）
- 后端 gateway 日志 `logs/gateway.log` 看 OIDC 错误明细

### 4. LoopDetectionMiddleware warning 路径可能损坏 thread

当 agent 反复调用同一工具达到 warning 阈值（小于 hard_limit）时，中间件会在工具调用链中间注入提醒消息，破坏严格 provider（MiniMax / Anthropic）的消息配对要求，下一轮 LLM 调用可能被拒。表现：API 返回 400 错误。Hard-stop 路径已修复（自动清孤儿 ToolMessage）；warning 路径仍是已知 P1 bug。变通：在此 thread 下开一个新的后续对话。

### 5. 没有自助密码重置

如 Q1 所述。

## 反馈

- 提 issue：仓库 issue 区
- 直接修：欢迎 PR
- 想了解某个功能为什么这么设计：[原始 spec](../superpowers/specs/archive/2026-04-27-user-guide-design.md)

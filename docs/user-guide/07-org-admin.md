# 07 组织管理员手册

> **适用角色：** [组织管理员]（[平台管理员] 也可阅读 —— 你的权限是它的超集）

本章节已通过 `tenant_owner` 账号实操验证（API 全部返回 200，页面全部可访问）。

作为组织管理员（`tenant_owner` 角色），你能管理本组织/租户内的用户、工作区、API token、审计日志与 Org Keys。

## 进入管理后台

访问 `/admin` 会自动跳转到默认管理页：

> 📷 **截图占位**：`images/07-admin-entry.png` — Admin 入口

如果你登录后看到 **403 Forbidden**，说明当前账号没有管理权限，请联系平台管理员授权。

## 个人资料（`/admin/profile`）

- 修改 **display_name**
- 管理你**自己**的个人 API token（与下面的「API Token」组织级 token 不同 —— 这里是仅你能用的）
- 查看活跃 session 列表，可单点撤销某个 session（用于"刚换设备登录，把旧的踢掉"）

## 用户管理（`/admin/users`）

> 📷 **截图占位**：`images/07-users-list.png` — 用户管理列表

- **列表** — 列出本租户全部用户，支持按 email 筛选与翻页
- **邀请** — 点"创建用户"或"邀请"按钮，填写 email + 显示名

用户**详情页**（`/admin/users/{id}`）已上线，支持修改用户在各工作区的角色和重置密码。

## 工作区管理（`/admin/workspaces`）

- **新建** workspace（slug + name）
- **重命名** 已有 workspace
- **删除** workspace（不可恢复）
- **管理成员**：进入 `/admin/workspaces/{id}/members` 增减成员、改角色

> ⚠️ 工作区详情页与成员子页的 UI 完整度仍在打磨。如某些操作按钮无反应，可能尚未接通。

## API Token（`/admin/tokens`）

> 📷 **截图占位**：`images/07-token-create.png` — Token 创建弹窗

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

> 📷 **截图占位**：`images/07-audit-log.png` — 审计日志列表

- **筛选** — action / user_id / resource_type / result / 日期范围（7-90 天窗口）
- **详情** — 点行展开看 actor、resource、payload diff
- **导出 CSV** — 上限 10 万行，超过会返回 413（请缩小日期范围或加更严的筛选）

合规审计、用户行为追溯、可疑操作排查都靠这里。

## 角色（`/admin/roles`）

只读列表，展示当前部署的 5 个预设角色（`platform_admin` / `tenant_owner` / `member` / `viewer` / `workspace_admin`）和它们的默认权限映射。**不能改 —— 仅作参考**。

## 下一步

- 你也是平台管理员 → [08 平台管理员手册](08-platform-admin.md)
- 遇到具体某个功能不工作 → [09 常见问题](09-faq-and-known-issues.md)

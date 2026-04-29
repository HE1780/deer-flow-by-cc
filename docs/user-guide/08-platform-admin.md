# 08 平台管理员手册

> **适用角色：** [平台管理员]

本章节已通过 `platform_admin` 账号实操验证（API 全部返回 200，页面全部可访问）。

作为平台管理员（`platform_admin` 角色），你拥有最高权限：除了组织管理员能做的事，你还能管理租户、审核全平台技能、跨租户查审计。

## 与组织管理员的差异

| 能力 | 组织管理员 | 平台管理员 |
|---|---|---|
| 管理本租户用户/工作区/Token/审计 | ✅ | ✅ |
| 管理多个租户（创建/删除/查统计） | ❌ | ✅ |
| 跨租户审计查询 | ❌ | ✅ |
| 审核全平台技能 | ❌ | ✅ |

## 租户管理（`/admin/tenants`）

> 📷 **截图占位**：`images/08-tenants-list.png` — 租户列表页

- **创建租户** — 填 slug + name。slug 是唯一标识，进库后不可改名
- **列表** — 支持 slug 模糊筛选与翻页
- **改名** — 只改 display name，不改 slug
- **软删除** — 标记 deactivated，租户内数据保留但不可登录。**没有硬删按钮** —— 真要清数据需要后端运维操作

**租户详情页**（`/admin/tenants/{id}`）已上线，支持租户重命名、查看统计（工作区数、成员数）和软删除。Owner 转移等更高级操作仍需通过后端 API。

## 技能审核（`/admin/skills`）

> 📷 **截图占位**：`images/08-skill-review.png` — 技能审核页

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

详见 [09 已知限制](09-faq-and-known-issues.md)。

## 下一步

- 回到 [README](README.md)
- 处理用户反馈的具体问题 → [09 常见问题](09-faq-and-known-issues.md)

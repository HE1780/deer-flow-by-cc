# 前端注册页 设计文档

**日期**：2026-05-01
**作者**：lydoc + Claude（brainstorm）
**目标受众**：执行实现 plan 的 agent / 自己重读时的人
**状态**：设计完成，待 review

---

## 1. 目标

为 deer-flow 前端补一条公开注册入口 `/register`，对接 P1 已 ship 的后端
`POST /api/auth/register`（注册码自助注册流程，详见
`docs/superpowers/specs/archive/2026-04-29-registration-code-design.md`）。

在此之前，注册码流程只有后端，admin 用 curl/Postman 验证；本期把前端这一步补齐
后，整条 onboarding 链路（admin 生成码 → 把链接发给候选人 → 候选人在浏览器里完成
注册并自动登录）首次端到端可用。

## 2. 范围（Scope）

### 包含

- 新页面 `frontend/src/app/(public)/register/page.tsx`，URL 形态
  `/register?code=xxxxxxxx...`
- 一个 `identityApi.registerWithCode()` 方法 + `RegisterWithCodePayload`
  类型（同时让 admin/UI 后续场景能复用同一份契约）
- 错误状态分级展示：字段内联 / 顶部 banner（5xx 与 404/410 共用 banner，详见 §3）
- vitest 单元测试（8 个用例）
- Playwright E2E 一条 happy path

### 不包含（明确边界）

- **i18n 化**：跟随 `/login` 现状，英文硬编码。`/login` 当前未走 i18n 体系，本期
  不引入新的"双语规范不一致"。若未来给 `/login` 国际化，本页一起做，单独立项。
- **邀请人/租户落地页**：后端没有公开"用码查租户元数据"端点；不引入。链接里只
  有 code，页面上只显示通用 onboarding 文案。
- **密码强度可视化**：当前后端只校验长度 ≥ 8，前端引入 zxcvbn 等无收益。
- **邮箱验证流程 / 二次确认 / 双因素**：注册码本身就是一次性 entropy ≥ 256 bit
  的邀请凭证，等同于"已被信任地分发"，不再叠加邮箱 verify。
- **已登录用户访问 `/register?code=xxx` 时自动登出**：走"提示+手动登出"路径
  （见 §5），不擅自销毁 session。
- **OIDC 入口的注册路径**：OIDC 用户在首次登录时由 backend `upsert_oidc_user`
  自动建用户，不需要前端注册页。

## 3. 用户路径

```
主路径（happy）：
  admin 创建码 → 把 https://app/register?code=xxxxxxxx 发给候选人
  → 候选人浏览器打开 → 页面渲染 email + password (+ display_name 可选) 表单
  → 用户填写并提交 → POST /api/auth/register
  → 201 + Set-Cookie: deerflow_session
  → router.push("/") → workspace 主页（已认证态）

异常分支：
  - URL 缺 code         → red banner "Invalid invitation link…"，表单禁用
  - 已登录访问           → 提示 "You are signed in as X"，提供 sign-out 按钮
  - 422 password 太短   → 密码框下方红字 "Password must be at least 8 characters"
  - 422 email 格式错    → 邮箱框下方红字 "Please enter a valid email address"
  - 404 invalid code   → 顶部 banner "This invitation link is invalid or has been used"
  - 410 expired        → 顶部 banner "This invitation link has expired. Please request a new one."
  - 409 email 已注册   → 邮箱框下方红字 "An account with this email already exists"
  - 5xx / 网络错       → 顶部 banner "Registration failed (NNN), please try again later"
                       （注：sonner Toaster 在 root layout 未挂载，(public) 路由组没有 toast 容器；
                        5xx 跟 404/410 共用同一个 banner 组件，零额外依赖）
```

## 4. 文件清单

| 文件 | 状态 | 说明 |
|---|---|---|
| `frontend/src/app/(public)/register/page.tsx` | 新增 | 页面 + 状态机 + 表单组件 |
| `frontend/src/core/identity/api.ts` | 修改 | 新增 `registerWithCode()` |
| `frontend/src/core/identity/types.ts` | 修改 | 新增 `RegisterWithCodePayload` / `RegisterWithCodeResponse` |
| `frontend/tests/unit/app/register-page.test.tsx` | 新增 | 8 个 vitest 用例 |
| `frontend/tests/e2e/identity/A1-register.spec.ts` | 新增 | 1 条 Playwright E2E 主路径 |

## 5. 状态机

页面顶层组件 `RegisterPage` 派生出五个互斥的渲染状态：

```
phase ∈ {
  "loading_me",         // 初始：等 /api/me 回来
  "already_logged_in",  // /api/me 返回认证用户 → 显示提示 + sign-out
  "no_code",            // URL 缺 ?code= → 红 banner，表单禁用
  "ready",              // 表单可交互
  "submitting",         // 表单提交中（按钮 disabled）
}
```

派生规则：

```ts
if (meQuery.isLoading)        return "loading_me";
if (meQuery.data?.user_id)    return "already_logged_in";
if (!code)                    return "no_code";
if (submitting)               return "submitting";
return "ready";
```

为什么先查 `/api/me` 再决定渲染：避免已登录用户因为忘记登出而误用别人发的邀请
链接，提交后被 409（email 已注册）反弹——这是真实可能的运营场景，提前拦截。

## 6. API 契约

```ts
// types.ts 新增
export interface RegisterWithCodePayload {
  code: string;
  email: string;
  password: string;
  display_name?: string;  // 可选；后端缺省取 email 前缀
}

export interface RegisterWithCodeResponse {
  status: "ok";
  email: string;
}

// api.ts 新增 — 但不通过 identityFetch 调用（见下）
```

**为什么 `/register` 提交不走 `identityFetch`**：

`identityFetch` 在收到 401 时会触发 refresh-then-retry 单飞机制；但 `/register`
端点是无 session 状态的公开入口，不应触发 refresh。同时 422/404/409/410 在
`identityFetch` 里被统一打成 `kind: "network"` + raw text message，调用方还要
二次 JSON.parse 拿 `detail`，反而绕。

跟随 `/login` 同模式，`/register` 表单的提交直接用原生 `fetch()`，自己 parse 返回
体。`identityApi.registerWithCode()` 仍然导出供未来非表单场景调用。

## 7. 错误分类逻辑

后端 `/api/auth/register` 返回的 `detail` 字段有两种形态（已写入后端
CLAUDE.md）：

- 字符串：handler 自己 raise `HTTPException(..., "string")`
- 数组：Pydantic schema 校验失败

前端要兼容这两种：

```ts
type SubmitOutcome =
  | { ok: true }
  | { ok: false; kind: "field"; field: "email" | "password"; msg: string }
  | { ok: false; kind: "banner"; msg: string };

async function submitRegister(payload: RegisterWithCodePayload): Promise<SubmitOutcome> {
  const res = await fetch("/api/auth/register", {
    method: "POST",
    credentials: "include",
    headers: { "content-type": "application/json", accept: "application/json" },
    body: JSON.stringify(payload),
  });
  if (res.ok) return { ok: true };

  const body = await res.json().catch(() => ({}));
  const detail = (body as { detail?: unknown }).detail;
  const detailStr = typeof detail === "string" ? detail.toLowerCase() : "";

  if (res.status === 422) {
    if (detailStr.includes("password")) {
      return { ok: false, kind: "field", field: "password",
               msg: "Password must be at least 8 characters" };
    }
    if (detailStr.includes("email")) {
      return { ok: false, kind: "field", field: "email",
               msg: "Please enter a valid email address" };
    }
    // Pydantic 数组兜底（极少见，schema 必填字段缺失才会触发）
    return { ok: false, kind: "field", field: "email", msg: "Invalid input" };
  }
  if (res.status === 404) {
    return { ok: false, kind: "banner",
             msg: "This invitation link is invalid or has been used" };
  }
  if (res.status === 410) {
    return { ok: false, kind: "banner",
             msg: "This invitation link has expired. Please request a new one." };
  }
  if (res.status === 409) {
    return { ok: false, kind: "field", field: "email",
             msg: "An account with this email already exists" };
  }
  return { ok: false, kind: "banner",
           msg: `Registration failed (${res.status}), please try again later` };
}
```

注：404 实际覆盖三种后端语义（码不存在 / accepted / revoked），前端不区分；用户层面文案统一为
"invalid or has been used"，与后端 CLAUDE.md 描述对齐。

## 8. 表单 UX 细节

- email 框：`type="email"` + `autoComplete="email"` + `required`
- password 框：`type="password"` 或 `text`（受 `showPassword` 切换控制）+
  `autoComplete="new-password"` + `required`
- 显示/隐藏切换：右上角小眼睛按钮（行业标配）
- display_name 框：`required={false}`，placeholder 提示"defaults to email
  prefix"
- 提交按钮：`phase=submitting` 时 disabled 并文案换为 "Creating account…"
- enter 键：单字段 enter 即提交（`<form onSubmit>`）；submitting 期间因
  disabled 不会重复触发
- 复用 `/login` 的 Tailwind 样式 token（`rounded-md border border-input bg-background ...`）

## 9. 组件结构（伪代码骨架）

```tsx
"use client";

export default function RegisterPage() {
  const params = useSearchParams();
  const router = useRouter();
  const code = params.get("code") ?? "";

  const meQuery = useQuery({
    queryKey: identityKeys.me(),
    queryFn: identityApi.me,
    retry: false,  // 401 是正常态，不要重试
  });

  if (meQuery.isLoading) return <LoadingShell />;
  if (meQuery.data?.user_id) return <AlreadyLoggedInBlock me={meQuery.data} />;
  if (!code) return <NoCodeBlock />;

  return <RegisterForm code={code} onSuccess={() => router.push("/")} />;
}

function RegisterForm({ code, onSuccess }: { code: string; onSuccess: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [bannerError, setBannerError] = useState<string | null>(null);
  const [emailError, setEmailError] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setBannerError(null); setEmailError(null); setPasswordError(null);
    const outcome = await submitRegister({
      code, email, password,
      display_name: displayName.trim() || undefined,
    });
    setSubmitting(false);
    if (outcome.ok) { onSuccess(); return; }
    if (outcome.kind === "banner") setBannerError(outcome.msg);
    else if (outcome.kind === "field" && outcome.field === "email") setEmailError(outcome.msg);
    else if (outcome.kind === "field" && outcome.field === "password") setPasswordError(outcome.msg);
  }

  return ( /* 表单 JSX，复用 /login 样式 */ );
}
```

## 10. 测试矩阵

### 10.1 单元（vitest, `tests/unit/app/register-page.test.tsx`）

1. **loading state** — `useQuery` pending 时渲染 loading 占位
2. **already-logged-in** — `me` 返回 `{ user_id, email }` → 显示提示文案 + sign-out 按钮
3. **no-code** — URL 无 `?code=` → red banner，表单不渲染
4. **happy path** — 填表 → fetch mock 返回 201 → `router.push("/")` 被调用
5. **422 password 错** — fetch mock 返回 `422 {"detail":"password must be at least 8 characters"}` → 密码框下出现错误文案，banner 不出现
6. **404 invalid code** — fetch mock 返回 `404 {"detail":"invalid registration code"}` → 顶部 banner 出现
7. **409 email 重复** — fetch mock 返回 `409 {"detail":"email already registered"}` → email 框下出错
8. **show/hide password** — 点击眼睛按钮，password input `type` 由 `password` 切到 `text`

### 10.2 E2E（Playwright, `tests/e2e/identity/A1-register.spec.ts`）

一条 happy path：
- mock `/api/me` 401（未登录态）
- mock `/api/auth/providers` 返回空 providers（占位，避免页面别处出 query 错）
- mock `POST /api/auth/register` 返回 201 + 模拟 Set-Cookie
- 访问 `/register?code=test12345`
- 填邮箱、密码、点击 submit
- 断言 `page.url()` 变成根路径 `/`（mock 根路径不验内容）

## 11. 风险与回滚

| 风险 | 缓解 |
|---|---|
| 已登录用户被 409 反弹 | §5 `already_logged_in` 分支提前拦截，根本到不了表单 |
| 表单 enter 重复提交 | `phase=submitting` 期间按钮 disabled |
| 422 detail 两种形态被误判 | §7 字符串/数组双兼容，数组走 email 字段兜底 |
| 后端将来改默认跳转目标 | 前端硬编码 `router.push("/")`，需文档同步；将来改 spec 同时改这里 |
| `/login` 改 i18n 后本页留英文 | i18n 升级时本页一起做，单独立项 |

回滚：删 5 个文件 + revert types.ts/api.ts 两处新增即可，零数据/契约影响。

## 12. 代码质量门槛

- `pnpm check`（lint + typecheck）必须绿
- 8 vitest + 1 playwright 必须绿
- 保持现有 `/login` 页面样式 token 一致（`rounded-md border border-input bg-background ...`）

## 13. 与已有规范的对齐

- 按 `frontend/CLAUDE.md`：仅在 `feat/*` 分支改代码，最小可用 + 测试通过即合并回 `cc-main` 并 push，不走 PR
- 按 `~/.claude/CLAUDE.md`：所有 spec/plan 放项目级 `docs/`，不放全局
- 按 `memo/memo.md`：本期完成后归档本 spec 到 `docs/superpowers/specs/archive/`

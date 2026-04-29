# DeerFlow Frontend

Like the original DeerFlow 1.0, we would love to give the community a minimalistic and easy-to-use web interface with a more modern and flexible architecture.

## Tech Stack

- **Framework**: [Next.js 16](https://nextjs.org/) with [App Router](https://nextjs.org/docs/app)
- **UI**: [React 19](https://react.dev/), [Tailwind CSS 4](https://tailwindcss.com/), [Shadcn UI](https://ui.shadcn.com/), [MagicUI](https://magicui.design/) and [React Bits](https://reactbits.dev/)
- **AI Integration**: [LangGraph SDK](https://www.npmjs.com/package/@langchain/langgraph-sdk) and [Vercel AI Elements](https://vercel.com/ai-sdk/ai-elements)

## Quick Start

### Prerequisites

- Node.js 22+
- pnpm 10.26.2+

### Installation

```bash
# Install dependencies
pnpm install

# Copy environment variables
cp .env.example .env
# Edit .env with your configuration
```

### Development

```bash
# Start development server
pnpm dev

# The app will be available at http://localhost:3110
```

### Build & Test

```bash
# Type check
pnpm typecheck

# Check formatting
pnpm format

# Apply formatting
pnpm format:write

# Lint
pnpm lint

# Run unit tests
pnpm test

# One-time setup: install Playwright Chromium browser
pnpm exec playwright install chromium

# Run E2E tests (builds and starts production server automatically)
pnpm test:e2e

# Build for production
pnpm build

# Start production server
pnpm start
```

## Site Map

```
├── /                              # Landing page
├── /chats                         # Chat list
├── /chats/new                     # New chat page
├── /chats/[thread_id]             # A specific chat page
│
├── /login                         # OIDC provider buttons (M7 A1)
├── /logout                        # Sign-out bridge
├── /auth/oidc/[provider]/callback # OIDC return target
├── /forbidden                     # 403 page rendered by RequirePermission
│
└── /admin/...                     # Identity admin (gated by middleware.ts)
    ├── profile                    # Basic + my tokens + my sessions tabs
    ├── tenants                    # platform_admin only — list & detail
    ├── users                      # tenant_owner — list, filter, create
    ├── roles                      # 5 built-in roles, read-only
    ├── workspaces                 # list + member management
    │   └── [id]/members           # add / remove / change role
    ├── tokens                     # tenant tokens — issue & revoke
    └── audit                      # filter, drawer, CSV export
```

The `/admin/*` routes ship behind `ENABLE_IDENTITY=true` on the backend.
With the flag off, the UI middleware still works (it short-circuits when
no `deerflow_session` cookie is present), but the backend returns 404
on `/api/me` so users land on `/login` and stay there. See
[../docs/UPGRADE_v2.md](../docs/UPGRADE_v2.md) for the rollout path.

## Configuration

### Environment Variables

Key environment variables (see `.env.example` for full list):

```bash
# Backend API URLs (optional, uses nginx proxy by default)
NEXT_PUBLIC_BACKEND_BASE_URL="http://localhost:8100"
# LangGraph API URLs (optional, uses nginx proxy by default)
NEXT_PUBLIC_LANGGRAPH_BASE_URL="http://localhost:2024"
```

## Project Structure

```
tests/
├── e2e/                    # E2E tests (Playwright, Chromium, mocked backend)
└── unit/                   # Unit tests (mirrors src/ layout)
src/
├── app/                    # Next.js App Router pages
│   ├── api/                # API routes
│   ├── workspace/          # Main workspace pages
│   └── mock/               # Mock/demo pages
├── components/             # React components
│   ├── ui/                 # Reusable UI components
│   ├── workspace/          # Workspace-specific components
│   ├── landing/            # Landing page components
│   └── ai-elements/        # AI-related UI elements
├── core/                   # Core business logic
│   ├── api/                # API client & data fetching
│   ├── artifacts/          # Artifact management
│   ├── config/             # App configuration
│   ├── i18n/               # Internationalization (en-US, zh-CN)
│   ├── identity/           # /api/me, /api/auth, /api/admin wrappers (M7)
│   │   ├── api.ts          # Typed REST client wrappers
│   │   ├── components/     # AdminSidebar, TenantSwitcher, RequirePermission, …
│   │   ├── fetcher.ts      # Session-expiry aware fetch helper
│   │   ├── hooks.ts        # useIdentity, useHasPermission, list+mutation hooks
│   │   ├── query-keys.ts   # TanStack Query keys
│   │   └── types.ts        # Backend response shapes mirrored 1:1
│   ├── mcp/                # MCP integration
│   ├── messages/           # Message handling
│   ├── models/             # Data models & types
│   ├── settings/           # User settings
│   ├── skills/             # Skills system
│   ├── threads/            # Thread management
│   ├── todos/              # Todo system
│   └── utils/              # Utility functions
├── hooks/                  # Custom React hooks
├── lib/                    # Shared libraries & utilities
├── server/                 # Server-side code
│   └── better-auth/        # Authentication setup and session helpers
└── styles/                 # Global styles
```

## Scripts

| Command             | Description                             |
| ------------------- | --------------------------------------- |
| `pnpm dev`          | Start development server with Turbopack |
| `pnpm build`        | Build for production                    |
| `pnpm start`        | Start production server                 |
| `pnpm test`         | Run unit tests with Vitest              |
| `pnpm test:e2e`     | Run E2E tests with Playwright           |
| `pnpm format`       | Check formatting with Prettier          |
| `pnpm format:write` | Apply formatting with Prettier          |
| `pnpm lint`         | Run ESLint                              |
| `pnpm lint:fix`     | Fix ESLint issues                       |
| `pnpm typecheck`    | Run TypeScript type checking            |
| `pnpm check`        | Run both lint and typecheck             |

## Development Notes

- Uses pnpm workspaces (see `packageManager` in package.json)
- Turbopack enabled by default in development for faster builds
- Environment validation can be skipped with `SKIP_ENV_VALIDATION=1` (useful for Docker)
- Backend API URLs are optional; nginx proxy is used by default in development

## Identity admin surface (M7 A)

When the backend runs with `ENABLE_IDENTITY=true`, the frontend exposes an
admin shell under `/admin/*`. Routing rules:

- **`middleware.ts`** redirects every `/admin/*` request without a
  `deerflow_session` cookie to `/login?next=…`.
- **`<RequirePermission>`** wraps each admin page body and renders the
  `/forbidden` UI if the caller lacks the page's required permission tag.
- **Sidebar** items hide themselves entirely when their `requires` tag
  isn't on `useIdentity().permissions` (or, for `Tenants`, when the caller
  isn't a `platform_admin`).

The identity client (`src/core/identity/`) speaks directly to the
backend routes documented in
[../docs/superpowers/specs/archive/2026-04-21-deerflow-identity-foundation-design.md](../docs/superpowers/specs/archive/2026-04-21-deerflow-identity-foundation-design.md):

| Page                      | Backend routes consumed                                                |
|---------------------------|------------------------------------------------------------------------|
| `/admin/profile`          | `/api/me`, `/api/me/tokens`, `/api/me/sessions`                        |
| `/admin/tenants`          | `/api/admin/tenants[/:id]`                                             |
| `/admin/users`            | `GET/POST /api/tenants/{tid}/users`                                    |
| `/admin/workspaces/[id]/members` | `GET/POST/PATCH/DELETE /api/tenants/{tid}/workspaces/{wid}/members` |
| `/admin/tokens`           | `GET/POST /api/tenants/{tid}/tokens`, `DELETE …/{id}`                  |
| `/admin/audit`            | `GET /api/tenants/{tid}/audit{,/export}`                               |
| `/admin/roles`            | `/api/roles`                                                           |

E2E coverage lives at `tests/e2e/identity/` with shared fixtures in
`fixtures/mock-backend.ts` (`mockIdentity`, `mockAdmin`, `mockWrites`).
Each spec mocks the backend through `page.route()` so no live PG/Redis
is needed — run with `pnpm test:e2e --grep identity`.

## License

MIT License. See [LICENSE](../LICENSE) for details.

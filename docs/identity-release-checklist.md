# Identity v2 Release Checklist

> 📌 **2026-04-29 状态**：本清单 38 项 `- [ ]` 全部未勾选 — 这不是代码 bug，是部署/发布演练缺位。归类汇总见 [OPEN_ISSUES.md "验收 gap 清单"](./OPEN_ISSUES.md#验收-gap-清单38-项手工演练)。
>
> 进入下一期发布周期时，建议把这 38 项拆成"必跑"（阻塞）/"强烈建议"两组，参见 OPEN_ISSUES 文末讨论方向。

---

Manual runbook that must be exercised on staging once before a v2
production rollout. Spec §11.7.

This checklist is intentionally hands-on — the automated suite proves
*correctness* but a handful of integrations (real IdPs, real data
volumes, real deploy platforms) can only be proven by doing.

Every item has a GO/NO-GO outcome. If any item fails, STOP the release
and file a remediation task against the relevant milestone; do not
carry a known failure into prod.

---

## Pre-flight

- [ ] Target branch merged to `main` and CI is green across all identity
  jobs.
- [ ] Test coverage for `app/gateway/identity/*` ≥ 80% (check the latest
  coverage report).
- [ ] `ENABLE_IDENTITY=false` regression guard
  (`tests/identity/test_feature_flag_offline.py`) passes locally.
- [ ] `config/identity.yaml.example` includes every provider you intend
  to document.
- [ ] `docs/UPGRADE_v2.md` and `CHANGELOG.md` reflect the final shipping
  feature set (no TODO markers).

## IdP smoke tests

Each provider must be reachable with a real tenant-admin-owned test
account. Run each test **end-to-end** — not with a mock.

- [ ] **Okta** — full login round-trip. Expected: `/api/me` returns the
  user record, session cookie is set, `/api/auth/logout` clears it.
- [ ] **Azure AD** — same.
- [ ] **Keycloak** — same; also verify that a group claim mapping
  creates the expected workspace membership on first login.

## Migration rehearsal

Run against a staging copy of production with **at least 1 000 threads**.
Use a real `$DEER_FLOW_HOME` snapshot, not synthetic data.

- [ ] `make identity-migrate-dry` → inspect the report. Counts match
  manual `find` of the source trees.
- [ ] `make identity-migrate-apply` → report shows `moved: N, failed: 0`.
- [ ] Re-run `make identity-migrate-apply` → report shows
  `moved: 0, skipped: N, failed: 0` (idempotency).
- [ ] Spot-check five random threads: read the file from the new path,
  confirm the forwarder symlink at the old path resolves, byte-count
  parity holds.
- [ ] `make identity-migrate-rollback REPORT=<path>` → source tree is
  back, targets are gone.

## Multi-replica bootstrap

Requires a two-replica gateway deploy (Kubernetes or two local processes
with the same PG + Redis).

- [ ] Start both replicas simultaneously with `ENABLE_IDENTITY=true` and
  no pre-existing `identity` rows.
- [ ] Both replicas should reach `Listening on ...` within 10 s of each
  other. Exactly one logs "identity bootstrap complete"; the other logs
  nothing unusual (the seed sees everything already there).
- [ ] Confirm `pg_locks` is empty after startup (the advisory lock is
  released).

## Deployment drills

- [ ] **docker-compose dev**: `docker compose up` with `ENABLE_IDENTITY=true`
  — services healthy, `/api/auth/oidc/<provider>/login` resolves.
- [ ] **docker-compose prod**: `./scripts/deploy.sh` with identity on — same.
- [ ] **K8s (production-like)**: two gateway replicas behind the ingress
  pass liveness + readiness probes and serve `/metrics`.

## Rollback drill

- [ ] On staging with identity on, set `ENABLE_IDENTITY=false` and
  restart the gateway.
- [ ] `/api/*` legacy routes respond as they did in v1.
- [ ] A thread created while identity was on is still openable through
  the legacy path (the forwarder symlink handles the redirection).
- [ ] `/api/auth/*` is 404; `/metrics` is 404.
- [ ] Flip back to `ENABLE_IDENTITY=true` → everything resumes.

## Audit plane

- [ ] `GET /api/tenants/{tid}/audit` returns an empty page (no data on
  a fresh tenant) and a populated page after a few logins.
- [ ] `GET /api/tenants/{tid}/audit/export?...` streams a CSV that opens
  cleanly in a spreadsheet.
- [ ] Kill the PG connection mid-traffic: the gateway keeps serving,
  `$DEER_FLOW_HOME/_audit/fallback.jsonl` fills with critical events.
  Restore PG: on the next scrape, `audit_write_failures_total` stops
  growing and `audit_queue_depth` drains.

## Metrics

- [ ] `curl http://<gateway>/metrics` returns the 5 identity metrics
  with sane values (no `NaN`, counters are monotonic between scrapes).
- [ ] Prometheus scrape job green; the sample alerts in
  `docs/identity-alerting.md` load without errors
  (`promtool check rules`).

## Known gaps to flag in the release notes

Previously open items — now resolved (2026-04-25):

- [x] Admin UI (M7 Part A) — all 14 admin routes shipped; Skills Hub,
  password login, workspace auth gate all landed.
- [x] CI identity e2e smoke — `identity-e2e-smoke` GH Actions workflow
  committed; `issue_bootstrap_token.py` fixed to register Redis session.

Remaining open items requiring manual staging verification:

- [ ] Real Okta / Azure AD / Keycloak login (IdP smoke tests above).
- [ ] Migration rehearsal on 1 000+ real threads.
- [ ] Multi-replica bootstrap drill.
- [ ] Rollback drill (flag on → off → legacy threads).
- [ ] Identity test coverage ≥ 80% (`pytest --cov`).

## Sign-offs

- [ ] Backend lead
- [ ] SRE / Ops
- [ ] Security review (at least auth + audit paths)
- [ ] Release engineer files the GA-cut tag and merges CHANGELOG.md

---

### Troubleshooting bookmarks

* **Login failure spike** → `docs/identity-alerting.md` →
  `DeerFlowLoginFailureSpike` runbook.
* **Audit backlog** → `docs/identity-alerting.md` →
  `DeerFlowAuditQueueBackup` runbook.
* **Full audit subsystem reference** → `backend/CLAUDE.md` →
  "Audit pipeline (M6)".
* **Storage layout & path guards** → `backend/CLAUDE.md` →
  "Storage (M4)".

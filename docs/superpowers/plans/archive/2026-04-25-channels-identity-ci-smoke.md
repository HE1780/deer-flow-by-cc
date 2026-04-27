# Channels Identity TODO + CI E2E Identity Smoke — Implementation Plan

> **实施状态（2026-04-27 复核）：** ✅ 全部已落地。
> - Part 1 (channels identity): commits `ab59a037` (ChannelStore 持久化 tenant/workspace) + `e385586a` (`_resolve_channel_identity` 辅助) + `85266c69` (`resolve_virtual_path` 串通) — `backend/app/channels/store.py:88-141` `manager.py:573-736`，测试类 `TestChannelManagerIdentity` 已添加 (`backend/tests/test_channels.py:2480`)。
> - Part 2 (CI smoke): `backend/scripts/ci/issue_bootstrap_token.py` + `identity_smoke_test.py` + `.github/workflows/identity-e2e-smoke.yml` 全部已创建。
> - 文件原计划用任务级 `### Step` 标题而非 `- [ ]` checkbox，所以无需勾选；以本横幅记录实施状态即可。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thread tenant/workspace identity through the IM channels pipeline (Part 1) and add a CI workflow that proves `ENABLE_IDENTITY=true` Gateway boots, authenticates, and audits end-to-end (Part 2).

**Architecture:** Part 1 reads `tenant_id`/`workspace_id` from `channel_sessions` config, persists them into `ChannelStore`, and passes them into `paths.resolve_virtual_path` — preserving legacy behavior when the flag is off. Part 2 boots Gateway with PG+Redis services, mints a bootstrap-admin JWT directly (no OIDC), exchanges it for an API token, and hits a four-call smoke assertion list.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, pytest, httpx, uv, GitHub Actions, PostgreSQL 16, Redis 7, python-jose (RS256), existing `app.gateway.identity.*` subsystem.

**Spec:** `docs/superpowers/specs/2026-04-24-channels-identity-ci-smoke-design.md`

**Cross-plan invariants enforced:**
1. `ENABLE_IDENTITY=false` ⇒ zero behavior change (Part 1 tests cover this; Part 2 only runs with the flag on).
2. Harness boundary — no `app.*` imports from `packages/harness/deerflow/`. Part 1 only touches `app.channels.*`; Part 2 only touches `app.gateway.identity.*` + scripts.
3. Audit log immutability (M6 GRANTs) unchanged.
4. Path derived from identity — Part 1 routes through `Paths.resolve_virtual_path(..., tenant_id=..., workspace_id=...)` which already enforces this.
5. Tool permission whitelist (M5) unchanged.

---

## File Structure

**Part 1 — Channels Identity TODO (3 files touched)**

- Modify: `backend/app/channels/store.py` — add `tenant_id`/`workspace_id` persistence, `get_thread_mapping()` method.
- Modify: `backend/app/channels/manager.py` — add `_resolve_channel_identity()`, thread the IDs through `_create_thread` → store, `_handle_chat` / streaming path → `_resolve_attachments` → `paths.resolve_virtual_path`. Remove `TODO(m5-identity)` block.
- Modify: `backend/tests/test_channels.py` — new `TestChannelManagerIdentity` class (4 tests) + one new test in `TestChannelStore`.

**Part 2 — CI E2E Identity Smoke (3 new files)**

- Create: `backend/scripts/ci/__init__.py` — empty, marks directory as a package (import convenience).
- Create: `backend/scripts/ci/issue_bootstrap_token.py` — mints a 60s RS256 JWT for the bootstrap admin email.
- Create: `backend/scripts/ci/identity_smoke_test.py` — single-file pytest-less smoke runner using httpx.
- Create: `.github/workflows/identity-e2e-smoke.yml` — new workflow (postgres+redis services, bootstrap, start gateway, run smoke).

Note: spec says `scripts/ci/...` without prefix. Anchoring them under `backend/scripts/ci/` matches how `backend/scripts/` already holds backend-specific helpers like `migrate_to_multitenant.py`, and makes `PYTHONPATH=. uv run python scripts/ci/...` work from `backend/`.

---

# Part 1 — Channels Identity TODO

## Task 1: `ChannelStore` persists `tenant_id`/`workspace_id`

**Files:**
- Modify: `backend/app/channels/store.py` (method `set_thread_id`, add `get_thread_mapping`)
- Test: `backend/tests/test_channels.py` (extend `TestChannelStore`)

### Step 1.1: Write the failing test

Append to `TestChannelStore` in `backend/tests/test_channels.py`:

```python
    def test_set_with_identity_persists_tenant_workspace(self, store):
        store.set_thread_id(
            "slack",
            "ch1",
            "thread-abc",
            user_id="u1",
            tenant_id=7,
            workspace_id=3,
        )
        mapping = store.get_thread_mapping("slack", "ch1")
        assert mapping is not None
        assert mapping["thread_id"] == "thread-abc"
        assert mapping["tenant_id"] == 7
        assert mapping["workspace_id"] == 3

    def test_get_thread_mapping_missing_returns_none(self, store):
        assert store.get_thread_mapping("slack", "nonexistent") is None

    def test_set_without_identity_stores_none(self, store):
        store.set_thread_id("slack", "ch1", "thread-abc", user_id="u1")
        mapping = store.get_thread_mapping("slack", "ch1")
        assert mapping is not None
        assert mapping["tenant_id"] is None
        assert mapping["workspace_id"] is None

    def test_get_thread_id_still_works_after_identity_persist(self, store):
        # Back-compat: the legacy getter must keep returning the thread_id only.
        store.set_thread_id("slack", "ch1", "t1", tenant_id=7, workspace_id=3)
        assert store.get_thread_id("slack", "ch1") == "t1"

    def test_legacy_entry_without_identity_keys_reads_as_none(self, tmp_path):
        # Simulate a store.json written by the pre-M7-followup version.
        path = tmp_path / "store.json"
        legacy = {
            "slack:ch1": {
                "thread_id": "thread-legacy",
                "user_id": "u1",
                "created_at": 1700000000.0,
                "updated_at": 1700000000.0,
            }
        }
        path.write_text(json.dumps(legacy), encoding="utf-8")
        store = ChannelStore(path=path)
        mapping = store.get_thread_mapping("slack", "ch1")
        assert mapping is not None
        assert mapping["thread_id"] == "thread-legacy"
        assert mapping.get("tenant_id") is None
        assert mapping.get("workspace_id") is None
```

### Step 1.2: Run tests to verify they fail

Run:
```
cd /Users/lydoc/projectscoding/deer-flow/backend && PYTHONPATH=. uv run pytest tests/test_channels.py::TestChannelStore -v
```
Expected: FAIL — `TypeError: set_thread_id() got an unexpected keyword argument 'tenant_id'` (and `AttributeError: 'ChannelStore' object has no attribute 'get_thread_mapping'`).

### Step 1.3: Implement the changes

Edit `backend/app/channels/store.py`. Change the `set_thread_id` signature and body, and add `get_thread_mapping`. Also update the class docstring to reflect the new fields.

Replace the `set_thread_id` method (around line 87-107) with:

```python
    def set_thread_id(
        self,
        channel_name: str,
        chat_id: str,
        thread_id: str,
        *,
        topic_id: str | None = None,
        user_id: str = "",
        tenant_id: int | None = None,
        workspace_id: int | None = None,
    ) -> None:
        """Create or update the mapping for an IM conversation/topic.

        ``tenant_id`` / ``workspace_id`` are optional and default to ``None`` —
        when ``ENABLE_IDENTITY=false`` (or the channel config omits them) the
        legacy single-tenant mapping shape is preserved.
        """
        with self._lock:
            key = self._key(channel_name, chat_id, topic_id)
            now = time.time()
            existing = self._data.get(key)
            self._data[key] = {
                "thread_id": thread_id,
                "user_id": user_id,
                "tenant_id": tenant_id,
                "workspace_id": workspace_id,
                "created_at": existing["created_at"] if existing else now,
                "updated_at": now,
            }
            self._save()
```

Add `get_thread_mapping` right above `get_thread_id` (around line 80):

```python
    def get_thread_mapping(
        self,
        channel_name: str,
        chat_id: str,
        *,
        topic_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Return the full stored entry (incl. ``tenant_id``/``workspace_id``).

        Missing ``tenant_id`` / ``workspace_id`` keys (from entries written by
        earlier versions) are read as ``None`` — callers rely on ``.get()``
        semantics so pre-M7-followup ``store.json`` files remain readable.
        """
        entry = self._data.get(self._key(channel_name, chat_id, topic_id))
        if entry is None:
            return None
        return {
            **entry,
            "tenant_id": entry.get("tenant_id"),
            "workspace_id": entry.get("workspace_id"),
        }
```

Also update the class docstring (around line 20-30) to list `tenant_id`/`workspace_id` in the sample layout:

```python
    """JSON-file-backed store that maps IM conversations to DeerFlow threads.

    Data layout (on disk)::

        {
            "<channel_name>:<chat_id>": {
                "thread_id": "<uuid>",
                "user_id": "<platform_user>",
                "tenant_id": 1,
                "workspace_id": 2,
                "created_at": 1700000000.0,
                "updated_at": 1700000000.0
            },
            ...
        }

    ``tenant_id`` / ``workspace_id`` are nullable; when ``ENABLE_IDENTITY`` is
    off (or the channel config omits them) they are stored as ``null`` and
    downstream resolvers fall back to the legacy flat path.

    The store is intentionally simple — a single JSON file that is atomically
    rewritten on every mutation. For production workloads with high concurrency,
    this can be swapped for a proper database backend.
    """
```

### Step 1.4: Run the tests to verify they pass

Run:
```
cd /Users/lydoc/projectscoding/deer-flow/backend && PYTHONPATH=. uv run pytest tests/test_channels.py::TestChannelStore -v
```
Expected: PASS (all existing + 5 new tests green).

### Step 1.5: Commit

```bash
cd /Users/lydoc/projectscoding/deer-flow && git add backend/app/channels/store.py backend/tests/test_channels.py
git commit -m "feat(channels): persist tenant_id/workspace_id in ChannelStore (M7A followup)"
```

---

## Task 2: `ChannelManager._resolve_channel_identity` helper

**Files:**
- Modify: `backend/app/channels/manager.py` (add helper after `_resolve_session_layer`)
- Test: `backend/tests/test_channels.py` (new `TestChannelManagerIdentity` class, first two tests)

### Step 2.1: Write the failing tests

Add a new class at the end of `backend/tests/test_channels.py`, right after `TestChannelService` (search for `class TestChannelService:` and append after its methods — put the new class between `TestChannelService` and any module-level trailer, or at end of file):

```python
# ---------------------------------------------------------------------------
# ChannelManager identity-threading tests (M7A followup)
# ---------------------------------------------------------------------------


class TestChannelManagerIdentity:
    def test_resolve_channel_identity_flag_off(self, monkeypatch):
        """ENABLE_IDENTITY absent → helper returns (None, None) regardless of config."""
        from app.channels.manager import ChannelManager

        monkeypatch.delenv("ENABLE_IDENTITY", raising=False)

        bus = MessageBus()
        store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
        manager = ChannelManager(
            bus=bus,
            store=store,
            channel_sessions={"telegram": {"tenant_id": 7, "workspace_id": 3}},
        )

        msg = InboundMessage(channel_name="telegram", chat_id="c1", user_id="u1", text="hi")
        tid, wid = manager._resolve_channel_identity(msg)
        assert tid is None
        assert wid is None

    def test_resolve_channel_identity_flag_on_reads_channel_layer(self, monkeypatch):
        """ENABLE_IDENTITY=1 + channel config → returns the configured pair."""
        from app.channels.manager import ChannelManager

        monkeypatch.setenv("ENABLE_IDENTITY", "1")

        bus = MessageBus()
        store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
        manager = ChannelManager(
            bus=bus,
            store=store,
            channel_sessions={"telegram": {"tenant_id": 7, "workspace_id": 3}},
        )

        msg = InboundMessage(channel_name="telegram", chat_id="c1", user_id="u1", text="hi")
        tid, wid = manager._resolve_channel_identity(msg)
        assert tid == 7
        assert wid == 3

    def test_resolve_channel_identity_falls_back_to_default_session(self, monkeypatch):
        """ENABLE_IDENTITY=1 + no per-channel values + default_session → uses default."""
        from app.channels.manager import ChannelManager

        monkeypatch.setenv("ENABLE_IDENTITY", "1")

        bus = MessageBus()
        store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
        manager = ChannelManager(
            bus=bus,
            store=store,
            default_session={"tenant_id": 2, "workspace_id": 5},
            channel_sessions={"telegram": {}},
        )

        msg = InboundMessage(channel_name="telegram", chat_id="c1", user_id="u1", text="hi")
        tid, wid = manager._resolve_channel_identity(msg)
        assert tid == 2
        assert wid == 5

    def test_resolve_channel_identity_rejects_non_int(self, monkeypatch):
        """Non-int config values are treated as missing (defensive)."""
        from app.channels.manager import ChannelManager

        monkeypatch.setenv("ENABLE_IDENTITY", "1")

        bus = MessageBus()
        store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
        manager = ChannelManager(
            bus=bus,
            store=store,
            channel_sessions={"telegram": {"tenant_id": "seven", "workspace_id": None}},
        )

        msg = InboundMessage(channel_name="telegram", chat_id="c1", user_id="u1", text="hi")
        tid, wid = manager._resolve_channel_identity(msg)
        assert tid is None
        assert wid is None
```

### Step 2.2: Run tests to verify they fail

Run:
```
cd /Users/lydoc/projectscoding/deer-flow/backend && PYTHONPATH=. uv run pytest tests/test_channels.py::TestChannelManagerIdentity -v
```
Expected: FAIL — `AttributeError: 'ChannelManager' object has no attribute '_resolve_channel_identity'`.

### Step 2.3: Implement `_resolve_channel_identity`

Edit `backend/app/channels/manager.py`. Add the helper immediately after `_resolve_session_layer` (around line 551, just before `_resolve_run_params`):

```python
    def _resolve_channel_identity(self, msg: InboundMessage) -> tuple[int | None, int | None]:
        """Read tenant/workspace IDs from channel config when the flag is on.

        Returns ``(None, None)`` when ``ENABLE_IDENTITY`` is off, the config
        omits both values, or the values aren't positive ints. The channel
        layer wins over ``default_session`` — same merge semantics as
        ``_resolve_session_layer``.
        """
        if os.environ.get("ENABLE_IDENTITY", "").strip().lower() not in {"1", "true", "yes", "on"}:
            return None, None

        channel_layer, _ = self._resolve_session_layer(msg)

        def _pick(key: str) -> int | None:
            value = channel_layer.get(key)
            if value is None:
                value = self._default_session.get(key)
            if isinstance(value, bool) or not isinstance(value, int):
                return None
            return value if value > 0 else None

        return _pick("tenant_id"), _pick("workspace_id")
```

Add `import os` at the top of the file if not already imported — check the existing imports (the file already uses `os.environ` elsewhere? verify). If `os` is missing, add `import os` alphabetically at the top import block (after `import mimetypes`, before `import re`).

Check: `grep -n "^import os" backend/app/channels/manager.py` — if the grep shows nothing, add `import os` at line 5 (between `import logging` and `import mimetypes`).

### Step 2.4: Run the tests to verify they pass

Run:
```
cd /Users/lydoc/projectscoding/deer-flow/backend && PYTHONPATH=. uv run pytest tests/test_channels.py::TestChannelManagerIdentity -v
```
Expected: PASS (4 tests green).

### Step 2.5: Commit

```bash
cd /Users/lydoc/projectscoding/deer-flow && git add backend/app/channels/manager.py backend/tests/test_channels.py
git commit -m "feat(channels): add _resolve_channel_identity helper reading channel_sessions config"
```

---

## Task 3: Thread tenant/workspace IDs through dispatch

**Files:**
- Modify: `backend/app/channels/manager.py` (`_create_thread`, `_handle_chat`, `_handle_streaming_chat`, `_prepare_artifact_delivery`, `_resolve_attachments`, remove `TODO(m5-identity)` block)
- Test: `backend/tests/test_channels.py` (add end-to-end tests to `TestChannelManagerIdentity`)

### Step 3.1: Write the failing tests

Append these tests to the `TestChannelManagerIdentity` class in `backend/tests/test_channels.py`:

```python
    def test_handle_chat_persists_tenant_workspace_into_store(self, monkeypatch):
        """When flag is on + channel config has the pair, set_thread_id stores them."""
        from app.channels.manager import ChannelManager

        monkeypatch.setenv("ENABLE_IDENTITY", "1")

        async def go():
            bus = MessageBus()
            store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
            manager = ChannelManager(
                bus=bus,
                store=store,
                channel_sessions={"telegram": {"tenant_id": 7, "workspace_id": 3}},
            )

            mock_client = _make_mock_langgraph_client()
            manager._client = mock_client

            outbound_received = []

            async def capture(msg):
                outbound_received.append(msg)

            bus.subscribe_outbound(capture)
            await manager.start()

            await bus.publish_inbound(
                InboundMessage(channel_name="telegram", chat_id="chat1", user_id="u1", text="hi")
            )
            await _wait_for(lambda: len(outbound_received) >= 1)
            await manager.stop()

            mapping = store.get_thread_mapping("telegram", "chat1")
            assert mapping is not None
            assert mapping["tenant_id"] == 7
            assert mapping["workspace_id"] == 3

        _run(go())

    def test_resolve_attachments_flag_off_passes_none(self, monkeypatch):
        """Flag off → paths.resolve_virtual_path called with tenant_id=None, workspace_id=None."""
        from app.channels import manager as manager_module
        from app.channels.manager import _resolve_attachments

        monkeypatch.delenv("ENABLE_IDENTITY", raising=False)

        fake_paths = MagicMock()
        fake_paths.sandbox_outputs_dir.return_value = Path("/tmp/outputs")

        resolved_path = MagicMock()
        resolved_path.resolve.return_value = resolved_path
        resolved_path.relative_to.return_value = Path("file.txt")
        resolved_path.is_file.return_value = True
        resolved_path.stat.return_value = SimpleNamespace(st_size=10)
        resolved_path.name = "file.txt"
        fake_paths.resolve_virtual_path.return_value = resolved_path

        class _Stub:
            def get_paths(self):
                return fake_paths

        monkeypatch.setitem(
            __import__("sys").modules,
            "deerflow.config.paths",
            _Stub(),
        )

        attachments = _resolve_attachments(
            "thread-xyz",
            ["/mnt/user-data/outputs/file.txt"],
            tenant_id=None,
            workspace_id=None,
        )

        fake_paths.resolve_virtual_path.assert_called_once()
        _, kwargs = fake_paths.resolve_virtual_path.call_args
        # Accept either kwargs or trailing positional args — but assert they are None.
        assert kwargs.get("tenant_id") is None
        assert kwargs.get("workspace_id") is None
        assert len(attachments) == 1

    def test_resolve_attachments_flag_on_passes_ids(self, monkeypatch):
        """Flag on + IDs supplied → paths.resolve_virtual_path gets the IDs as kwargs."""
        from app.channels.manager import _resolve_attachments

        fake_paths = MagicMock()
        fake_paths.sandbox_outputs_dir.return_value = Path("/tmp/outputs")

        resolved_path = MagicMock()
        resolved_path.resolve.return_value = resolved_path
        resolved_path.relative_to.return_value = Path("file.txt")
        resolved_path.is_file.return_value = True
        resolved_path.stat.return_value = SimpleNamespace(st_size=42)
        resolved_path.name = "file.txt"
        fake_paths.resolve_virtual_path.return_value = resolved_path

        class _Stub:
            def get_paths(self):
                return fake_paths

        monkeypatch.setitem(
            __import__("sys").modules,
            "deerflow.config.paths",
            _Stub(),
        )

        _resolve_attachments(
            "thread-xyz",
            ["/mnt/user-data/outputs/file.txt"],
            tenant_id=7,
            workspace_id=3,
        )

        fake_paths.resolve_virtual_path.assert_called_once()
        _, kwargs = fake_paths.resolve_virtual_path.call_args
        assert kwargs.get("tenant_id") == 7
        assert kwargs.get("workspace_id") == 3
```

### Step 3.2: Run the tests to verify they fail

Run:
```
cd /Users/lydoc/projectscoding/deer-flow/backend && PYTHONPATH=. uv run pytest tests/test_channels.py::TestChannelManagerIdentity -v
```
Expected: FAIL — `_resolve_attachments` signature doesn't accept `tenant_id`/`workspace_id`, and `set_thread_id` isn't being called with them by `_create_thread`.

### Step 3.3: Implement: update `_resolve_attachments` signature

Edit `backend/app/channels/manager.py`. Replace `_resolve_attachments` (lines 331-381) with the new signature + logic. Remove the `TODO(m5-identity)` block:

```python
def _resolve_attachments(
    thread_id: str,
    artifacts: list[str],
    *,
    tenant_id: int | None = None,
    workspace_id: int | None = None,
) -> list[ResolvedAttachment]:
    """Resolve virtual artifact paths to host filesystem paths with metadata.

    Only paths under ``/mnt/user-data/outputs/`` are accepted; any other
    virtual path is rejected with a warning to prevent exfiltrating uploads
    or workspace files via IM channels.

    When ``tenant_id`` / ``workspace_id`` are supplied (M4 identity on),
    :func:`Paths.resolve_virtual_path` routes to the tenant-stratified layout;
    when absent, the legacy single-tenant path is used.

    Skips artifacts that cannot be resolved (missing files, invalid paths)
    and logs warnings for them.
    """
    from deerflow.config.paths import get_paths

    attachments: list[ResolvedAttachment] = []
    paths = get_paths()
    outputs_dir = paths.sandbox_outputs_dir(thread_id).resolve()
    for virtual_path in artifacts:
        # Security: only allow files from the agent outputs directory
        if not virtual_path.startswith(_OUTPUTS_VIRTUAL_PREFIX):
            logger.warning("[Manager] rejected non-outputs artifact path: %s", virtual_path)
            continue
        try:
            actual = paths.resolve_virtual_path(
                thread_id,
                virtual_path,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
            )
            # Verify the resolved path is actually under the outputs directory
            # (guards against path-traversal even after prefix check)
            try:
                actual.resolve().relative_to(outputs_dir)
            except ValueError:
                logger.warning("[Manager] artifact path escapes outputs dir: %s -> %s", virtual_path, actual)
                continue
            if not actual.is_file():
                logger.warning("[Manager] artifact not found on disk: %s -> %s", virtual_path, actual)
                continue
            mime, _ = mimetypes.guess_type(str(actual))
            mime = mime or "application/octet-stream"
            attachments.append(
                ResolvedAttachment(
                    virtual_path=virtual_path,
                    actual_path=actual,
                    filename=actual.name,
                    mime_type=mime,
                    size=actual.stat().st_size,
                    is_image=mime.startswith("image/"),
                )
            )
        except (ValueError, OSError) as exc:
            logger.warning("[Manager] failed to resolve artifact %s: %s", virtual_path, exc)
    return attachments
```

### Step 3.4: Implement: update `_prepare_artifact_delivery` signature

Replace `_prepare_artifact_delivery` (around line 384-408) with:

```python
def _prepare_artifact_delivery(
    thread_id: str,
    response_text: str,
    artifacts: list[str],
    *,
    tenant_id: int | None = None,
    workspace_id: int | None = None,
) -> tuple[str, list[ResolvedAttachment]]:
    """Resolve attachments and append filename fallbacks to the text response."""
    attachments: list[ResolvedAttachment] = []
    if not artifacts:
        return response_text, attachments

    attachments = _resolve_attachments(
        thread_id,
        artifacts,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    resolved_virtuals = {attachment.virtual_path for attachment in attachments}
    unresolved = [path for path in artifacts if path not in resolved_virtuals]

    if unresolved:
        artifact_text = _format_artifact_text(unresolved)
        response_text = (response_text + "\n\n" + artifact_text) if response_text else artifact_text

    # Always include resolved attachment filenames as a text fallback so files
    # remain discoverable even when the upload is skipped or fails.
    if attachments:
        resolved_text = _format_artifact_text([attachment.virtual_path for attachment in attachments])
        response_text = (response_text + "\n\n" + resolved_text) if response_text else resolved_text

    return response_text, attachments
```

### Step 3.5: Implement: update `_create_thread` to persist IDs

Replace `_create_thread` (around line 673-685) with:

```python
    async def _create_thread(self, client, msg: InboundMessage) -> str:
        """Create a new thread on the LangGraph Server and store the mapping."""
        thread = await client.threads.create()
        thread_id = thread["thread_id"]
        tenant_id, workspace_id = self._resolve_channel_identity(msg)
        self.store.set_thread_id(
            msg.channel_name,
            msg.chat_id,
            thread_id,
            topic_id=msg.topic_id,
            user_id=msg.user_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
        logger.info(
            "[Manager] new thread created on LangGraph Server: thread_id=%s for chat_id=%s topic_id=%s tenant_id=%s workspace_id=%s",
            thread_id,
            msg.chat_id,
            msg.topic_id,
            tenant_id,
            workspace_id,
        )
        return thread_id
```

### Step 3.6: Implement: read stored IDs in `_handle_chat` + pass to `_prepare_artifact_delivery`

In `_handle_chat` (around line 687), replace the `thread_id` lookup block (lines 692-699) with:

```python
        # Look up existing DeerFlow thread mapping — includes tenant/workspace
        # when M4+ identity is on. ``None`` for both when flag is off.
        mapping = self.store.get_thread_mapping(msg.channel_name, msg.chat_id, topic_id=msg.topic_id)
        if mapping is not None:
            thread_id = mapping["thread_id"]
            tenant_id = mapping.get("tenant_id")
            workspace_id = mapping.get("workspace_id")
            logger.info("[Manager] reusing thread: thread_id=%s for topic_id=%s", thread_id, msg.topic_id)
        else:
            thread_id = await self._create_thread(client, msg)
            # _create_thread has now written the mapping — read it back so we
            # use the exact same pair the store persisted.
            mapping = self.store.get_thread_mapping(msg.channel_name, msg.chat_id, topic_id=msg.topic_id) or {}
            tenant_id = mapping.get("tenant_id")
            workspace_id = mapping.get("workspace_id")
```

Then in the same function, change the `_prepare_artifact_delivery` call (around line 751) from:

```python
        response_text, attachments = _prepare_artifact_delivery(thread_id, response_text, artifacts)
```

to:

```python
        response_text, attachments = _prepare_artifact_delivery(
            thread_id,
            response_text,
            artifacts,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
```

Also pass the IDs into `_handle_streaming_chat`. Change the streaming call site (around line 722-730):

```python
        if self._channel_supports_streaming(msg.channel_name):
            await self._handle_streaming_chat(
                client,
                msg,
                thread_id,
                assistant_id,
                run_config,
                run_context,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
            )
            return
```

### Step 3.7: Implement: update `_handle_streaming_chat` signature

Replace the signature of `_handle_streaming_chat` (around line 771-779) with:

```python
    async def _handle_streaming_chat(
        self,
        client,
        msg: InboundMessage,
        thread_id: str,
        assistant_id: str,
        run_config: dict[str, Any],
        run_context: dict[str, Any],
        *,
        tenant_id: int | None = None,
        workspace_id: int | None = None,
    ) -> None:
```

In the streaming `finally` block, update the `_prepare_artifact_delivery` call (around line 842):

```python
            response_text, attachments = _prepare_artifact_delivery(
                thread_id,
                response_text,
                artifacts,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
            )
```

### Step 3.8: Implement: update `_handle_command`'s `/new` branch to pass IDs

In `_handle_command` (around line 892-901), update the `set_thread_id` call inside the `/new` branch:

```python
        if command == "new":
            # Create a new thread on the LangGraph Server
            client = self._get_client()
            thread = await client.threads.create()
            new_thread_id = thread["thread_id"]
            tenant_id, workspace_id = self._resolve_channel_identity(msg)
            self.store.set_thread_id(
                msg.channel_name,
                msg.chat_id,
                new_thread_id,
                topic_id=msg.topic_id,
                user_id=msg.user_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
            )
            reply = "New conversation started."
```

### Step 3.9: Run tests to verify they pass

Run:
```
cd /Users/lydoc/projectscoding/deer-flow/backend && PYTHONPATH=. uv run pytest tests/test_channels.py -v
```
Expected: PASS — the new `TestChannelManagerIdentity` tests green **and** the pre-existing `TestChannelManager` + `TestChannelStore` tests still green (no regressions).

If any pre-existing test fails because a mock of `paths.resolve_virtual_path` was called with new kwargs, adjust the mock expectation to `call_args.kwargs` rather than hard-checking positional-only call. Re-run until clean.

### Step 3.10: Run the offline / harness-boundary regression guards

Run:
```
cd /Users/lydoc/projectscoding/deer-flow/backend && PYTHONPATH=. uv run pytest tests/identity/test_feature_flag_offline.py tests/test_harness_boundary.py -v
```
Expected: PASS — the channel changes don't introduce any new `app.gateway.identity.*` imports into modules loaded when the flag is off, and nothing in `packages/harness/deerflow/` imports from `app.*`.

### Step 3.11: Commit

```bash
cd /Users/lydoc/projectscoding/deer-flow && git add backend/app/channels/manager.py backend/tests/test_channels.py
git commit -m "feat(channels): thread tenant_id/workspace_id through resolve_virtual_path (resolves M4 TODO)"
```

---

# Part 2 — CI E2E Identity Smoke

## Task 4: `issue_bootstrap_token.py` helper

**Files:**
- Create: `backend/scripts/ci/__init__.py` (empty)
- Create: `backend/scripts/ci/issue_bootstrap_token.py`
- Test: run it manually (no unit test; it's a CLI helper exercised by Task 6's smoke runner).

### Step 4.1: Create the empty package marker

Create `backend/scripts/ci/__init__.py` with an empty string as content.

### Step 4.2: Create the JWT minting script

Create `backend/scripts/ci/issue_bootstrap_token.py`:

```python
"""Mint a short-lived RS256 JWT for the bootstrap admin user.

Used by the CI identity smoke workflow to avoid the OIDC dance. The JWT is
signed with the same RS256 key the Gateway uses for internal auth, so
``IdentityMiddleware`` resolves it exactly like a post-OIDC access token.

Usage::

    DEERFLOW_BOOTSTRAP_ADMIN_EMAIL=admin@smoke.test \\
        python scripts/ci/issue_bootstrap_token.py

Exit 0 with the JWT printed on stdout; exit 2 on config / DB errors.
"""

from __future__ import annotations

import asyncio
import sys
import time
import uuid

from sqlalchemy import select

from app.gateway.identity.auth.identity_factory import build_identity_for_user
from app.gateway.identity.auth.jwt import AccessTokenClaims, issue_access_token
from app.gateway.identity.db import create_engine_and_sessionmaker
from app.gateway.identity.models.tenant import Tenant, Workspace
from app.gateway.identity.models.user import User
from app.gateway.identity.settings import get_identity_settings


async def _mint() -> str:
    settings = get_identity_settings()

    if not settings.enabled:
        raise SystemExit("ENABLE_IDENTITY must be true to mint a bootstrap JWT")

    email = settings.bootstrap_admin_email
    if not email:
        raise SystemExit("DEERFLOW_BOOTSTRAP_ADMIN_EMAIL must be set")

    # Load the private key. Prefer the env-embedded key; fall back to disk.
    if settings.jwt_private_key:
        private_pem = settings.jwt_private_key
    else:
        with open(settings.jwt_private_key_path) as f:
            private_pem = f.read()

    engine, maker = create_engine_and_sessionmaker(settings.database_url)
    try:
        async with maker() as session:
            user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
            if user is None:
                raise SystemExit(f"bootstrap admin {email!r} not found (run `make identity-bootstrap` first)")

            # The bootstrap admin has a Membership to the default tenant. Find it.
            tenant = (
                await session.execute(
                    select(Tenant)
                    .join(Tenant.memberships)
                    .where(Tenant.memberships.property.mapper.class_.user_id == user.id)
                )
            ).scalars().first()
            if tenant is None:
                # Fall back to the first tenant the seed created ("default").
                tenant = (
                    await session.execute(select(Tenant).order_by(Tenant.id).limit(1))
                ).scalar_one_or_none()
                if tenant is None:
                    raise SystemExit("no tenant rows exist — bootstrap did not run")

            workspace = (
                await session.execute(
                    select(Workspace).where(Workspace.tenant_id == tenant.id).order_by(Workspace.id).limit(1)
                )
            ).scalar_one_or_none()

            identity = await build_identity_for_user(session, user, tenant, workspace)
    finally:
        await engine.dispose()

    now = int(time.time())
    claims = AccessTokenClaims(
        sub=str(identity.user_id),
        email=identity.email or email,
        tid=identity.tenant_id,
        wids=list(identity.workspace_ids),
        permissions=sorted(identity.permissions),
        roles=identity.roles,
        sid=uuid.uuid4().hex,
        iat=now,
        exp=now + 60,
        iss=settings.jwt_issuer,
        aud=settings.jwt_audience,
    )
    return issue_access_token(claims, private_key_pem=private_pem)


def main() -> None:
    try:
        token = asyncio.run(_mint())
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover — defensive for CI
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    print(token)


if __name__ == "__main__":
    main()
```

Note on the membership join: `User` doesn't have a `.memberships` relationship defined — double-check by grepping `Membership` in `backend/app/gateway/identity/models/user.py`. If the relationship is not defined there, replace the tenant-resolution block with an explicit `Membership` query:

```python
            from app.gateway.identity.models.user import Membership

            tenant_row = (
                await session.execute(
                    select(Tenant)
                    .join(Membership, Membership.tenant_id == Tenant.id)
                    .where(Membership.user_id == user.id, Membership.status == 1)
                    .order_by(Tenant.id)
                    .limit(1)
                )
            ).scalar_one_or_none()
            tenant = tenant_row
            if tenant is None:
                tenant = (
                    await session.execute(select(Tenant).order_by(Tenant.id).limit(1))
                ).scalar_one_or_none()
                if tenant is None:
                    raise SystemExit("no tenant rows exist — bootstrap did not run")
```

Use whichever variant actually compiles — the agent executing this plan must verify with `grep -n "memberships\|Membership" backend/app/gateway/identity/models/user.py` before committing.

### Step 4.3: Smoke-test the script manually

Run locally (requires postgres + redis running and bootstrap executed):

```
cd /Users/lydoc/projectscoding/deer-flow/backend && \
  ENABLE_IDENTITY=true \
  DEERFLOW_DATABASE_URL=postgresql+asyncpg://deerflow:deerflow@localhost:5432/deerflow \
  DEERFLOW_REDIS_URL=redis://localhost:6379/0 \
  DEERFLOW_BOOTSTRAP_ADMIN_EMAIL=admin@smoke.test \
  PYTHONPATH=. uv run python scripts/ci/issue_bootstrap_token.py
```

Expected: a single line of JWT on stdout (three dot-separated base64 segments). If the local DB isn't running, skip this — Task 7 exercises it end-to-end in CI.

### Step 4.4: Commit

```bash
cd /Users/lydoc/projectscoding/deer-flow && git add backend/scripts/ci/__init__.py backend/scripts/ci/issue_bootstrap_token.py
git commit -m "feat(ci): add issue_bootstrap_token.py (mints RS256 JWT for CI smoke)"
```

---

## Task 5: `identity_smoke_test.py` runner

**Files:**
- Create: `backend/scripts/ci/identity_smoke_test.py`

### Step 5.1: Create the smoke runner

Create `backend/scripts/ci/identity_smoke_test.py`:

```python
"""End-to-end smoke check for ENABLE_IDENTITY=true Gateway.

Exercises the full auth pipeline with no OIDC mock:

    1. GET  /health                                → 200
    2. POST /api/me/tokens  (JWT auth)             → 201, plaintext starting dft_
    3. GET  /api/me         (API token auth)       → 200, user_id + tenant_id non-null
    4. GET  /api/tenants/{tid}/audit  (API token)  → 200, items non-empty

Exit 0 with "smoke: all assertions passed"; exit 1 on any failure, dumping
the offending response body to stderr.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import httpx

GATEWAY = os.environ.get("GATEWAY_URL", "http://127.0.0.1:8001")
TIMEOUT = httpx.Timeout(10.0, connect=5.0)


def _die(msg: str, resp: httpx.Response | None = None) -> None:
    print(f"smoke FAIL: {msg}", file=sys.stderr)
    if resp is not None:
        print(f"  status: {resp.status_code}", file=sys.stderr)
        print(f"  body:   {resp.text[:2000]}", file=sys.stderr)
    sys.exit(1)


def _issue_jwt() -> str:
    here = Path(__file__).resolve().parent
    script = here / "issue_bootstrap_token.py"
    result = subprocess.run(
        [sys.executable, str(script)],
        check=False,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        _die(f"issue_bootstrap_token.py exited {result.returncode}")
    token = result.stdout.strip()
    if not token or token.count(".") != 2:
        _die(f"bad JWT shape: {token!r}")
    return token


def main() -> None:
    jwt = _issue_jwt()
    jwt_headers = {"Authorization": f"Bearer {jwt}"}

    with httpx.Client(timeout=TIMEOUT) as client:
        # 1. /health
        r = client.get(f"{GATEWAY}/health")
        if r.status_code != 200:
            _die("GET /health", r)
        print("smoke: /health OK")

        # 2. Create API token using the JWT
        r = client.post(
            f"{GATEWAY}/api/me/tokens",
            headers=jwt_headers,
            json={"name": "ci-smoke", "scopes": ["thread:read", "thread:write"]},
        )
        if r.status_code not in (200, 201):
            _die("POST /api/me/tokens", r)
        body = r.json()
        plaintext = body.get("plaintext", "")
        if not plaintext.startswith("dft_"):
            _die(f"api-token plaintext does not start with dft_: {plaintext!r}", r)
        print("smoke: POST /api/me/tokens OK")

        api_headers = {"Authorization": f"Bearer {plaintext}"}

        # 3. /api/me via API token
        r = client.get(f"{GATEWAY}/api/me", headers=api_headers)
        if r.status_code != 200:
            _die("GET /api/me", r)
        me = r.json()
        if not me.get("user_id"):
            _die(f"/api/me missing user_id: {me!r}", r)
        if me.get("active_tenant_id") is None:
            _die(f"/api/me active_tenant_id is null: {me!r}", r)
        tenant_id = me["active_tenant_id"]
        print(f"smoke: /api/me OK (tenant_id={tenant_id})")

        # 4. Audit list — audit middleware should have logged the calls above.
        r = client.get(f"{GATEWAY}/api/tenants/{tenant_id}/audit", headers=api_headers)
        if r.status_code != 200:
            _die(f"GET /api/tenants/{tenant_id}/audit", r)
        audit = r.json()
        items = audit.get("items", [])
        if not items:
            _die(f"audit items empty — middleware may not be firing: {audit!r}", r)
        print(f"smoke: /api/tenants/{tenant_id}/audit OK (items={len(items)})")

    print("smoke: all assertions passed")


if __name__ == "__main__":
    main()
```

### Step 5.2: Syntax-check the runner

Run:
```
cd /Users/lydoc/projectscoding/deer-flow/backend && PYTHONPATH=. uv run python -c "import ast; ast.parse(open('scripts/ci/identity_smoke_test.py').read()); print('OK')"
```
Expected: `OK`.

### Step 5.3: Commit

```bash
cd /Users/lydoc/projectscoding/deer-flow && git add backend/scripts/ci/identity_smoke_test.py
git commit -m "feat(ci): add identity_smoke_test.py (4-assertion end-to-end smoke)"
```

---

## Task 6: GitHub Actions workflow

**Files:**
- Create: `.github/workflows/identity-e2e-smoke.yml`

### Step 6.1: Create the workflow

Create `.github/workflows/identity-e2e-smoke.yml`:

```yaml
name: Identity E2E Smoke

on:
  push:
    branches: [ 'main' ]
    paths:
      - 'backend/**'
      - '.github/workflows/identity-e2e-smoke.yml'
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review]
    paths:
      - 'backend/**'
      - '.github/workflows/identity-e2e-smoke.yml'

concurrency:
  group: identity-e2e-smoke-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: true

permissions:
  contents: read

jobs:
  smoke:
    if: github.event.pull_request.draft == false
    runs-on: ubuntu-latest
    timeout-minutes: 15
    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_DB: deerflow
          POSTGRES_USER: deerflow
          POSTGRES_PASSWORD: deerflow
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U deerflow -d deerflow"
          --health-interval 5s
          --health-timeout 3s
          --health-retries 10
      redis:
        image: redis:7-alpine
        ports:
          - 6379:6379
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 5s
          --health-timeout 3s
          --health-retries 10

    env:
      ENABLE_IDENTITY: "true"
      DEERFLOW_DATABASE_URL: postgresql+asyncpg://deerflow:deerflow@localhost:5432/deerflow
      DEERFLOW_REDIS_URL: redis://localhost:6379/0
      DEERFLOW_BOOTSTRAP_ADMIN_EMAIL: admin@smoke.test
      DEERFLOW_INTERNAL_SIGNING_KEY: smoke-test-signing-key-32chars!!
      DEERFLOW_COOKIE_SECURE: "false"
      DEER_FLOW_HOME: ${{ github.workspace }}/backend/.deer-flow

    steps:
      - name: Checkout
        uses: actions/checkout@v6

      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: '3.12'

      - name: Install uv
        uses: astral-sh/setup-uv@v7

      - name: Install backend dependencies
        working-directory: backend
        run: uv sync --group dev

      - name: Alembic upgrade head
        working-directory: backend
        run: PYTHONPATH=. uv run alembic upgrade head

      - name: Generate RS256 keypair
        working-directory: backend
        run: make identity-keys

      - name: Bootstrap platform admin
        working-directory: backend
        run: PYTHONPATH=. uv run python -m app.gateway.identity.cli bootstrap

      - name: Start Gateway
        working-directory: backend
        run: |
          PYTHONPATH=. uv run uvicorn app.gateway.app:app \
            --host 127.0.0.1 --port 8001 \
            > gateway.log 2>&1 &
          echo $! > gateway.pid

      - name: Wait for /health
        run: |
          for i in $(seq 1 30); do
            if curl -fsS http://127.0.0.1:8001/health > /dev/null; then
              echo "gateway is up"
              exit 0
            fi
            sleep 1
          done
          echo "gateway did not come up"
          cat backend/gateway.log || true
          exit 1

      - name: Run identity smoke test
        working-directory: backend
        run: PYTHONPATH=. uv run python scripts/ci/identity_smoke_test.py

      - name: Stop Gateway
        if: always()
        working-directory: backend
        run: |
          if [ -f gateway.pid ]; then
            kill $(cat gateway.pid) 2>/dev/null || true
            rm -f gateway.pid
          fi

      - name: Upload gateway log
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: gateway-log
          path: backend/gateway.log
          if-no-files-found: ignore
```

### Step 6.2: Validate YAML locally

Run:
```
cd /Users/lydoc/projectscoding/deer-flow && python3 -c "import yaml; yaml.safe_load(open('.github/workflows/identity-e2e-smoke.yml')); print('OK')"
```
Expected: `OK`. (If `pyyaml` is not available, skip — the GitHub API will fail loudly on malformed YAML when the workflow is pushed to origin.)

### Step 6.3: Commit

```bash
cd /Users/lydoc/projectscoding/deer-flow && git add .github/workflows/identity-e2e-smoke.yml
git commit -m "ci: add identity-e2e-smoke workflow (PG+Redis, bootstrap, JWT, API token, audit)"
```

---

## Task 7: Full local verification + CLAUDE.md update

**Files:**
- Modify: `backend/CLAUDE.md` (flip the "Still open" line)

### Step 7.1: Run the full backend suite

Run:
```
cd /Users/lydoc/projectscoding/deer-flow/backend && make test
```
Expected: PASS — no regressions, the new channel tests green.

### Step 7.2: Run `make lint`

Run:
```
cd /Users/lydoc/projectscoding/deer-flow/backend && make lint
```
Expected: PASS.

If `ruff` flags anything in the new files, fix in-place (common fixes: `from __future__ import annotations` already present; ruff's `I001` import sort). Re-run until green.

### Step 7.3: Exercise the smoke workflow end-to-end locally (optional but recommended)

Run once if you have Docker and can start PG+Redis:

```bash
cd /Users/lydoc/projectscoding/deer-flow && docker run -d --rm --name smoke-pg \
  -e POSTGRES_DB=deerflow -e POSTGRES_USER=deerflow -e POSTGRES_PASSWORD=deerflow \
  -p 5432:5432 postgres:16-alpine

docker run -d --rm --name smoke-redis -p 6379:6379 redis:7-alpine

cd backend && \
  ENABLE_IDENTITY=true \
  DEERFLOW_DATABASE_URL=postgresql+asyncpg://deerflow:deerflow@localhost:5432/deerflow \
  DEERFLOW_REDIS_URL=redis://localhost:6379/0 \
  DEERFLOW_BOOTSTRAP_ADMIN_EMAIL=admin@smoke.test \
  DEERFLOW_INTERNAL_SIGNING_KEY=smoke-test-signing-key-32chars!! \
  DEERFLOW_COOKIE_SECURE=false \
  PYTHONPATH=. uv run alembic upgrade head && \
  PYTHONPATH=. uv run python -c "from app.gateway.identity.auth.jwt import ensure_rsa_keypair; from app.gateway.identity.settings import get_identity_settings; s = get_identity_settings(); ensure_rsa_keypair(s.jwt_private_key_path, s.jwt_public_key_path)" && \
  PYTHONPATH=. uv run python -m app.gateway.identity.cli bootstrap && \
  PYTHONPATH=. uv run uvicorn app.gateway.app:app --host 127.0.0.1 --port 8001 &

# in another terminal, once /health returns 200:
cd /Users/lydoc/projectscoding/deer-flow/backend && \
  ENABLE_IDENTITY=true \
  DEERFLOW_DATABASE_URL=postgresql+asyncpg://deerflow:deerflow@localhost:5432/deerflow \
  DEERFLOW_REDIS_URL=redis://localhost:6379/0 \
  DEERFLOW_BOOTSTRAP_ADMIN_EMAIL=admin@smoke.test \
  DEERFLOW_INTERNAL_SIGNING_KEY=smoke-test-signing-key-32chars!! \
  PYTHONPATH=. uv run python scripts/ci/identity_smoke_test.py
```

Expected: `smoke: all assertions passed`. Tear down with `docker stop smoke-pg smoke-redis`, `kill %1`.

Skip this step if Docker isn't available locally — Task 6's CI run is the authoritative verification surface.

### Step 7.4: Update `backend/CLAUDE.md`

Find the line near the end of the identity section (around the "Still open for a follow-up session" paragraph):

```
**Still open for a follow-up session:** M7 Part A (14 admin pages + Playwright E2E) and Part C.8 (GitHub Actions end-to-end smoke — needs OIDC mock IdP infrastructure).
```

Replace with:

```
**Still open for a follow-up session:** None — M7 Part C.8 (GitHub Actions identity E2E smoke) shipped via `.github/workflows/identity-e2e-smoke.yml` (bypasses OIDC by minting an RS256 JWT directly for the bootstrap admin); channel identity TODO resolved via `ChannelStore` persistence of `tenant_id`/`workspace_id` and `Paths.resolve_virtual_path` wiring.
```

Also in the `IM Channels System` section, update the reference to `TODO(m5-identity)` in the file description. Replace:

```
- `store.py` - JSON-file persistence mapping `channel_name:chat_id[:topic_id]` → `thread_id` (keys are `channel:chat` for root conversations and `channel:chat:topic` for threaded conversations)
```

with:

```
- `store.py` - JSON-file persistence mapping `channel_name:chat_id[:topic_id]` → `{thread_id, tenant_id, workspace_id, user_id, ...}` (keys are `channel:chat` for root conversations and `channel:chat:topic` for threaded conversations). When `ENABLE_IDENTITY` is off (or channel config omits the pair), `tenant_id`/`workspace_id` are stored as `null` and resolvers fall back to the legacy flat path.
```

In the `Channel identity deferred` bullet inside the M4 storage section, replace:

```
- **Channel identity deferred**: `app/channels/manager.py` still calls `Paths.resolve_virtual_path` without identity. Marked with `TODO(m5-identity)` — IM channel identity threading is tracked for the M5 follow-up pass; the M5 Gateway→LangGraph HMAC propagation work has landed (see below).
```

with:

```
- **Channel identity**: `app/channels/manager.py::_resolve_channel_identity` reads `tenant_id`/`workspace_id` from `channel_sessions.<name>` (falling back to `default_session`) when `ENABLE_IDENTITY=true`. `ChannelManager._create_thread` persists the pair into `ChannelStore` at thread creation time; `_handle_chat` + `_handle_streaming_chat` read them back via `get_thread_mapping` and pass them to `paths.resolve_virtual_path` so IM artifacts land under the tenant-stratified outputs directory. Flag off → both values `None` → legacy single-tenant path preserved.
```

### Step 7.5: Commit

```bash
cd /Users/lydoc/projectscoding/deer-flow && git add backend/CLAUDE.md
git commit -m "docs(identity): mark M7 C.8 + channel identity TODO as shipped"
```

### Step 7.6: Final inventory

Run:
```
cd /Users/lydoc/projectscoding/deer-flow && git log --oneline -10
```
Expected: 5 new commits from this plan on top of `b6d47ca1`:
1. `feat(channels): persist tenant_id/workspace_id in ChannelStore (M7A followup)`
2. `feat(channels): add _resolve_channel_identity helper reading channel_sessions config`
3. `feat(channels): thread tenant_id/workspace_id through resolve_virtual_path (resolves M4 TODO)`
4. `feat(ci): add issue_bootstrap_token.py (mints RS256 JWT for CI smoke)`
5. `feat(ci): add identity_smoke_test.py (4-assertion end-to-end smoke)`
6. `ci: add identity-e2e-smoke workflow (PG+Redis, bootstrap, JWT, API token, audit)`
7. `docs(identity): mark M7 C.8 + channel identity TODO as shipped`

(7 commits total; the exact order can flex if Task 7 runs before the CI commit lands.)

---

## Self-review

**Spec coverage:**
- Part 1 `store.py` changes — Task 1 ✓
- Part 1 `manager.py` `_resolve_channel_identity` — Task 2 ✓
- Part 1 `_resolve_attachments` signature — Task 3 ✓
- Part 1 `_prepare_artifact_delivery` propagation — Task 3 ✓
- Part 1 `_handle_chat` + `_create_thread` wiring — Task 3 ✓
- Part 1 `TODO(m5-identity)` removal — Task 3.3 ✓
- Part 1 streaming path wiring — Task 3.7 ✓
- Part 1 tests (flag_off, flag_on_with_config, store persists, missing config falls back) — Tasks 2 + 3 ✓
- Part 2 `issue_bootstrap_token.py` — Task 4 ✓
- Part 2 `identity_smoke_test.py` — Task 5 ✓
- Part 2 GitHub workflow — Task 6 ✓
- Non-goals (real OIDC, K8s, 1000-thread, rollback drill) — not in plan, matches spec ✓
- Cross-cutting invariants (flag-off no regression, no harness→app import, no audit mutation, paths routed through identity helpers, tool whitelist untouched) — enforced by Task 3.10's regression-guard run ✓

**Placeholder scan:**
No `TBD`, `TODO`, `fill in`, or "similar to Task N". One conditional branch in Task 4 (User.memberships relationship check) — includes an explicit grep command the executor runs to pick between two concrete code variants, not a placeholder.

**Type consistency:**
- `set_thread_id(..., *, tenant_id, workspace_id)` — keyword-only in Task 1, called keyword-only in Tasks 3.5 and 3.8.
- `get_thread_mapping(..., *, topic_id=None)` — keyword-only in Task 1, called keyword-only in Task 3.6.
- `_resolve_attachments(thread_id, artifacts, *, tenant_id, workspace_id)` — keyword-only in Task 3.3, called keyword-only via `_prepare_artifact_delivery` in Task 3.4.
- `_handle_streaming_chat(..., *, tenant_id, workspace_id)` — keyword-only in Task 3.7, called keyword-only in Task 3.6.
- `AccessTokenClaims` fields match `backend/app/gateway/identity/auth/jwt.py:45-59` (sub, email, tid, wids, permissions, roles, sid, iat, exp, iss, aud).

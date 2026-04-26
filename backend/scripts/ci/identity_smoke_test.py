"""End-to-end smoke check for ENABLE_IDENTITY=true Gateway.

Exercises the full auth pipeline with no OIDC mock:

    1. GET  /health                                -> 200
    2. POST /api/me/tokens  (JWT auth)             -> 201, plaintext starting dft_
    3. GET  /api/me         (API token auth)       -> 200, user_id + tenant_id non-null
    4. GET  /api/tenants/{tid}/audit  (API token)  -> 200, items non-empty

Exit 0 with "smoke: all assertions passed"; exit 1 on any failure, dumping
the offending response body to stderr.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

GATEWAY = os.environ.get("GATEWAY_URL", "http://127.0.0.1:8100")
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
            json={"name": "ci-smoke", "scopes": ["thread:read", "thread:write", "audit:read"]},
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

        # 4. Audit list - audit middleware enqueues async; AuditBatchWriter
        # flushes every 1s, so we retry up to 10s for items to appear.
        items: list = []
        last_resp: httpx.Response | None = None
        for _ in range(10):
            r = client.get(f"{GATEWAY}/api/tenants/{tenant_id}/audit", headers=api_headers)
            last_resp = r
            if r.status_code != 200:
                _die(f"GET /api/tenants/{tenant_id}/audit", r)
            items = r.json().get("items", [])
            if items:
                break
            time.sleep(1.0)
        if not items:
            _die("audit items empty after 10s - middleware may not be firing", last_resp)
        print(f"smoke: /api/tenants/{tenant_id}/audit OK (items={len(items)})")

    print("smoke: all assertions passed")


if __name__ == "__main__":
    main()

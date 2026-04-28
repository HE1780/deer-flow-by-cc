// frontend/src/core/identity/fetcher.ts
import { type IdentityError, type Permission } from "./types";

type Listener = () => void;
const listeners = new Set<Listener>();
let sessionExpiredPending = false;

/** Internal-only extension of RequestInit. Set to `true` on the refresh
 *  call itself and on the single post-refresh retry, so a real 401 in
 *  either of those code paths surfaces directly without recursing. */
type InternalInit = RequestInit & { _skipRefreshOn401?: boolean };

/** Singleflight slot. While a refresh is in-flight, all concurrent 401
 *  callers await the same promise. `null` once the refresh resolves so a
 *  later 401 starts a fresh attempt. */
let pendingRefresh: Promise<boolean> | null = null;

export function onSessionExpired(fn: Listener): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function resetSessionExpiredListeners(): void {
  listeners.clear();
  sessionExpiredPending = false;
}

export function consumeSessionExpired(): void {
  sessionExpiredPending = false;
}

function emitSessionExpired(): void {
  if (sessionExpiredPending) return;
  sessionExpiredPending = true;
  for (const fn of listeners) fn();
}

/** Singleflight refresh helper. Returns `true` if the access cookie was
 *  re-issued, `false` otherwise. Internal-only — the only caller is
 *  identityFetch's 401 branch (and `identityApi.refresh` via re-export). */
async function refreshSession(): Promise<boolean> {
  if (pendingRefresh) return pendingRefresh;
  pendingRefresh = identityFetch<unknown>("/api/auth/refresh", {
    method: "POST",
    _skipRefreshOn401: true,
  } as InternalInit)
    .then(() => true)
    .catch(() => false)
    .finally(() => {
      pendingRefresh = null;
    });
  return pendingRefresh;
}

export { refreshSession as _refreshSessionForIdentityApi };

/** Error thrown by identityFetch. Carries the IdentityError variant so callers
 *  can switch on `err.kind`. Extends `Error` so lint rules that require thrown
 *  values to be Error instances are satisfied. */
export class IdentityFetchError extends Error {
  kind: IdentityError["kind"];
  status?: number;
  missing?: Permission;

  constructor(err: IdentityError) {
    super(err.kind);
    this.name = "IdentityFetchError";
    this.kind = err.kind;
    if (err.kind === "forbidden") this.missing = err.missing;
    if (err.kind === "network") {
      this.status = err.status;
      this.message = err.message;
    }
  }
}

export async function identityFetch<T>(
  input: string,
  init?: RequestInit,
): Promise<T> {
  const resp = await fetch(input, {
    credentials: "include",
    headers: {
      accept: "application/json",
      ...(init?.body ? { "content-type": "application/json" } : {}),
      ...init?.headers,
    },
    ...init,
  });

  if (resp.status === 401) {
    emitSessionExpired();
    throw new IdentityFetchError({ kind: "unauthenticated" });
  }
  if (resp.status === 403) {
    let missing: string | undefined;
    try {
      const body = (await resp.json()) as { detail?: { missing?: string } };
      missing = body?.detail?.missing;
    } catch {
      // 403 without JSON body is valid; missing stays undefined.
    }
    throw new IdentityFetchError({ kind: "forbidden", missing });
  }
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new IdentityFetchError({
      kind: "network",
      status: resp.status,
      message: text,
    });
  }

  return (await resp.json()) as T;
}

// frontend/src/core/identity/fetcher.ts
import { type IdentityError, type Permission } from "./types";

type Listener = () => void;

/** Shared state stored on globalThis so concurrent module instances (e.g.
 *  during vi.resetModules() in tests) all operate on the same listeners set
 *  and singleflight slot.  The symbol key is collision-safe. */
const _KEY = Symbol.for("deerflow.identity.fetcherState");
type SharedState = {
  listeners: Set<Listener>;
  sessionExpiredPending: boolean;
  pendingRefresh: Promise<boolean> | null;
};

function getSharedState(): SharedState {
  const g = globalThis as Record<symbol, SharedState>;
  g[_KEY] ??= {
    listeners: new Set<Listener>(),
    sessionExpiredPending: false,
    pendingRefresh: null,
  };
  return g[_KEY];
}

/** Internal-only extension of RequestInit. Set to `true` on the refresh
 *  call itself and on the single post-refresh retry, so a real 401 in
 *  either of those code paths surfaces directly without recursing. */
type InternalInit = RequestInit & { _skipRefreshOn401?: boolean };

export function onSessionExpired(fn: Listener): () => void {
  getSharedState().listeners.add(fn);
  return () => getSharedState().listeners.delete(fn);
}

export function resetSessionExpiredListeners(): void {
  const s = getSharedState();
  s.listeners.clear();
  s.sessionExpiredPending = false;
  // Also drop any in-flight refresh promise so a subsequent test/scenario
  // that calls reset doesn't observe a stale pendingRefresh from before.
  s.pendingRefresh = null;
}

export function consumeSessionExpired(): void {
  getSharedState().sessionExpiredPending = false;
}

export function emitSessionExpired(): void {
  const s = getSharedState();
  if (s.sessionExpiredPending) return;
  s.sessionExpiredPending = true;
  for (const fn of s.listeners) fn();
}

/** Singleflight session refresh. Returns true if /api/auth/refresh succeeded.
 *  Shared by identityFetch and the LangGraph SDK transport so concurrent 401s
 *  across both fan in to a single refresh attempt. While a refresh is
 *  in-flight, all concurrent callers await the same promise. */
export async function refreshSession(): Promise<boolean> {
  const s = getSharedState();
  if (s.pendingRefresh) return s.pendingRefresh;
  s.pendingRefresh = identityFetch<unknown>("/api/auth/refresh", {
    method: "POST",
    _skipRefreshOn401: true,
  } as InternalInit)
    .then(() => true)
    .catch(() => false)
    .finally(() => {
      getSharedState().pendingRefresh = null;
    });
  return s.pendingRefresh;
}

// Backward-compat alias used by identityApi.refresh — unchanged shape.
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
  const { _skipRefreshOn401, ...realInit } = (init ?? {}) as InternalInit;

  const resp = await fetch(input, {
    credentials: "include",
    headers: {
      accept: "application/json",
      ...(realInit.body ? { "content-type": "application/json" } : {}),
      ...realInit.headers,
    },
    ...realInit,
  });

  if (resp.status === 401) {
    if (_skipRefreshOn401) {
      emitSessionExpired();
      throw new IdentityFetchError({ kind: "unauthenticated" });
    }
    const refreshed = await refreshSession();
    if (refreshed) {
      return identityFetch<T>(input, {
        ...init,
        _skipRefreshOn401: true,
      } as InternalInit);
    }
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

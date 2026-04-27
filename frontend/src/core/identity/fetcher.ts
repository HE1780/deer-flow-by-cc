// frontend/src/core/identity/fetcher.ts
import { type IdentityError, type Permission } from "./types";

type Listener = () => void;
const listeners = new Set<Listener>();
let sessionExpiredPending = false;

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

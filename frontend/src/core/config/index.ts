import { env } from "@/env";

function getBaseOrigin() {
  if (typeof window !== "undefined") {
    return window.location.origin;
  }
  // Fallback for SSR
  return "http://localhost:2026";
}

export function getBackendBaseURL() {
  if (env.NEXT_PUBLIC_BACKEND_BASE_URL) {
    return new URL(env.NEXT_PUBLIC_BACKEND_BASE_URL, getBaseOrigin())
      .toString()
      .replace(/\/+$/, "");
  } else {
    return "";
  }
}

export function getLangGraphBaseURL(isMock?: boolean) {
  if (env.NEXT_PUBLIC_LANGGRAPH_BASE_URL) {
    return new URL(
      env.NEXT_PUBLIC_LANGGRAPH_BASE_URL,
      getBaseOrigin(),
    ).toString();
  } else if (isMock) {
    if (typeof window !== "undefined") {
      return `${window.location.origin}/mock/api`;
    }
    return "http://localhost:3110/mock/api";
  } else {
    // LangGraph SDK requires a full URL, construct it from current origin.
    // Default to /api/langgraph-compat (Gateway-backed runtime) so identity
    // HMAC headers are injected on every run; the legacy /api/langgraph
    // direct-to-dev-server path bypasses Gateway and breaks the M5 identity
    // propagation contract.  Override via NEXT_PUBLIC_LANGGRAPH_BASE_URL when
    // running the standard mode (4-process layout with langgraph dev server).
    if (typeof window !== "undefined") {
      return `${window.location.origin}/api/langgraph-compat`;
    }
    // Fallback for SSR
    return "http://localhost:2026/api/langgraph-compat";
  }
}

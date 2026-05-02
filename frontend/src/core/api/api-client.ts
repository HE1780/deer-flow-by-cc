"use client";

import { Client as LangGraphClient } from "@langchain/langgraph-sdk/client";

import { emitSessionExpired, refreshSession } from "@/core/identity/fetcher";

import { getLangGraphBaseURL } from "../config";

import { sanitizeRunStreamOptions } from "./stream-mode";

/** Streaming requests must not be retried — replaying a half-consumed SSE
 *  connection corrupts message ordering. We detect them by URL pattern
 *  (primary) and accept header (defense-in-depth — `prepareFetchOptions` in
 *  langgraph-sdk 1.6.0 does NOT auto-set `accept: text/event-stream` so
 *  header detection alone is unreliable).
 *
 *  SDK 1.6.0 streaming endpoints (verified from dist/client.js):
 *    - POST `/runs/stream`                          (runs.stream stateless)
 *    - POST `/threads/{tid}/runs/stream`            (runs.stream)
 *    - GET  `/runs/{rid}/stream`                    (joinStream stateless)
 *    - GET  `/threads/{tid}/runs/{rid}/stream`      (joinStream)
 *    - GET  `/threads/{tid}/stream`                 (assistants stream)
 *
 *  Non-streaming endpoint that LOOKS similar:
 *    - GET  `/threads/{tid}/runs/{rid}/join`        (runs.join — blocking wait)
 *
 *  Match: pathname ends in `/stream` (with optional query string). Must NOT
 *  match `/runs/{rid}/join`, or 401s on runs.join would skip refresh-retry. */
const STREAM_PATH_RE = /\/stream(\?|$)/;

function isStreamingRequest(input: RequestInfo | URL, init?: RequestInit): boolean {
  const url =
    typeof input === "string"
      ? input
      : input instanceof URL
        ? input.href
        : input.url;
  if (STREAM_PATH_RE.test(url)) return true;

  const headers = init?.headers;
  if (!headers) return false;
  const recordHeaders = headers as Record<string, string>;
  const accept =
    headers instanceof Headers
      ? headers.get("accept")
      : Array.isArray(headers)
        ? headers.find(([k]) => k.toLowerCase() === "accept")?.[1]
        : recordHeaders.accept ?? recordHeaders.Accept;
  return typeof accept === "string" && accept.includes("text/event-stream");
}

/** Wraps fetch for the LangGraph SDK so SDK-originated 401s share the same
 *  singleflight refresh-and-retry behavior as identityFetch. Streaming
 *  requests fall through unchanged. */
async function sdkFetchWithRefresh(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  const resp = await fetch(input, init);
  if (resp.status !== 401) return resp;
  if (isStreamingRequest(input, init)) return resp;

  const refreshed = await refreshSession();
  if (!refreshed) {
    emitSessionExpired();
    return resp;
  }
  const retry = await fetch(input, init);
  if (retry.status === 401) emitSessionExpired();
  return retry;
}

function createCompatibleClient(isMock?: boolean): LangGraphClient {
  const client = new LangGraphClient({
    apiUrl: getLangGraphBaseURL(isMock),
    // maxConcurrency: Infinity so all concurrent SDK calls pass through
    // sdkFetchWithRefresh in the same microtask batch.  The default SDK value
    // of 4 would serialise them and break the singleflight refresh guarantee
    // (the 5th queued call would start a second refresh after the first
    // completes and clears pendingRefresh).
    callerOptions: { fetch: sdkFetchWithRefresh, maxConcurrency: Infinity },
  });

  // Existing wrappers for streamMode sanitization — unchanged.
  const originalRunStream = client.runs.stream.bind(client.runs);
  client.runs.stream = ((threadId, assistantId, payload) =>
    originalRunStream(
      threadId,
      assistantId,
      sanitizeRunStreamOptions(payload),
    )) as typeof client.runs.stream;

  const originalJoinStream = client.runs.joinStream.bind(client.runs);
  client.runs.joinStream = ((threadId, runId, options) =>
    originalJoinStream(
      threadId,
      runId,
      sanitizeRunStreamOptions(options),
    )) as typeof client.runs.joinStream;

  return client;
}

const _clients = new Map<string, LangGraphClient>();
export function getAPIClient(isMock?: boolean): LangGraphClient {
  const cacheKey = isMock ? "mock" : "default";
  let client = _clients.get(cacheKey);

  if (!client) {
    client = createCompatibleClient(isMock);
    _clients.set(cacheKey, client);
  }

  return client;
}

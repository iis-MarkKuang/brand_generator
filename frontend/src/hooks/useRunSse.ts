import { useEffect, useRef, useState } from "react";
import type { SseEvent } from "../types";

interface Options {
  onEvent?: (e: SseEvent) => void;
  enabled?: boolean;
}

/**
 * Subscribe to the SSE stream for a run. Falls back to no-op when disabled.
 * Auto-closes when the server sends the `done` event.
 */
export function useRunSse(runId: string | undefined, { onEvent, enabled = true }: Options) {
  const [closed, setClosed] = useState(false);
  const cbRef = useRef(onEvent);
  cbRef.current = onEvent;

  useEffect(() => {
    if (!runId || !enabled) return;
    setClosed(false);
    const es = new EventSource(`/api/runs/${runId}/events`);
    es.onmessage = (msg) => {
      try {
        const e = JSON.parse(msg.data) as SseEvent;
        cbRef.current?.(e);
        if ((e as { event?: string }).event === "done") {
          es.close();
          setClosed(true);
        }
      } catch {
        /* ignore malformed line */
      }
    };
    es.onerror = () => {
      // browser will auto-reconnect; mark closed only if we already saw done
    };
    return () => es.close();
  }, [runId, enabled]);

  return { closed };
}

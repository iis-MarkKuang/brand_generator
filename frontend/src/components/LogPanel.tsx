import { useEffect, useRef } from "react";
import type { SseEvent } from "../types";

function isOrch(e: SseEvent): e is import("../types").SseOrchestratorEvent {
  return (e as { action?: string }).action !== undefined;
}

export default function LogPanel({ events }: { events: SseEvent[] }) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events.length]);

  return (
    <div className="bg-ink border border-edge rounded-xl flex flex-col h-72">
      <div className="px-4 py-2 border-b border-edge text-xs uppercase tracking-wider text-muted flex items-center justify-between">
        <span>Live event stream</span>
        <span className="font-mono text-slate-400">{events.length}</span>
      </div>
      <div className="flex-1 overflow-y-auto scroll-thin p-3 space-y-1 font-mono text-xs">
        {events.length === 0 && (
          <div className="text-muted">waiting for events…</div>
        )}
        {events.map((e, i) => {
          if (isOrch(e)) {
            const swap = e.action?.startsWith("request_vram:");
            return (
              <div key={i} className={swap ? "text-accent" : "text-slate-300"}>
                <span className="text-muted">{e.t?.slice(11) ?? "--:--:--"}</span>{" "}
                <span className="font-semibold">{e.action}</span>{" "}
                <span className="text-muted">{e.reason}</span>
                {e.vram_before_gb != null && e.vram_after_gb != null && (
                  <span className="text-emerald-400">
                    {" "}
                    {e.vram_before_gb}→{e.vram_after_gb}GB
                  </span>
                )}
              </div>
            );
          }
          const ev = e as { event?: string; asset_id?: string; status?: string };
          return (
            <div key={i} className="text-sky-300">
              <span className="font-semibold">{ev.event}</span>{" "}
              {ev.asset_id ?? ev.status ?? ""}
            </div>
          );
        })}
        <div ref={endRef} />
      </div>
    </div>
  );
}

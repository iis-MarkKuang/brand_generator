import { useMemo } from "react";
import type { SseEvent, SseOrchestratorEvent } from "../types";

const TOTAL_VRAM_GB = 120; // GB10 Grace-Blackwell unified memory

interface SwapEntry {
  model: string;
  reason: string;
  vramBefore?: number;
  vramAfter?: number;
  latency?: number;
  t?: string;
}

interface VramDashboardProps {
  events: SseEvent[];
}

export default function VramDashboard({ events }: VramDashboardProps) {
  const orchEvents = useMemo(
    () =>
      events.filter(
        (e): e is SseOrchestratorEvent =>
          "action" in e && typeof (e as SseOrchestratorEvent).action === "string",
      ),
    [events],
  );

  const swaps = useMemo<SwapEntry[]>(
    () =>
      orchEvents
        .filter((e) => e.action?.startsWith("request_vram:"))
        .map((e) => ({
          model: e.action!.split(":")[1] ?? "?",
          reason: e.reason ?? "",
          vramBefore: e.vram_before_gb ?? undefined,
          vramAfter: e.vram_after_gb ?? undefined,
          latency: e.latency_s ?? undefined,
          t: e.t,
        })),
    [orchEvents],
  );

  const latestVram = useMemo(() => {
    for (let i = orchEvents.length - 1; i >= 0; i--) {
      const v = orchEvents[i].vram_after_gb;
      if (v != null) return v;
    }
    return undefined;
  }, [orchEvents]);

  const activeModel = swaps.length > 0 ? swaps[swaps.length - 1].model : null;
  const usedGb = latestVram ? TOTAL_VRAM_GB - latestVram : 0;
  const freePct = latestVram ? (latestVram / TOTAL_VRAM_GB) * 100 : 100;
  const usedPct = 100 - freePct;

  const reasoningCount = orchEvents.filter((e) => e.action === "reasoning").length;
  const renderCount = swaps.filter((s) => s.model === "comfyui").length;
  const ollamaCount = swaps.filter((s) => s.model === "ollama").length;

  const nimCount = orchEvents.filter((e) => e.backend === "nim").length;

  return (
    <div className="bg-panel border border-edge rounded-xl p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-display text-sm text-white">DGX Spark · VRAM Orchestration</h3>
        <span className="text-[10px] font-mono text-muted">GB10 · 120 GB unified</span>
      </div>

      {/* VRAM gauge */}
      <div className="mb-5">
        <div className="flex justify-between text-xs text-muted mb-1.5">
          <span>Unified Memory</span>
          <span className="font-mono">
            {latestVram != null ? `${latestVram.toFixed(1)} GB free` : "—"}
          </span>
        </div>
        <div className="relative h-7 bg-edge rounded-full overflow-hidden">
          {/* used segment (animated) */}
          <div
            className="absolute left-0 top-0 h-full rounded-l-full transition-all duration-700 ease-out"
            style={{
              width: `${usedPct}%`,
              background:
                "linear-gradient(90deg, rgba(59,130,246,0.7) 0%, rgba(16,185,129,0.7) 100%)",
            }}
          />
          {/* free segment */}
          <div
            className="absolute right-0 top-0 h-full rounded-r-full transition-all duration-700 ease-out"
            style={{
              width: `${freePct}%`,
              background: "rgba(148,163,184,0.12)",
            }}
          />
          {/* tick marks at 25/50/75% */}
          {[25, 50, 75].map((pct) => (
            <div
              key={pct}
              className="absolute top-0 h-full w-px bg-edge/60"
              style={{ left: `${pct}%` }}
            />
          ))}
          {/* center label */}
          <div className="absolute inset-0 flex items-center justify-center text-xs font-semibold text-white/90 mix-blend-difference">
            {usedGb.toFixed(0)} GB used / {TOTAL_VRAM_GB} GB
          </div>
        </div>
        <div className="flex justify-between text-[10px] text-muted mt-1">
          <span>0 GB</span>
          <span>60 GB</span>
          <span>120 GB</span>
        </div>
      </div>

      {/* Active model indicator */}
      <div className="flex items-center gap-3 mb-4">
        <div className="text-xs text-muted">Active:</div>
        <div
          className={`text-sm font-semibold px-3 py-1 rounded-full flex items-center gap-1.5 ${
            activeModel === "ollama"
              ? "bg-blue-500/20 text-blue-300"
              : activeModel === "comfyui"
                ? "bg-green-500/20 text-green-300"
                : "bg-edge text-muted"
          }`}
        >
          {activeModel === "ollama" && (
            <>
              <span className="w-2 h-2 rounded-full bg-blue-400 animate-pulse" />
              Ollama · Nemotron (30B)
            </>
          )}
          {activeModel === "comfyui" && (
            <>
              <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
              ComfyUI · FLUX
            </>
          )}
          {!activeModel && <span>idle</span>}
        </div>
        {nimCount > 0 && (
          <div className="text-[10px] text-amber-300/70 font-mono">
            NIM failover ×{nimCount}
          </div>
        )}
      </div>

      {/* Swap timeline */}
      <div className="text-xs uppercase tracking-wider text-muted mb-2">
        Model swap timeline
      </div>
      <div className="space-y-1 max-h-44 overflow-y-auto pr-1">
        {swaps.map((s, i) => (
          <div key={i} className="flex items-center gap-2 text-xs py-0.5">
            <div
              className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${
                s.model === "ollama" ? "bg-blue-400" : "bg-green-400"
              }`}
            />
            <span className="font-mono text-slate-300 w-16 flex-shrink-0">{s.model}</span>
            <span className="text-muted truncate flex-1">{s.reason}</span>
            {s.vramAfter != null && (
              <span className="text-muted font-mono flex-shrink-0">
                {s.vramAfter.toFixed(0)} GB
              </span>
            )}
            {s.latency != null && s.latency > 0 && (
              <span className="text-accent/70 font-mono flex-shrink-0">
                {s.latency.toFixed(1)}s
              </span>
            )}
          </div>
        ))}
        {swaps.length === 0 && (
          <div className="text-muted text-xs italic">Waiting for pipeline to start…</div>
        )}
      </div>

      {/* Counters */}
      <div className="grid grid-cols-4 gap-2 mt-4 pt-3 border-t border-edge text-center">
        {[
          ["Swaps", swaps.length, "text-white"],
          ["Ollama", ollamaCount, "text-blue-300"],
          ["Renders", renderCount, "text-green-300"],
          ["VLM", reasoningCount, "text-accent"],
        ].map(([label, val, color]) => (
          <div key={label as string}>
            <div className={`text-lg font-display ${color as string}`}>{val as number}</div>
            <div className="text-[10px] text-muted">{label as string}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

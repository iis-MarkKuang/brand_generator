import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { assetUrl, getBrandDna, getRun } from "../api";
import type { AssetType, BrandDna, KitAsset, SseEvent } from "../types";
import { useRunSse } from "../hooks/useRunSse";
import AssetTile from "./AssetTile";
import DnaCard from "./DnaCard";
import LogPanel from "./LogPanel";

interface LiveAsset {
  type: AssetType;
  status: "planned" | "rendering" | "approved" | "failed";
  score?: number | null;
  error?: string | null;
  imgUrl?: string;
}

function typeFromId(id: string): AssetType {
  const base = id.split("__")[0];
  return base as AssetType;
}

export default function LiveView() {
  const { runId } = useParams<{ runId: string }>();
  const [events, setEvents] = useState<SseEvent[]>([]);
  const [renderingId, setRenderingId] = useState<string | null>(null);
  const [latestImg, setLatestImg] = useState<Record<string, string>>({});

  const run = useQuery({
    queryKey: ["run", runId],
    queryFn: () => getRun(runId!),
    enabled: !!runId,
    refetchInterval: (q) => (q.state.data?.stage === "assembled" ? false : 2000),
  });

  const dna = useQuery<BrandDna>({
    queryKey: ["dna", runId],
    queryFn: () => getBrandDna(runId!),
    enabled: !!runId,
    retry: false,
    refetchInterval: (q) => (q.state.data ? false : 3000),
  });

  useRunSse(runId, {
    onEvent: (e) => {
      setEvents((prev) => [...prev, e]);
      const orch = e as { action?: string; reason?: string };
      if (orch.reason?.startsWith("render:")) {
        setRenderingId(orch.reason.split(":")[1]);
      }
      const asset = e as { event?: string; asset_id?: string };
      if (asset.event === "asset" && asset.asset_id) {
        setLatestImg((prev) => ({
          ...prev,
          [typeFromId(asset.asset_id!)]: assetUrl(runId!, `${asset.asset_id}.png`),
        }));
      }
    },
  });

  const manifest = run.data?.manifest;
  const stage = run.data?.stage ?? "starting";

  const lanes = useMemo<LiveAsset[]>(() => {
    if (manifest) {
      return manifest.assets.map((a: KitAsset) => ({
        type: a.type,
        status: a.status,
        score: a.final_score,
        error: a.error,
        imgUrl: a.status === "approved" ? assetUrl(runId!, `${a.id}.png`) : latestImg[a.type],
      }));
    }
    const seen = new Map<AssetType, LiveAsset>();
    for (const id of Object.keys(latestImg)) {
      const t = typeFromId(id);
      seen.set(t, { type: t, status: "rendering", imgUrl: latestImg[t] });
    }
    if (renderingId) {
      const t = typeFromId(renderingId);
      if (!seen.has(t)) seen.set(t, { type: t, status: "rendering" });
    }
    return [...seen.values()];
  }, [manifest, latestImg, renderingId, runId]);

  const opt = manifest?.optimization_stats;
  const assembled = stage === "assembled";

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-2xl text-white">Live Run</h1>
          <div className="text-xs font-mono text-muted mt-0.5">{runId}</div>
        </div>
        <div className="flex items-center gap-3">
          <span
            className={`text-sm px-3 py-1 rounded-full ${
              assembled
                ? "bg-emerald-500/20 text-emerald-300"
                : "bg-edge text-slate-200"
            }`}
          >
            {stage}
          </span>
          {assembled && (
            <Link
              to={`/kit/${runId}`}
              className="text-sm bg-accent hover:bg-accent/90 text-white font-semibold rounded-lg px-4 py-1.5"
            >
              View Brand Kit →
            </Link>
          )}
        </div>
      </div>

      <div className="grid lg:grid-cols-2 gap-6">
        <div className="space-y-4">
          {dna.data ? (
            <DnaCard dna={dna.data} />
          ) : (
            <div className="bg-panel border border-edge rounded-xl p-5 text-muted text-sm">
              Analyzing reference image with Stepfun VLM…
            </div>
          )}

          <div>
            <div className="text-xs uppercase tracking-wider text-muted mb-2">
              Asset lanes
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              {lanes.length === 0 && (
                <div className="col-span-full text-muted text-sm">
                  Planning asset manifest with the Art Director…
                </div>
              )}
              {lanes.map((a) => (
                <AssetTile
                  key={a.type}
                  type={a.type}
                  status={a.status}
                  score={a.score}
                  error={a.error}
                  imgUrl={a.imgUrl}
                />
              ))}
            </div>
          </div>
        </div>

        <div className="space-y-4">
          <LogPanel events={events} />
          {opt && (
            <div className="bg-panel border border-edge rounded-xl p-4 grid grid-cols-3 gap-3 text-center">
              {[
                ["VRAM swaps", opt.vram_swaps],
                ["VLM calls", opt.total_vlm_calls],
                ["Renders", opt.total_renders],
              ].map(([label, val]) => (
                <div key={label as string}>
                  <div className="text-2xl font-display text-accent">{val as number}</div>
                  <div className="text-xs text-muted">{label}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

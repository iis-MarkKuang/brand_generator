import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { getBrandDna, getRun, kitFileUrl, kitZipUrl } from "../api";
import AssetTile from "./AssetTile";
import PaletteStrip from "./PaletteStrip";

export default function KitBoard() {
  const { runId } = useParams<{ runId: string }>();
  const run = useQuery({
    queryKey: ["run", runId],
    queryFn: () => getRun(runId!),
    enabled: !!runId,
  });
  const dna = useQuery({
    queryKey: ["dna", runId],
    queryFn: () => getBrandDna(runId!),
    enabled: !!runId,
    retry: false,
  });

  const manifest = run.data?.manifest;
  if (!manifest) {
    return (
      <div className="bg-panel border border-edge rounded-2xl p-8 text-center text-muted">
        {run.isLoading ? "Loading kit…" : "Kit not ready."}{" "}
        <Link to={`/run/${runId}`} className="text-accent underline">
          back to live view
        </Link>
      </div>
    );
  }

  const opt = manifest.optimization_stats;
  const approved = manifest.assets.filter((a) => a.status === "approved").length;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl text-white">{manifest.brand_name}</h1>
          <div className="text-xs font-mono text-muted mt-0.5">
            {runId} · {manifest.status} · {approved}/{manifest.assets.length} approved ·{" "}
            {manifest.total_latency_s}s
          </div>
        </div>
        <a
          href={kitZipUrl(runId!)}
          className="bg-accent hover:bg-accent/90 text-white font-semibold rounded-lg px-4 py-2 text-sm"
        >
          ↓ Download kit.zip
        </a>
      </div>

      <div className="bg-panel border border-edge rounded-xl p-4">
        <div className="text-xs uppercase tracking-wider text-muted mb-2">Palette</div>
        <PaletteStrip palette={manifest.palette} />
      </div>

      <div>
        <div className="text-xs uppercase tracking-wider text-muted mb-2">Brand assets</div>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
          {manifest.assets.map((a) => (
            <AssetTile
              key={a.id}
              type={a.type}
              status={a.status}
              score={a.final_score}
              error={a.error}
              imgUrl={
                a.status === "approved" ? kitFileUrl(runId!, `${a.id}.png`) : undefined
              }
            />
          ))}
        </div>
      </div>

      <div className="grid lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 bg-panel border border-edge rounded-xl p-5">
          <div className="flex items-center justify-between mb-3">
            <div className="text-xs uppercase tracking-wider text-muted">
              Brand guide preview
            </div>
            <a
              href={`/api/runs/${runId}/brand_guide`}
              className="text-xs text-accent underline"
              target="_blank"
              rel="noreferrer"
            >
              open raw
            </a>
          </div>
          <BrandGuidePreview runId={runId!} />
        </div>

        <div className="bg-panel border border-edge rounded-xl p-5 space-y-3">
          <div className="text-xs uppercase tracking-wider text-muted">
            Optimization stats
          </div>
          <dl className="space-y-2 text-sm">
            {[
              ["VRAM swaps", opt.vram_swaps],
              ["Total VLM calls", opt.total_vlm_calls],
              ["Total renders", opt.total_renders],
              ["Critic low / med / high", `${opt.critic_effort_low_count} / ${opt.critic_effort_medium_count} / ${opt.critic_effort_high_count}`],
              ["Local reasoning calls", opt.routing_local_count],
              ["DNA cache hit", opt.brand_dna_cache_hit ? "yes" : "no"],
            ].map(([k, v]) => (
              <div key={k as string} className="flex justify-between gap-4">
                <dt className="text-muted">{k}</dt>
                <dd className="font-mono text-slate-200">{v as string | number}</dd>
              </div>
            ))}
          </dl>
          {dna.data && (
            <div className="pt-3 border-t border-edge">
              <div className="text-xs uppercase tracking-wider text-muted mb-1.5">
                Personality
              </div>
              <p className="text-sm text-slate-200 italic">{dna.data.personality}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function BrandGuidePreview({ runId }: { runId: string }) {
  const guide = useQuery({
    queryKey: ["guide", runId],
    queryFn: async () => {
      const res = await fetch(`/api/runs/${runId}/brand_guide`);
      if (!res.ok) return "";
      return res.text();
    },
    enabled: !!runId,
  });
  if (!guide.data) return <div className="text-muted text-sm">Loading…</div>;
  return (
    <pre className="text-sm text-slate-200 whitespace-pre-wrap font-sans leading-relaxed max-h-80 overflow-y-auto scroll-thin">
      {guide.data}
    </pre>
  );
}

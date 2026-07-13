import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { getHealth, startRun } from "../api";
import type { AssetType } from "../types";

const ALL_ASSETS: { id: AssetType; label: string }[] = [
  { id: "logo", label: "Logo" },
  { id: "hero_banner", label: "Hero Banner" },
  { id: "social_square", label: "Social Square" },
  { id: "product_mockup", label: "Product Mockup" },
  { id: "business_card", label: "Business Card" },
];

export default function NewKitForm() {
  const navigate = useNavigate();
  const [brief, setBrief] = useState(
    "A warm, craft-first small-batch coffee roaster. Hand-drawn serif, earthy palette of espresso and oat cream.",
  );
  const [brandName, setBrandName] = useState("Ember & Oat");
  const [file, setFile] = useState<File | null>(null);
  const [assets, setAssets] = useState<Set<AssetType>>(
    new Set<AssetType>(["logo", "social_square", "hero_banner"]),
  );
  const [maxRetries, setMaxRetries] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const health = useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
    refetchInterval: 5000,
  });

  function toggle(a: AssetType) {
    setAssets((prev) => {
      const next = new Set(prev);
      if (next.has(a)) next.delete(a);
      else next.add(a);
      return next;
    });
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!file) {
      setError("Please add a reference image.");
      return;
    }
    if (assets.size === 0) {
      setError("Select at least one asset type.");
      return;
    }
    setSubmitting(true);
    try {
      const { run_id } = await startRun({
        brief,
        brand_name: brandName,
        assets: [...assets],
        max_retries: maxRetries,
        image: file,
      });
      navigate(`/run/${run_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  const deps = health.data?.deps;

  return (
    <div className="grid lg:grid-cols-3 gap-6">
      <form
        onSubmit={onSubmit}
        className="lg:col-span-2 bg-panel border border-edge rounded-2xl p-6 space-y-5"
      >
        <div>
          <h1 className="font-display text-2xl text-white">Forge a Brand Kit</h1>
          <p className="text-sm text-muted mt-1">
            Upload a reference image + brief. The Art Director plans, FLUX renders, and the
            Critic reviews — live on the Spark.
          </p>
        </div>

        <div className="grid sm:grid-cols-2 gap-4">
          <label className="block">
            <span className="text-xs uppercase tracking-wider text-muted">Brand name</span>
            <input
              value={brandName}
              onChange={(e) => setBrandName(e.target.value)}
              className="mt-1 w-full bg-ink border border-edge rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-accent"
            />
          </label>
          <label className="block">
            <span className="text-xs uppercase tracking-wider text-muted">
              Max retries / asset
            </span>
            <input
              type="number"
              min={0}
              max={3}
              value={maxRetries}
              onChange={(e) => setMaxRetries(Number(e.target.value))}
              className="mt-1 w-full bg-ink border border-edge rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-accent"
            />
          </label>
        </div>

        <label className="block">
          <span className="text-xs uppercase tracking-wider text-muted">Brand brief</span>
          <textarea
            value={brief}
            onChange={(e) => setBrief(e.target.value)}
            rows={3}
            className="mt-1 w-full bg-ink border border-edge rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-accent resize-none"
          />
        </label>

        <label
          className="block border-2 border-dashed border-edge rounded-xl p-6 text-center cursor-pointer hover:border-accent transition"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            const f = e.dataTransfer.files[0];
            if (f) setFile(f);
          }}
        >
          <input
            type="file"
            accept="image/*"
            className="hidden"
            onChange={(e) => e.target.files?.[0] && setFile(e.target.files[0])}
          />
          {file ? (
            <div className="text-sm">
              <div className="text-slate-200">{file.name}</div>
              <div className="text-xs text-muted">
                {Math.round(file.size / 1024)} KB · click to replace
              </div>
            </div>
          ) : (
            <div className="text-sm text-muted">
              Drag & drop a reference image, or click to browse
            </div>
          )}
        </label>

        <div>
          <span className="text-xs uppercase tracking-wider text-muted">Assets</span>
          <div className="flex flex-wrap gap-2 mt-2">
            {ALL_ASSETS.map((a) => {
              const on = assets.has(a.id);
              return (
                <button
                  type="button"
                  key={a.id}
                  onClick={() => toggle(a.id)}
                  className={`text-sm px-3 py-1.5 rounded-lg border transition ${
                    on
                      ? "bg-accent/20 border-accent text-white"
                      : "bg-ink border-edge text-muted hover:text-slate-200"
                  }`}
                >
                  {a.label}
                </button>
              );
            })}
          </div>
        </div>

        {error && (
          <div className="text-sm text-rose-300 bg-rose-500/10 border border-rose-500/30 rounded-lg px-3 py-2">
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="w-full bg-accent hover:bg-accent/90 disabled:opacity-50 text-white font-semibold rounded-lg py-2.5 transition"
        >
          {submitting ? "Starting…" : "Generate Brand Kit"}
        </button>
      </form>

      <aside className="space-y-4">
        <div className="bg-panel border border-edge rounded-2xl p-5">
          <div className="text-xs uppercase tracking-wider text-muted mb-3">
            Local services
          </div>
          <ul className="space-y-2 text-sm">
            {[
              ["Ollama (reasoning)", deps?.ollama],
              ["ComfyUI (FLUX)", deps?.comfyui],
              ["Stepfun (VLM)", deps?.stepfun],
            ].map(([label, ok]) => (
              <li key={label as string} className="flex items-center gap-2">
                <span
                  className={`h-2 w-2 rounded-full ${
                    ok ? "bg-emerald-400" : "bg-rose-400"
                  }`}
                />
                <span className="text-slate-200">{label}</span>
                <span className="text-muted text-xs ml-auto">
                  {ok ? "ready" : "down"}
                </span>
              </li>
            ))}
          </ul>
        </div>
        <div className="bg-panel border border-edge rounded-2xl p-5 text-sm text-muted">
          <p>
            One run at a time on the GB10 unified memory. The Art Director swaps Ollama
            out before each FLUX render — watch the live VRAM-swap log.
          </p>
        </div>
      </aside>
    </div>
  );
}

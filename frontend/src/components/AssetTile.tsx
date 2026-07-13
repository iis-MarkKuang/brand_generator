import type { AssetType } from "../types";
import { assetLabel } from "../assetLabels";

interface Props {
  type: AssetType;
  status: "approved" | "failed" | "rendering" | "planned";
  score?: number | null;
  error?: string | null;
  imgUrl?: string;
}

export default function AssetTile({ type, status, score, error, imgUrl }: Props) {
  return (
    <div className="bg-panel border border-edge rounded-xl overflow-hidden flex flex-col">
      <div className="aspect-square bg-ink relative flex items-center justify-center">
        {status === "rendering" && <div className="absolute inset-0 shimmer" />}
        {status === "approved" && imgUrl && (
          <img src={imgUrl} alt={type} className="w-full h-full object-contain" />
        )}
        {status === "failed" && (
          <div className="text-center px-3">
            <div className="text-rose-400 text-2xl mb-1">✕</div>
            <div className="text-xs text-muted">generation failed</div>
          </div>
        )}
        {status === "planned" && (
          <div className="text-muted text-sm">queued</div>
        )}
        <span className="absolute top-2 left-2 text-[10px] uppercase tracking-wider text-muted bg-black/40 px-1.5 py-0.5 rounded">
          {assetLabel(type)}
        </span>
        {score != null && (
          <span
            className={`absolute top-2 right-2 text-[10px] font-mono px-1.5 py-0.5 rounded ${
              score >= 70
                ? "bg-emerald-500/20 text-emerald-300"
                : "bg-rose-500/20 text-rose-300"
            }`}
          >
            {score}
          </span>
        )}
      </div>
      {error && (
        <div className="px-3 py-2 text-xs text-muted line-clamp-2 border-t border-edge">
          {error}
        </div>
      )}
    </div>
  );
}

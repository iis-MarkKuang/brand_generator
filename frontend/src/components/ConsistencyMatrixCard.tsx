import type { ConsistencyMatrix } from "../types";

interface Props {
  matrix: ConsistencyMatrix;
}

function scoreColor(score: number): string {
  if (score >= 0.8) return "bg-emerald-500/30 text-emerald-300";
  if (score >= 0.6) return "bg-amber-500/30 text-amber-300";
  return "bg-red-500/30 text-red-300";
}

function scoreBar(score: number): string {
  if (score >= 0.8) return "bg-emerald-400";
  if (score >= 0.6) return "bg-amber-400";
  return "bg-red-400";
}

export default function ConsistencyMatrixCard({ matrix }: Props) {
  const overallPct = Math.round(matrix.overall_score * 100);

  return (
    <div className="bg-panel border border-edge rounded-xl p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-display text-sm text-white">VLM Cross-Asset Consistency</h3>
        <span
          className={`text-xs font-semibold px-2.5 py-1 rounded-full ${scoreColor(matrix.overall_score)}`}
        >
          {overallPct}%
        </span>
      </div>

      {/* Overall score bar */}
      <div className="mb-4">
        <div className="flex justify-between text-[10px] text-muted mb-1">
          <span>Overall coherence</span>
          <span>{overallPct}/100</span>
        </div>
        <div className="h-2.5 bg-edge rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-700 ${scoreBar(matrix.overall_score)}`}
            style={{ width: `${overallPct}%` }}
          />
        </div>
      </div>

      {/* Per-dimension heatmap */}
      <div className="space-y-2.5 mb-4">
        {matrix.dimensions.map((d) => {
          const pct = Math.round(d.score * 100);
          return (
            <div key={d.dimension}>
              <div className="flex items-center justify-between text-xs mb-1">
                <span className="text-slate-300 capitalize">{d.dimension}</span>
                <span className={`font-mono font-semibold ${scoreColor(d.score).split(" ")[1]}`}>
                  {pct}%
                </span>
              </div>
              <div className="h-2 bg-edge rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-500 ${scoreBar(d.score)}`}
                  style={{ width: `${pct}%` }}
                />
              </div>
              {d.notes && (
                <div className="text-[10px] text-muted mt-0.5 italic">{d.notes}</div>
              )}
            </div>
          );
        })}
        {matrix.dimensions.length === 0 && (
          <div className="text-muted text-xs italic">No dimension data.</div>
        )}
      </div>

      {/* Summary */}
      {matrix.summary && (
        <div className="pt-3 border-t border-edge">
          <div className="text-[10px] uppercase tracking-wider text-muted mb-1">
            VLM assessment
          </div>
          <p className="text-sm text-slate-200 italic">{matrix.summary}</p>
        </div>
      )}

      {/* Assets compared */}
      {matrix.asset_ids.length > 0 && (
        <div className="pt-2 mt-2 border-t border-edge">
          <div className="text-[10px] uppercase tracking-wider text-muted mb-1">
            Assets compared ({matrix.asset_ids.length})
          </div>
          <div className="flex flex-wrap gap-1.5">
            {matrix.asset_ids.map((id) => (
              <span
                key={id}
                className="text-[10px] font-mono px-2 py-0.5 rounded bg-edge text-slate-300"
              >
                {id}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

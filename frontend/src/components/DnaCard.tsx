import type { BrandDna } from "../types";
import PaletteStrip from "./PaletteStrip";

export default function DnaCard({ dna }: { dna: BrandDna }) {
  return (
    <div className="bg-panel border border-edge rounded-xl p-5 space-y-4">
      <div>
        <h3 className="font-display text-lg text-white">{dna.brand_name}</h3>
        <p className="text-sm text-muted italic">{dna.personality}</p>
      </div>
      <div>
        <div className="text-xs uppercase tracking-wider text-muted mb-2">Palette</div>
        <PaletteStrip palette={dna.palette.map((c) => c.hex)} />
        <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2">
          {dna.palette.map((c) => (
            <span key={c.hex} className="text-xs text-muted">
              {c.name} <span className="font-mono text-slate-300">{c.hex}</span>
            </span>
          ))}
        </div>
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <div className="text-xs uppercase tracking-wider text-muted mb-1.5">Mood</div>
          <div className="flex flex-wrap gap-1.5">
            {dna.mood.map((m) => (
              <span
                key={m}
                className="text-xs px-2 py-0.5 rounded-full bg-edge text-slate-200"
              >
                {m}
              </span>
            ))}
          </div>
        </div>
        <div>
          <div className="text-xs uppercase tracking-wider text-muted mb-1.5">Typography</div>
          <div className="text-sm text-slate-200">
            <span className="font-display">{dna.typography_pairs.headline}</span>
            <span className="text-muted"> · </span>
            <span>{dna.typography_pairs.body}</span>
          </div>
          <div className="text-xs text-muted mt-0.5">class: {dna.typography_class}</div>
        </div>
      </div>
      <div>
        <div className="text-xs uppercase tracking-wider text-muted mb-1.5">
          Visual keywords
        </div>
        <div className="flex flex-wrap gap-1.5">
          {dna.visual_keywords.map((k) => (
            <span
              key={k}
              className="text-xs px-2 py-0.5 rounded border border-edge text-slate-300"
            >
              {k}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

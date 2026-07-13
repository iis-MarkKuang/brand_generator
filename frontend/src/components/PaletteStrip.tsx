export default function PaletteStrip({
  palette,
  size = "md",
}: {
  palette: string[];
  size?: "sm" | "md";
}) {
  const h = size === "sm" ? "h-6" : "h-12";
  return (
    <div className="flex rounded-lg overflow-hidden border border-edge">
      {palette.length === 0 && <div className={`${h} w-full bg-edge`} />}
      {palette.map((hex) => (
        <div
          key={hex}
          className={`${h} flex-1 flex items-end justify-center`}
          style={{ backgroundColor: hex }}
          title={hex}
        >
          <span
            className="text-[10px] font-mono mb-0.5 px-1 rounded bg-black/30 text-white/90"
            style={{ mixBlendMode: "normal" }}
          >
            {hex}
          </span>
        </div>
      ))}
    </div>
  );
}

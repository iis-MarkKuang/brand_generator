import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { listRuns } from "../api";

export default function History() {
  const { data, isLoading, refetch } = useQuery({
    queryKey: ["runs"],
    queryFn: listRuns,
    refetchInterval: 5000,
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="font-display text-2xl text-white">Run History</h1>
        <button
          onClick={() => refetch()}
          className="text-sm text-muted hover:text-slate-200"
        >
          refresh
        </button>
      </div>

      {isLoading && <div className="text-muted text-sm">Loading…</div>}

      {data && data.length === 0 && (
        <div className="bg-panel border border-edge rounded-xl p-6 text-muted text-sm">
          No runs yet. <Link to="/" className="text-accent underline">Create a kit</Link>.
        </div>
      )}

      <ul className="space-y-2">
        {data?.map((r) => {
          const date = new Date(r.created_at * 1000);
          const target = r.status === "assembled" ? `/kit/${r.run_id}` : `/run/${r.run_id}`;
          return (
            <li key={r.run_id}>
              <Link
                to={target}
                className="flex items-center justify-between bg-panel border border-edge rounded-xl px-4 py-3 hover:border-accent transition"
              >
                <div>
                  <div className="font-mono text-sm text-slate-200">{r.run_id}</div>
                  <div className="text-xs text-muted">
                    {date.toLocaleString()}
                  </div>
                </div>
                <span
                  className={`text-xs px-2 py-0.5 rounded-full ${
                    r.status === "assembled"
                      ? "bg-emerald-500/20 text-emerald-300"
                      : "bg-edge text-slate-300"
                  }`}
                >
                  {r.status}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

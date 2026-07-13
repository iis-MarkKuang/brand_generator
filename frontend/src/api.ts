import type {
  BrandDna,
  HealthDeps,
  RunState,
  RunSummary,
} from "./types";

const base = "";

async function asJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export interface StartRunInput {
  brief: string;
  brand_name: string;
  assets: string[];
  max_retries: number;
  image: File;
}

export async function startRun(input: StartRunInput): Promise<{ run_id: string }> {
  const form = new FormData();
  form.set("brief", input.brief);
  form.set("brand_name", input.brand_name);
  form.set("assets", input.assets.join(","));
  form.set("max_retries", String(input.max_retries));
  form.set("image", input.image);
  const res = await fetch(`${base}/api/runs`, { method: "POST", body: form });
  if (res.status === 409) {
    const body = await res.json();
    const active = body?.detail?.active_run_id ?? "unknown";
    throw new Error(`A run is already active (${active}). Wait for it to finish.`);
  }
  return asJson(res);
}

export async function getRun(runId: string): Promise<RunState> {
  return asJson(await fetch(`${base}/api/runs/${runId}`));
}

export async function getBrandDna(runId: string): Promise<BrandDna> {
  return asJson(await fetch(`${base}/api/runs/${runId}/brand_dna`));
}

export async function listRuns(): Promise<RunSummary[]> {
  const body = await asJson<{ runs: RunSummary[] }>(
    await fetch(`${base}/api/runs`),
  );
  return body.runs;
}

export async function getHealth(): Promise<{ status: string; deps: HealthDeps }> {
  return asJson(await fetch(`${base}/api/health`));
}

export function assetUrl(runId: string, name: string): string {
  return `${base}/api/runs/${runId}/assets/${name}`;
}

export function kitZipUrl(runId: string): string {
  return `${base}/api/runs/${runId}/kit.zip`;
}

export function brandGuideUrl(runId: string): string {
  return `${base}/api/runs/${runId}/brand_guide`;
}

export function kitFileUrl(runId: string, name: string): string {
  return `${base}/api/runs/${runId}/kit/${name}`;
}

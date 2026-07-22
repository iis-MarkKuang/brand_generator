export type AssetType =
  | "logo"
  | "banner"
  | "social_square"
  | "product_mockup"
  | "business_card";

export type AssetStatus = "approved" | "failed";

export interface HexColor {
  name: string;
  hex: string;
  rank: "primary" | "accent" | "neutral";
}

export interface BrandDna {
  brand_name: string;
  palette: HexColor[];
  mood: string[];
  typography_class: string;
  typography_pairs: { headline: string; body: string };
  visual_keywords: string[];
  dos: string[];
  donts: string[];
  personality: string;
}

export interface KitAsset {
  id: string;
  type: AssetType;
  path: string;
  status: AssetStatus;
  final_score: number | null;
  error: string | null;
}

export interface OptimizationStats {
  vram_swaps: number;
  brand_dna_cache_hit: boolean;
  critic_effort_low_count: number;
  critic_effort_medium_count: number;
  critic_effort_high_count: number;
  total_vlm_calls: number;
  total_renders: number;
  routing_local_count: number;
  routing_nim_count: number;
}

export interface ConsistencyDimension {
  dimension: string;
  score: number;
  notes: string;
}

export interface ConsistencyMatrix {
  overall_score: number;
  dimensions: ConsistencyDimension[];
  summary: string;
  asset_ids: string[];
}

export interface KitManifest {
  run_id: string;
  brand_name: string;
  status: "complete" | "partial";
  brand_guide: string;
  assets: KitAsset[];
  palette: string[];
  generated_at: string;
  total_latency_s: number;
  optimization_stats: OptimizationStats;
  consistency?: ConsistencyMatrix | null;
}

export interface RunState {
  run_id: string;
  stage: string;
  manifest: KitManifest | null;
}

export interface RunSummary {
  run_id: string;
  status: string;
  created_at: number;
}

export interface HealthDeps {
  ollama: boolean;
  comfyui: boolean;
  stepfun: boolean;
}

/** SSE event shapes pushed by /api/runs/{id}/events (allowlisted fields). */
export interface SseOrchestratorEvent {
  t?: string;
  action?: string;
  reason?: string;
  vram_before_gb?: number;
  vram_after_gb?: number;
  latency_s?: number;
  backend?: string;
}

export interface SseAssetEvent {
  event: "asset";
  asset_id: string;
}

export interface SseDoneEvent {
  event: "done";
  status: string;
}

export type SseEvent = SseOrchestratorEvent | SseAssetEvent | SseDoneEvent;

// Mirrors backend/app/agent/models.py and backend/app/api/schemas.py.

export type ToolStatus =
  | "success"
  | "tool_error"
  | "invalid_arguments"
  | "unknown_tool"
  | "timeout"
  | "unavailable"
  | "protocol_error"
  | "malformed_response"
  | "budget_exceeded";

export type ServerStatus = "available" | "unavailable" | "not_configured" | "unknown";

export interface Citation {
  number: number;
  citation_id: string;
  document_title: string;
  source_filename: string;
  document_version: string;
  page: number;
  section: string | null;
  excerpt: string;
  source_url?: string | null;
  doc_status?: string | null;
}

export interface SourceRef {
  server_id: string;
  server_name: string;
  tool: string;
  mode: string | null;
  provider: string | null;
  /** Public page the data came from (https only; filtered by the backend). */
  source_url?: string | null;
  /** When the service queried its source (UTC ISO). */
  retrieved_at?: string | null;
  /** Upstream update/version date, if the source states it. Not the query time. */
  data_as_of: string | null;
  /** true = out of date, false = current, null = cannot be determined. */
  stale: boolean | null;
  staleness_reason?: string | null;
  note?: string | null;
}

export interface ToolCallSummary {
  call_id: string;
  tool: string;
  server_id: string | null;
  arguments: Record<string, unknown> | null;
  status: ToolStatus;
  duration_ms: number;
  attempts: number;
  error: string | null;
  cached: boolean;
}

export interface AgentResult {
  trace_id: string;
  query: string;
  answer: string;
  status: "ok" | "partial" | "error";
  error_code: string | null;
  insufficient_evidence: boolean;
  citations: Citation[];
  sources: SourceRef[];
  tool_calls: ToolCallSummary[];
  warnings: string[];
  citation_check: { checked: number; unsupported: string[]; numbers_checked?: number; unsupported_numbers?: string[] };
  provider: string;
  model: string;
  iterations: number;
  latency_ms: number;
  usage: Record<string, number>;
}

export interface ServerState {
  id: string;
  name: string;
  description: string | null;
  url: string | null;
  status: ServerStatus;
  error: string | null;
  last_checked: string | null;
  latency_ms: number | null;
  protocol_version: string | null;
  server_version: string | null;
  tool_names: string[];
  data_mode: string | null;
  source_detail: Record<string, unknown> | null;
}

export interface SourcesResponse {
  servers: ServerState[];
  tool_count: number;
  checked_at: string;
}

export interface HealthResponse {
  status: "ok" | "degraded";
  version: string;
  environment: string;
  llm: { provider: string; model: string; configured: boolean; error: string | null };
  mcp: { configured: number; available: number; tools: number };
  time: string;
  campus_time?: string | null;
  access_mode?: "open" | "password" | null;
}

export interface SessionInfo {
  access_mode: "open" | "password";
  authenticated: boolean;
  expires_at: string | null;
}

export interface EvalRunInfo {
  run_id: string;
  kind: "agent" | "retrieval" | "library_search";
  generated_at: string | null;
  dataset: string | null;
  provider: string | null;
  model: string | null;
  transport: string | null;
  retriever: string | null;
  repeat: number | null;
  pass_rate: number | null;
  cases: number | null;
  legacy: boolean;
}

export interface RetrievalSplit {
  queries: number;
  answerable: number;
  no_answer: number;
  [metric: string]: number | string | null;
}

export interface RetrievalResult {
  retriever: string;
  status: "ok" | "not_run";
  reason?: string;
  embedding_model?: string;
  retrieval_mode?: string;
  thresholds?: { min_score: number; bm25_min_score: number };
  index_build_s?: number;
  splits?: { dev: RetrievalSplit; test: RetrievalSplit };
}

export interface RetrievalReport {
  kind: "retrieval";
  run_id: string;
  generated_at: string;
  dataset: string;
  k: number;
  tuned: boolean;
  results: RetrievalResult[];
}

export interface LibrarySplit {
  queries: number;
  positives: number;
  negatives: number;
  [metric: string]: number | string | null;
}

export interface LibraryResult {
  mode: string;
  status: "ok" | "not_run";
  reason?: string;
  embedder?: string | null;
  gates?: { min_score: number; min_z: number } | null;
  negative_margin?: number | null;
  negatives_top_cosine?: Record<string, number>;
  splits?: { dev: LibrarySplit; test: LibrarySplit };
  test_categories?: Record<string, Record<string, number | null>>;
}

export interface LibraryReport {
  kind: "library_search";
  run_id: string;
  generated_at: string;
  dataset: string;
  k: number;
  tuned: boolean;
  catalogue: { books: number; sha256: string };
  results: LibraryResult[];
}

export interface TraceListItem {
  trace_id: string;
  created_at: string;
  query: string;
  status: string;
  latency_ms: number;
  tool_calls: number;
  provider: string;
}

export interface TraceStep {
  kind: "discovery" | "llm" | "tool" | "note";
  started_at: string;
  duration_ms: number;
  detail: Record<string, unknown>;
}

export interface AgentTrace {
  trace_id: string;
  created_at: string;
  query: string;
  provider: string;
  model: string;
  status: string;
  latency_ms: number;
  steps: TraceStep[];
  result: AgentResult | null;
}

export interface ApiErrorBody {
  error: { code: string; message: string; request_id?: string | null };
}

export interface EvalCategory {
  category: string;
  cases: number;
  passed: number;
}

export interface EvalCase {
  id: string;
  category: string;
  query: string;
  passed: boolean;
  expected_servers: string[];
  called_servers: string[];
  called_tools?: string[];
  latency_ms: number;
  failures: string[];
  failure_class?: string | null;
  repeat?: number;
}

export interface EvalReport {
  kind?: "agent";
  run_id?: string;
  generated_at: string;
  dataset?: string;
  provider: string;
  model: string;
  transport?: string;
  note: string;
  latency_note?: string;
  config?: Record<string, unknown> & { dataset_version?: number; retriever?: string; repeat?: number };
  summary: Record<string, unknown>;
  categories: EvalCategory[];
  cases: EvalCase[];
}

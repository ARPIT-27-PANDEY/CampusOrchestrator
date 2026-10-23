// Mirrors backend/app/agent/models.py and backend/app/api/schemas.py.

export type ToolStatus =
  | "success"
  | "tool_error"
  | "invalid_arguments"
  | "unknown_tool"
  | "timeout"
  | "unavailable"
  | "protocol_error"
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
}

export interface SourceRef {
  server_id: string;
  server_name: string;
  tool: string;
  mode: string | null;
  provider: string | null;
  data_as_of: string | null;
  stale: boolean | null;
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
  citation_check: { checked: number; unsupported: string[] };
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

export interface EvalReport {
  generated_at: string;
  provider: string;
  model: string;
  note: string;
  summary: Record<string, number | string | null>;
  categories: EvalCategory[];
  cases: {
    id: string;
    category: string;
    query: string;
    passed: boolean;
    expected_servers: string[];
    called_servers: string[];
    latency_ms: number;
    failures: string[];
  }[];
}

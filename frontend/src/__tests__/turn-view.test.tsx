import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({ default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a> }));

import { TurnView } from "@/components/chat/answer";
import type { Turn } from "@/lib/chat-state";
import type { AgentResult } from "@/lib/types";

function result(overrides: Partial<AgentResult> = {}): AgentResult {
  return {
    trace_id: "trace123",
    query: "q",
    answer: "Prerequisite is **CS 210** [Academic Handbook 2026-27, p. 4]",
    status: "partial",
    error_code: null,
    insufficient_evidence: false,
    citations: [
      { number: 1, citation_id: "abc-p4-c2", document_title: "Academic Handbook 2026-27", source_filename: "academic_handbook_2026.pdf", document_version: "ce1e90b84acc", page: 4, section: "Section 3 - Course Prerequisites", excerpt: "3.3 AI Workshop Series prerequisite." },
    ],
    sources: [{ server_id: "academics", server_name: "Academics", tool: "search_handbook", mode: "demo", provider: "qdrant", data_as_of: null, stale: null }],
    tool_calls: [
      { call_id: "a", tool: "events__search_events", server_id: "events", arguments: { query: "ai workshop" }, status: "unavailable", duration_ms: 12, attempts: 2, error: "The server is unreachable.", cached: false },
      { call_id: "b", tool: "academics__search_handbook", server_id: "academics", arguments: { query: "prereq" }, status: "success", duration_ms: 90, attempts: 1, error: null, cached: false },
    ],
    warnings: ["Events: The server is unreachable."],
    citation_check: { checked: 1, unsupported: [] },
    provider: "mock",
    model: "mock-deterministic-v1",
    iterations: 2,
    latency_ms: 320,
    usage: {},
    ...overrides,
  };
}

function turn(r: AgentResult): Turn {
  return { id: "1", query: "Next AI workshop and its prerequisite?", phase: "done", draft: r.answer, toolCalls: r.tool_calls, result: r, traceId: r.trace_id };
}

describe("TurnView", () => {
  it("shows the answer, the route with failures, demo labelling and citations", () => {
    render(<TurnView turn={turn(result())} />);
    expect(screen.getByText("CS 210")).toBeInTheDocument();
    expect(screen.getByText(/^Partial answer/)).toBeInTheDocument();
    expect(screen.getByText("Events: is unreachable")).toBeInTheDocument(); // the failed service is named
    expect(screen.getByText(/not treated as "no results"/)).toBeInTheDocument();
    expect(screen.getByText(/Unreachable after 2 attempts/)).toBeInTheDocument();
    expect(screen.getByText("Demo data")).toBeInTheDocument();
    expect(screen.getByText(/Academic Handbook 2026-27, page 4/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open trace" })).toHaveAttribute("href", "/traces?id=trace123");
  });

  it("flags insufficient evidence and unverified page references", () => {
    render(
      <TurnView
        turn={turn(result({ status: "ok", citations: [], insufficient_evidence: true, citation_check: { checked: 1, unsupported: ["[Handbook, p. 9]"] } }))}
      />,
    );
    expect(screen.getByText("No supporting passage found")).toBeInTheDocument();
    expect(screen.getByText(/\[Handbook, p. 9\]/)).toBeInTheDocument();
  });

  it("asks the user to sign in again when the session expired", () => {
    render(
      <TurnView
        turn={{ id: "1", query: "q", phase: "failed", draft: "", toolCalls: [], error: { code: "auth_required", message: "Please sign in." } }}
      />,
    );
    expect(screen.getByText("Please sign in again")).toBeInTheDocument();
    expect(screen.getByText(/session has expired/)).toBeInTheDocument();
  });

  it("shows a loading state while streaming", () => {
    render(<TurnView turn={{ id: "1", query: "q", phase: "calling", draft: "", toolCalls: [] }} />);
    expect(screen.getByLabelText("Loading answer")).toBeInTheDocument();
    expect(screen.getByText("Asking campus systems…")).toBeInTheDocument();
  });
});

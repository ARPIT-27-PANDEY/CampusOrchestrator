export interface SSEEvent {
  event: string;
  data: unknown;
}

/**
 * Parse as many complete SSE events as possible from `text`.
 * Returns the events and the unconsumed remainder (an incomplete trailing event).
 * Comment lines (": keepalive") are ignored; malformed JSON payloads are skipped.
 */
export function parseSSEChunk(text: string): { events: SSEEvent[]; rest: string } {
  const normalized = text.replace(/\r\n/g, "\n");
  const blocks = normalized.split("\n\n");
  const rest = blocks.pop() ?? "";
  const events: SSEEvent[] = [];
  for (const block of blocks) {
    let event = "message";
    const dataLines: string[] = [];
    for (const line of block.split("\n")) {
      if (!line || line.startsWith(":")) continue;
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).replace(/^ /, ""));
    }
    if (!dataLines.length) continue;
    try {
      events.push({ event, data: JSON.parse(dataLines.join("\n")) });
    } catch {
      // ignore malformed payloads rather than corrupting the conversation
    }
  }
  return { events, rest };
}

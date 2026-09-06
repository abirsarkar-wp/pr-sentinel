"use client";

import { useState } from "react";
import type { AgentTraceEntry } from "@/lib/types";

export default function TraceViewer({
  traces,
}: {
  traces: AgentTraceEntry[];
}) {
  const [openTurn, setOpenTurn] = useState<number | null>(null);

  return (
    <div className="space-y-2">
      {traces.map((trace) => (
        <div
          key={trace.turn_number}
          className="rounded-lg border border-gray-200"
        >
          <button
            onClick={() =>
              setOpenTurn(
                openTurn === trace.turn_number
                  ? null
                  : trace.turn_number
              )
            }
            className="w-full text-left px-4 py-3 flex justify-between items-center text-sm"
          >
            <span>
              Turn {trace.turn_number} ·{" "}
              <span className="uppercase text-gray-500">
                {trace.role}
              </span>
            </span>

            <span className="text-gray-400">
              {trace.latency_ms
                ? `${trace.latency_ms}ms`
                : ""}
            </span>
          </button>

          {openTurn === trace.turn_number && (
            <pre className="bg-gray-900 text-gray-100 text-xs p-4 overflow-x-auto rounded-b-lg">
              {JSON.stringify(
                trace.content_json,
                null,
                2
              )}
            </pre>
          )}
        </div>
      ))}
    </div>
  );
}
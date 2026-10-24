import type { StageState } from "../api";
import { STAGE_LABEL } from "../lib/format";

const STAGES = ["technical", "trust", "engagement", "compose"] as const;
const STATE_LABEL: Record<StageState, string> = {
  pending: "Waiting",
  running: "Running",
  completed: "Done",
  failed: "Failed",
  timed_out: "Timed out",
};

export function ProgressStepper({ stages }: { stages?: Record<string, StageState> }) {
  const done = STAGES.filter((s) => stages?.[s] === "completed").length;
  return (
    <div>
      <p className="sr-only" aria-live="polite">
        {done} of {STAGES.length} stages complete.
      </p>
      <ol className="stepper">
        {STAGES.map((stage, i) => {
          const state: StageState = stages?.[stage] ?? "pending";
          return (
            <li key={stage} data-state={state}>
              <div className="state">
                {i + 1} · {STATE_LABEL[state]}
              </div>
              <div>{STAGE_LABEL[stage]}</div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

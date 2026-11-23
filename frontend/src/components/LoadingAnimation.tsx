import { Check } from "lucide-react";

/** Shows the agent's live steps ("Searching Amazon…", "Loading price history…"). */
export default function LoadingAnimation({ steps }: { steps: string[] }) {
  const shown = steps.length ? steps : ["Thinking…"];
  return (
    <div className="flex animate-fadeIn justify-start" role="status" aria-live="polite">
      <div className="w-full max-w-md rounded-2xl rounded-tl-sm border border-line bg-card px-4 py-3">
        <ul className="space-y-1.5 text-sm">
          {shown.map((step, i) => {
            const done = i < shown.length - 1;
            return (
              <li key={step} className={`flex items-center gap-2 ${done ? "text-muted" : "text-ink"}`}>
                {done ? (
                  <Check className="h-3.5 w-3.5 shrink-0 text-good" aria-hidden />
                ) : (
                  <span className="flex w-3.5 shrink-0 justify-center gap-0.5" aria-hidden>
                    {[0, 1, 2].map((d) => (
                      <span
                        key={d}
                        className="h-1 w-1 animate-pulseDot rounded-full bg-highlight"
                        style={{ animationDelay: `${d * 0.15}s` }}
                      />
                    ))}
                  </span>
                )}
                <span>{step}</span>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}

import type { Evidence, LeadLabel } from "@/lib/types";

const LEAD: Record<LeadLabel, { label: string; tone: string; text: string }> = {
  STRONG: {
    label: "Strong lead",
    tone: "bg-emerald-600",
    text: "Several identifying details match. Check them yourself before you act.",
  },
  POSSIBLE: {
    label: "Possible lead",
    tone: "bg-amber-500",
    text: "Identifying details match. Check the details below before you act.",
  },
  WEAK: {
    label: "Weak lead",
    tone: "bg-slate-500",
    text: "Only general details match, such as colour or brand. This is not enough to notify you, so it is shown for reference.",
  },
};

const STRENGTH_TAG: Record<Evidence["strength"], string> = {
  STRONG: "strong",
  MODERATE: "moderate",
  WEAK: "weak",
};

/** Lead label, with the rule-based relevance score. The score is not a probability of ownership. */
export function LeadBadge({ lead, percent }: { lead: LeadLabel | null; percent: number }) {
  if (!lead) {
    return (
      <span className="inline-flex items-center rounded-full bg-slate-400 px-3 py-1 text-sm font-semibold text-white">
        Earlier suggestion
      </span>
    );
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <span className={`inline-flex items-center rounded-full px-3 py-1 text-sm font-semibold text-white ${LEAD[lead].tone}`}>
        {LEAD[lead].label}
      </span>
      <span
        className="text-xs text-slate-500"
        title="A rule-based relevance score from fixed rules. It is not a probability that this is your item."
      >
        relevance {percent}%
      </span>
    </span>
  );
}

export function LeadDescription({ lead }: { lead: LeadLabel | null }) {
  const text = lead ? LEAD[lead].text : "This suggestion was made before lead labels existed. Check the details below.";
  return <p className={`text-sm ${lead === "WEAK" ? "text-amber-800" : "text-slate-600"}`}>{text}</p>;
}

/**
 * Structured evidence. Identity details are shown first, with their strength. Weak details are kept
 * apart and labelled, so they are not presented as strong matches. Context (place and time) is shown
 * separately, because it cannot identify an item. Conflicts are always shown.
 */
/** Item type, place and time. They describe the situation, not the item's identity. */
export const CONTEXT_SIGNALS = ["category", "location", "zone", "time"];

export function MatchEvidence({ evidence, lead }: { evidence: Evidence[]; lead: LeadLabel | null }) {
  const identity = evidence.filter(
    (e) => e.direction === "supports" && e.strength !== "WEAK" && !CONTEXT_SIGNALS.includes(e.signal),
  );
  const minor = evidence.filter(
    (e) => e.direction === "supports" && e.strength === "WEAK" && !CONTEXT_SIGNALS.includes(e.signal),
  );
  const context = evidence.filter((e) => e.direction === "supports" && CONTEXT_SIGNALS.includes(e.signal));
  const conflicts = evidence.filter((e) => e.direction === "contradicts");

  return (
    <div className="space-y-4 text-sm">
      {lead === "WEAK" && (
        <div className="rounded-xl bg-amber-50 p-3 text-amber-900">
          <strong>Weak lead.</strong> Do not treat this as a match. Shared colour, place or photo style do not identify an item.
        </div>
      )}
      <div>
        <h3 className="mb-1.5 font-semibold text-slate-900">
          {lead === "WEAK" ? "Shared details (not enough to notify you)" : "Matching details"}
        </h3>
        {identity.length === 0 ? (
          <p className="text-slate-500">No distinctive details match.</p>
        ) : (
          <ul className="space-y-1.5">
            {identity.map((e) => (
              <li key={`${e.signal}-${e.text}`} className="flex items-start gap-2 text-slate-700">
                <span className="text-emerald-700">✓</span>
                <span>{e.text}</span>
                <span className="ml-auto shrink-0 rounded bg-slate-100 px-1.5 text-xs text-slate-500">
                  {STRENGTH_TAG[e.strength]}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {minor.length > 0 && (
        <div>
          <h3 className="mb-1.5 font-semibold text-slate-500">Minor details (weak)</h3>
          <ul className="space-y-1 text-slate-500">
            {minor.map((e) => (
              <li key={`${e.signal}-${e.text}`}>• {e.text}</li>
            ))}
          </ul>
        </div>
      )}

      {context.length > 0 && (
        <div>
          <h3 className="mb-1.5 font-semibold text-slate-900">Item type, place and time</h3>
          <ul className="space-y-1 text-slate-600">
            {context.map((e) => (
              <li key={`${e.signal}-${e.text}`}>• {e.text}</li>
            ))}
          </ul>
          <p className="mt-1 text-xs text-slate-500">These show context only. They do not identify an item.</p>
        </div>
      )}

      {conflicts.length > 0 && (
        <div className="rounded-xl bg-red-50 p-3">
          <h3 className="mb-1.5 font-semibold text-red-800">Conflicts</h3>
          <ul className="space-y-1 text-red-800">
            {conflicts.map((e) => (
              <li key={`${e.signal}-${e.text}`}>⚠ {e.text}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

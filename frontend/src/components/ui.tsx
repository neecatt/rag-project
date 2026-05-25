import { cn } from "@/lib/utils";
import type { Citation } from "@/lib/types";

type EvidenceCitation = Citation & {
  excerpt?: string;
};

export function SectionCard({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <section
      className={cn(
        "surface-glass rounded-[1.75rem] p-6 animate-rise",
        className,
      )}
    >
      {children}
    </section>
  );
}

export function Pill({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: "neutral" | "success" | "warning" | "danger";
}) {
  const tones = {
    neutral: "bg-white/70 text-slate-700 ring-1 ring-slate-200/80",
    success: "bg-emerald-100/90 text-emerald-900 ring-1 ring-emerald-200",
    warning: "bg-amber-100/90 text-amber-900 ring-1 ring-amber-200",
    danger: "bg-rose-100/90 text-rose-900 ring-1 ring-rose-200",
  };

  return (
    <span
      className={cn(
        "rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.16em]",
        tones[tone],
      )}
    >
      {children}
    </span>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="rounded-[1.5rem] border border-dashed border-slate-200 bg-white/45 px-6 py-10 text-center">
      <h3 className="text-lg font-semibold tracking-tight text-slate-950">{title}</h3>
      <p className="mx-auto mt-2 max-w-xl text-sm leading-7 text-slate-600">
        {description}
      </p>
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}

export function AnswerContent({
  content,
  className,
}: {
  content: string;
  className?: string;
}) {
  const blocks = content
    .split(/\n{2,}/)
    .map((block) => block.trim())
    .filter(Boolean);

  return (
    <div className={cn("space-y-4", className)}>
      {blocks.map((block, index) => {
        const lines = block.split("\n").map((line) => line.trim()).filter(Boolean);
        const listItems = lines
          .map((line) => line.match(/^([-*]|\d+\.)\s+(.*)$/)?.[2]?.trim())
          .filter((item): item is string => Boolean(item));

        if (lines.length > 0 && listItems.length === lines.length) {
          return (
            <ul key={`${index}-${block.slice(0, 16)}`} className="space-y-2 pl-5 text-sm leading-7 text-inherit">
              {listItems.map((item) => (
                <li key={item} className="list-disc">
                  {item}
                </li>
              ))}
            </ul>
          );
        }

        return (
          <p
            key={`${index}-${block.slice(0, 16)}`}
            className="whitespace-pre-wrap text-sm leading-7 text-inherit"
          >
            {block}
          </p>
        );
      })}
    </div>
  );
}

export function EvidenceList({
  citations,
  title = "Supporting evidence",
  emptyLabel = "No citations returned",
}: {
  citations?: EvidenceCitation[];
  title?: string;
  emptyLabel?: string;
}) {
  if (!citations?.length) {
    return (
      <p className="text-xs uppercase tracking-[0.16em] text-slate-500">
        {emptyLabel}
      </p>
    );
  }

  return (
    <div className="rounded-[1.3rem] bg-white/80 p-4 ring-1 ring-slate-200">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
        {title}
      </p>
      <div className="mt-3 space-y-3">
        {citations.map((citation, index) => (
          <div
            key={`${citation.chunk_id}-${index}`}
            className="rounded-[1rem] bg-slate-50 px-3 py-3 text-sm text-slate-700 ring-1 ring-slate-200/70"
          >
            <p className="font-medium text-slate-900">
              [{index + 1}] {citation.title}
            </p>
            {citation.locator ? (
              <p className="mt-2 text-xs uppercase tracking-[0.16em] text-slate-500">
                {citation.locator}
              </p>
            ) : null}
            {citation.excerpt ? (
              <p className="mt-3 border-l-2 border-slate-200 pl-3 text-sm leading-6 text-slate-600">
                {citation.excerpt}
              </p>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}

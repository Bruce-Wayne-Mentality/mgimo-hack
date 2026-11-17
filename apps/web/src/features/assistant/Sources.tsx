import { BookOpen, ChevronDown, Quote, SearchX } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/cn";

/** A rule fragment the answer is based on (knowledge base) or one of the 15 built-in rules (id + title only). */
export type Source = {
  id: string;
  title: string;
  doc_id?: string;
  section_path?: string;
  page?: number | null;
  chunk_id?: string;
  excerpt?: string;
};

export const KB_KINDS = ["kb_answer", "kb_extract", "kb_refusal"] as const;

/** Under an answer: where it comes from. Tap a card to read the exact quote of the rule. */
export function SourceCards({ sources }: { sources: Source[] }) {
  const [open, setOpen] = useState<string | null>(null);
  if (sources.length === 0) return null;
  const detailed = sources.some((source) => source.excerpt);
  if (!detailed) {
    return (
      <p className="caption m-0 mt-2 flex flex-wrap items-center gap-1.5">
        <BookOpen aria-hidden className="size-3.5" /> Источник: {sources.map((source) => source.title).join(", ")}
      </p>
    );
  }
  return (
    <ul aria-label="Источники ответа" className="m-0 mt-3 flex list-none flex-col gap-2 p-0">
      {sources.map((source) => {
        const key = source.chunk_id ?? `${source.id}-${source.section_path}`;
        const expanded = open === key;
        const where = [source.section_path, source.page ? `стр. ${source.page}` : null].filter(Boolean).join(" · ");
        return (
          <li key={key} className="min-w-0">
            <button
              type="button"
              aria-expanded={expanded}
              onClick={() => setOpen(expanded ? null : key)}
              className="soft flex w-full min-w-0 items-start gap-2.5 rounded-[12px] bg-surface-2 px-3 py-2.5 text-left hover:bg-primary-soft"
            >
              <BookOpen aria-hidden className="mt-0.5 size-4 shrink-0 text-primary" />
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium break-words">{source.title}</span>
                {where && <span className="caption block break-words">{where}</span>}
              </span>
              <ChevronDown aria-hidden className={cn("mt-0.5 size-4 shrink-0 text-muted transition-transform", expanded && "rotate-180")} />
            </button>
            {expanded && source.excerpt && (
              <blockquote className="m-0 mt-1.5 rounded-[12px] border-l-4 border-primary bg-surface px-3 py-2 text-[14px] break-words whitespace-pre-line text-text-2">
                {source.excerpt}
              </blockquote>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/** A mark above knowledge base answers: an exact quote or a calm «not in the rules». */
export function KbBadge({ kind }: { kind: string }) {
  if (kind === "kb_extract") {
    return (
      <span className="mb-1.5 inline-flex items-center gap-1 rounded-full bg-primary-soft px-2.5 py-1 text-[12px] font-medium text-primary-strong">
        <Quote aria-hidden className="size-3.5" /> Точная цитата из правил
      </span>
    );
  }
  if (kind === "kb_refusal") {
    return (
      <span className="mb-1.5 inline-flex items-center gap-1 rounded-full bg-surface-2 px-2.5 py-1 text-[12px] font-medium text-text-2">
        <SearchX aria-hidden className="size-3.5" /> В правилах этого нет
      </span>
    );
  }
  if (kind === "kb_answer") {
    return (
      <span className="mb-1.5 inline-flex items-center gap-1 rounded-full bg-[#e3f7ea] px-2.5 py-1 text-[12px] font-medium text-[#146c3a]">
        <BookOpen aria-hidden className="size-3.5" /> По документам вуза
      </span>
    );
  }
  return null;
}

/** While the assistant searches: a skeleton of a message, not a spinner. */
export function ReplySkeleton() {
  return (
    <div role="status" aria-label="Ассистент ищет ответ" className="flex w-[min(88%,420px)] flex-col gap-2 rounded-[20px] rounded-bl-md bg-surface px-4 py-3 shadow-k-card">
      <span className="h-3 w-3/4 animate-pulse rounded bg-surface-2" />
      <span className="h-3 w-full animate-pulse rounded bg-surface-2" />
      <span className="h-3 w-1/2 animate-pulse rounded bg-surface-2" />
    </div>
  );
}

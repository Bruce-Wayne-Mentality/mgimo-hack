import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleSlash, SearchX, Send } from "lucide-react";
import { useState } from "react";
import { Alert, Button, Card, EmptyState, ErrorState, PageHeader, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";

export type Gap = {
  id: string;
  question: string;
  status: "open" | "answered" | "rejected";
  top_score: number;
  nearest: { title: string; section_path: string } | null;
  answer_text: string | null;
  answered_by: string | null;
  created_at: string;
  answered_at: string | null;
};

const TABS = [
  { key: "open", label: "Без ответа" },
  { key: "answered", label: "Отвечены" },
  { key: "rejected", label: "Не по правилам" },
] as const;

function when(value: string): string {
  return new Intl.DateTimeFormat("ru", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Moscow" }).format(new Date(value));
}

export function GapCard({ gap }: { gap: Gap }) {
  const client = useQueryClient();
  const [text, setText] = useState("");
  const done = () => client.invalidateQueries({ queryKey: ["kb-gaps"] });
  const answer = useMutation({
    mutationFn: (publish: boolean) => api(`/api/staff/kb/gaps/${gap.id}/answer`, { method: "POST", body: { answer_text: text.trim(), publish } }),
    onSuccess: done,
  });
  const reject = useMutation({ mutationFn: () => api(`/api/staff/kb/gaps/${gap.id}/reject`, { method: "POST" }), onSuccess: done });
  const busy = answer.isPending || reject.isPending;
  return (
    <Card className="flex min-w-0 flex-col gap-3">
      <div className="min-w-0">
        <p className="caption m-0">{when(gap.created_at)} · вопрос студента без имени и контактов</p>
        <p className="m-0 mt-1 text-[16px] font-medium break-words">{gap.question}</p>
        <p className="caption m-0 mt-1 break-words">
          {gap.nearest ? `Ближе всего нашлось: «${gap.nearest.title}», ${gap.nearest.section_path}` : "В базе ничего похожего"}
          {` · уверенность ${gap.top_score}`}
        </p>
      </div>
      {gap.status === "open" ? (
        <>
          <label className="flex flex-col gap-1.5">
            <span className="text-sm font-medium">Ответ</span>
            <textarea
              value={text}
              onChange={(event) => setText(event.target.value)}
              rows={3}
              maxLength={2000}
              placeholder="Ответ попадёт в базу знаний ассистента — пишите по правилам, без имён и контактов"
              className="min-h-24 w-full resize-y rounded-[var(--radius-control)] border border-line bg-surface px-3 py-2 text-base focus:border-primary focus:outline-none"
            />
          </label>
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => answer.mutate(true)} disabled={busy || text.trim().length < 3} loading={answer.isPending}>
              <Send aria-hidden className="size-4" /> Опубликовать
            </Button>
            <button
              onClick={() => reject.mutate()}
              disabled={busy}
              className="soft inline-flex min-h-11 items-center gap-1.5 rounded-[var(--radius-control)] bg-surface-2 px-4 text-sm font-medium text-text hover:bg-primary-soft disabled:opacity-60"
            >
              <CircleSlash aria-hidden className="size-4" /> Не по правилам
            </button>
          </div>
          {(answer.isError || reject.isError) && <Alert>{(answer.error ?? reject.error)?.message}</Alert>}
        </>
      ) : (
        <div className={cn("rounded-[12px] px-3 py-2 text-sm", gap.status === "answered" ? "bg-[#e3f7ea] text-[#146c3a]" : "bg-surface-2 text-text-2")}>
          {gap.status === "answered" ? <span className="block break-words whitespace-pre-line">{gap.answer_text}</span> : "Отмечено: вопрос не по правилам вуза"}
          {gap.answered_by && <span className="caption mt-1 block">{gap.answered_by}{gap.answered_at ? ` · ${when(gap.answered_at)}` : ""}</span>}
        </div>
      )}
    </Card>
  );
}

/** Questions the assistant could not answer from the rules: answer once — the base learns. */
export function KbGapsPage() {
  const [status, setStatus] = useState<(typeof TABS)[number]["key"]>("open");
  const gaps = useQuery({
    queryKey: ["kb-gaps", status],
    queryFn: () => api<{ items: Gap[]; counts: Record<string, number> }>(`/api/staff/kb/gaps?status=${status}`),
  });
  return (
    <div className="flex flex-col gap-4">
      <PageHeader eyebrow="Ассистент · база знаний" title="Пробелы базы">
        <p className="m-0 mt-1 max-w-2xl text-text-2">
          Вопросы, на которые ассистент не нашёл ответа в правилах. Опубликованный ответ становится частью базы — на тот же вопрос ассистент дальше ответит сам, с источником «Ответы деканата».
        </p>
      </PageHeader>
      <div role="tablist" aria-label="Статус вопросов" className="flex flex-wrap gap-2">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            role="tab"
            aria-selected={status === tab.key}
            onClick={() => setStatus(tab.key)}
            className={cn("soft min-h-10 rounded-full px-4 text-sm font-medium", status === tab.key ? "bg-primary text-on-primary" : "bg-surface text-text-2 hover:bg-primary-soft")}
          >
            {tab.label}
            {gaps.data && <span className="ml-1.5 opacity-80">{gaps.data.counts[tab.key] ?? 0}</span>}
          </button>
        ))}
      </div>
      {gaps.isPending && <Skeleton className="h-40" />}
      {gaps.isError && <ErrorState message={gaps.error.message} onRetry={() => gaps.refetch()} />}
      {gaps.data && gaps.data.items.length === 0 && (
        <EmptyState>
          <span className="inline-flex items-center gap-2"><SearchX aria-hidden className="size-5" /> Пробелов нет</span>
        </EmptyState>
      )}
      <div className="grid min-w-0 gap-3 lg:grid-cols-2">
        {gaps.data?.items.map((gap) => <GapCard key={gap.id} gap={gap} />)}
      </div>
    </div>
  );
}

import { ChevronRight, Plus } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { Card, EmptyState, ErrorState, PageHeader, Skeleton } from "@/components/ui";
import { cn } from "@/lib/cn";
import { OPEN, dateLabel, useMyRequests, type RequestSummary } from "./api";
import { StatusChip } from "./parts";

const FILTERS = [
  { key: "all", label: "Все" },
  { key: "open", label: "Активные" },
  { key: "ready", label: "Готовые" },
  { key: "closed", label: "Закрытые" },
] as const;

type Filter = (typeof FILTERS)[number]["key"];

function matches(item: RequestSummary, filter: Filter): boolean {
  if (filter === "open") return OPEN.includes(item.status);
  if (filter === "ready") return item.status === "ready";
  if (filter === "closed") return item.status === "rejected" || item.status === "cancelled";
  return true;
}

export function NewRequestButton({ className }: { className?: string }) {
  return (
    <Link
      to="/requests/new"
      className={cn("soft inline-flex min-h-12 items-center justify-center gap-2 rounded-[var(--radius-control)] bg-primary px-5 text-[15px] font-medium text-on-primary hover:bg-primary-hover", className)}
    >
      <Plus className="size-5" aria-hidden />
      Новая заявка
    </Link>
  );
}

export function RequestRow({ item }: { item: RequestSummary }) {
  const open = OPEN.includes(item.status);
  return (
    <Link
      to={`/requests/${item.id}`}
      className={cn("nudge soft flex items-center gap-4 rounded-[var(--radius-tile)] p-4 hover:bg-primary-soft", item.status === "needs_info" ? "bg-[#fff8e8]" : "bg-surface-2")}
    >
      <div className="min-w-0 flex-1">
        <p className="caption m-0">{item.number} · от {dateLabel(item.created_at)}</p>
        <p className="m-0 mt-0.5 truncate text-[16px] font-medium">{item.type.title}</p>
        <p className="caption m-0 mt-1">
          {item.status === "needs_info"
            ? "Нужен ваш ответ"
            : open && new Date(item.due_at).getTime() < Date.now()
              ? `Дольше обычного: ориентир был ${dateLabel(item.due_at)}`
              : open
                ? `Обычно до ${dateLabel(item.due_at)}`
                : `Обновлена ${dateLabel(item.updated_at)}`}
        </p>
      </div>
      <StatusChip status={item.status} label={item.status_label} className="hidden sm:inline-flex" />
      <ChevronRight className="size-5 shrink-0 text-muted" aria-hidden />
      <span className="sr-only">Статус: {item.status_label}</span>
    </Link>
  );
}

export function RequestsPage() {
  const requests = useMyRequests();
  const [filter, setFilter] = useState<Filter>("all");
  const items = (requests.data ?? []).filter((item) => matches(item, filter));
  const needAnswer = (requests.data ?? []).filter((item) => item.status === "needs_info").length;

  return (
    <div className="flex flex-col gap-4">
      <PageHeader eyebrow="Справки и обращения в деканат" title="Заявки">
        <div className="mt-2">
          <NewRequestButton />
        </div>
      </PageHeader>

      {needAnswer > 0 && (
        <div role="status" className="rounded-[var(--radius-card)] bg-[#fff4dc] px-5 py-4 text-[15px] text-[#6b4600]">
          {needAnswer === 1 ? "По одной заявке нужен ваш ответ." : `По ${needAnswer} заявкам нужен ваш ответ.`}
        </div>
      )}

      <Card>
        <div role="tablist" aria-label="Фильтр заявок" className="mb-4 flex gap-1.5 overflow-x-auto [scrollbar-width:none]">
          {FILTERS.map((option) => (
            <button
              key={option.key}
              role="tab"
              aria-selected={filter === option.key}
              onClick={() => setFilter(option.key)}
              className={cn(
                "soft min-h-10 shrink-0 rounded-[10px] px-4 text-sm",
                filter === option.key ? "bg-primary text-on-primary" : "bg-surface-2 text-text-2 hover:bg-primary-soft",
              )}
            >
              {option.label}
            </button>
          ))}
        </div>
        <div aria-live="polite" className="flex flex-col gap-2.5">
          {requests.isPending && <Skeleton className="h-24" />}
          {requests.isError && <ErrorState message={requests.error.message} onRetry={() => requests.refetch()} />}
          {requests.isSuccess && requests.data.length === 0 && (
            <EmptyState action={<NewRequestButton className="min-h-10" />}>
              Заявок пока нет. Справку с места учёбы можно получить за минуту.
            </EmptyState>
          )}
          {requests.isSuccess && requests.data.length > 0 && items.length === 0 && <EmptyState>В этом разделе заявок нет.</EmptyState>}
          {items.map((item) => (
            <RequestRow key={item.id} item={item} />
          ))}
        </div>
      </Card>
    </div>
  );
}

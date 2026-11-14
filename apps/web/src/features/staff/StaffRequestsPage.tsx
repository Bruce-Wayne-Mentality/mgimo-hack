import { AlertTriangle, ChevronRight } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { Alert, Button, Card, CardTitle, EmptyState, ErrorState, PageHeader, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { dateLabel, dateTimeLabel, useRequest, useRequestAction, useStaffQueue, type RequestDetail, type RequestStatus } from "../requests/api";
import { Conversation, RequestFacts } from "../requests/RequestDetailPage";
import { StatusChip, Tracker } from "../requests/parts";

const FILTERS: { key: string; label: string; status?: string; overdue?: boolean }[] = [
  { key: "open", label: "В очереди", status: "open" },
  { key: "submitted", label: "Новые", status: "submitted" },
  { key: "needs_info", label: "Ждём студента", status: "needs_info" },
  { key: "overdue", label: "Просрочены", overdue: true },
  { key: "all", label: "Все" },
];

export function StaffRequestsPage() {
  const [filterKey, setFilterKey] = useState("open");
  const filter = FILTERS.find((item) => item.key === filterKey)!;
  const queue = useStaffQueue({ status: filter.status, overdue: filter.overdue });

  return (
    <div className="flex flex-col gap-4">
      <PageHeader eyebrow="Кабинет сотрудника · сортировка по сроку" title="Очередь заявок" />
      <Card>
        <div role="tablist" aria-label="Фильтр очереди" className="mb-4 flex gap-1.5 overflow-x-auto [scrollbar-width:none]">
          {FILTERS.map((option) => (
            <button
              key={option.key}
              role="tab"
              aria-selected={filterKey === option.key}
              onClick={() => setFilterKey(option.key)}
              className={cn("soft min-h-10 shrink-0 rounded-[10px] px-4 text-sm",
                filterKey === option.key ? "bg-primary text-on-primary" : "bg-surface-2 text-text-2 hover:bg-primary-soft")}
            >
              {option.label}
            </button>
          ))}
        </div>
        <div aria-live="polite" className="flex flex-col gap-2.5">
          {queue.isPending && <Skeleton className="h-24" />}
          {queue.isError && <ErrorState message={queue.error.message} onRetry={() => queue.refetch()} />}
          {queue.isSuccess && queue.data.length === 0 && <EmptyState>Здесь пусто — все заявки разобраны.</EmptyState>}
          {queue.data?.map((item) => (
            <Link
              key={item.id}
              to={`/staff/requests/${item.id}`}
              className={cn("nudge soft flex items-center gap-4 rounded-[var(--radius-tile)] p-4 hover:bg-primary-soft", item.overdue ? "bg-[#fff1ec]" : "bg-surface-2")}
            >
              <div className="min-w-0 flex-1">
                <p className="caption m-0">{item.number} · {item.student.full_name} · {item.student.group}</p>
                <p className="m-0 mt-0.5 truncate text-[16px] font-medium">{item.type.title}</p>
                <p className={cn("m-0 mt-1 flex items-center gap-1.5 text-[13px]", item.overdue ? "font-medium text-[#b4441f]" : "text-muted")}>
                  {item.overdue && <AlertTriangle className="size-4" aria-hidden />}
                  {item.overdue ? `Просрочена: срок был ${dateLabel(item.due_at)}` : `Срок до ${dateTimeLabel(item.due_at)}`}
                </p>
              </div>
              <StatusChip status={item.status} label={item.status_label} className="hidden sm:inline-flex" />
              <ChevronRight className="size-5 shrink-0 text-muted" aria-hidden />
            </Link>
          ))}
        </div>
      </Card>
    </div>
  );
}

const ACTION_COPY: Partial<Record<RequestStatus, { button: string; placeholder: string; variant: "primary" | "secondary" | "danger" }>> = {
  in_review: { button: "Взять в работу", placeholder: "", variant: "primary" },
  needs_info: { button: "Запросить данные", placeholder: "Что нужно уточнить у студента", variant: "secondary" },
  ready: { button: "Готово", placeholder: "Результат для студента: где забрать, номер приказа…", variant: "primary" },
  rejected: { button: "Отклонить", placeholder: "Причина отказа", variant: "danger" },
};

export function StaffRequestPage() {
  const { id = "" } = useParams();
  const request = useRequest(id, true);
  const [note, setNote] = useState("");
  const [pending, setPending] = useState<RequestStatus | null>(null);
  const transition = useRequestAction<{ to: RequestStatus; note?: string }>(id, true, (input) =>
    api<RequestDetail>(`/api/staff/requests/${id}/transition`, { method: "POST", body: input }),
  );
  const comment = useRequestAction<{ body: string; internal: boolean }>(id, true, (input) =>
    api<RequestDetail>(`/api/requests/${id}/comments`, { method: "POST", body: input }),
  );

  if (request.isPending) return <Skeleton className="h-96" />;
  if (request.isError) {
    return (
      <div className="flex flex-col gap-4">
        <PageHeader eyebrow={<Link to="/staff/requests" className="text-primary hover:underline">← Очередь</Link>} title="Заявка" />
        <ErrorState message={request.error.message} onRetry={() => request.refetch()} />
      </div>
    );
  }
  const data = request.data;
  const run = (to: RequestStatus, needsNote: boolean) => {
    if (needsNote && !note.trim()) {
      setPending(to);
      return;
    }
    transition.mutate({ to, note: note.trim() || undefined }, { onSuccess: () => { setNote(""); setPending(null); } });
  };

  return (
    <div className="flex flex-col gap-4">
      <PageHeader eyebrow={<Link to="/staff/requests" className="text-primary hover:underline">← Очередь</Link>} title={data.type.title}>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <StatusChip status={data.status} label={data.status_label} />
          <span className="caption">{data.number} · подана {dateLabel(data.created_at)} · срок до {dateTimeLabel(data.due_at)}</span>
        </div>
      </PageHeader>

      {data.student && (
        <section className="flex flex-col gap-1 rounded-[var(--radius-card)] bg-[image:var(--k-gradient-primary)] p-5 text-on-primary sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="m-0 text-[20px] font-medium">{data.student.full_name}</p>
            <p className="m-0 text-sm opacity-80">{data.student.faculty}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            {[data.student.group, `${data.student.course} курс`, data.student.record_book_no].map((chip) => (
              <span key={chip} className="rounded-[10px] bg-white/16 px-3 py-1.5 text-[13px]">{chip}</span>
            ))}
          </div>
        </section>
      )}

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)]">
        <div className="flex flex-col gap-4">
          {!!data.actions?.length && (
            <Card aria-labelledby="actions-heading">
              <CardTitle id="actions-heading">Действия</CardTitle>
              {data.actions.some((action) => action.note_required) && (
                <div className="mb-3 flex flex-col gap-1.5">
                  <label htmlFor="note" className="text-sm font-medium text-text-2">Комментарий для студента</label>
                  <textarea
                    id="note"
                    rows={3}
                    maxLength={2000}
                    value={note}
                    onChange={(event) => setNote(event.target.value)}
                    placeholder={pending ? ACTION_COPY[pending]?.placeholder : "Обязателен для запроса данных, готовности и отказа"}
                    aria-invalid={!!pending && !note.trim()}
                    className="soft w-full rounded-[var(--radius-control)] border border-transparent bg-surface-2 px-4 py-3 text-base focus:border-primary focus:bg-surface focus:outline-none aria-[invalid=true]:border-danger"
                  />
                  {pending && !note.trim() && <p className="m-0 text-[13px] text-danger">Напишите комментарий — он придёт студенту.</p>}
                </div>
              )}
              <div className="flex flex-wrap gap-2">
                {data.actions.map((action) => {
                  const copy = ACTION_COPY[action.to];
                  return (
                    <Button key={action.to} variant={copy?.variant ?? "secondary"} loading={transition.isPending && transition.variables?.to === action.to}
                      onClick={() => run(action.to, action.note_required)}>
                      {copy?.button ?? action.label}
                    </Button>
                  );
                })}
              </div>
              {transition.isError && <Alert className="mt-3">{transition.error.message}</Alert>}
            </Card>
          )}
          <Card aria-labelledby="track-heading">
            <CardTitle id="track-heading">Ход заявки</CardTitle>
            <Tracker request={data} />
            <ol className="m-0 mt-5 flex list-none flex-col gap-1.5 border-t border-line pt-4">
              {data.events.map((event, index) => (
                <li key={index} className="text-[13px] text-text-2">
                  <span className="text-muted">{dateTimeLabel(event.at)} · </span>
                  {event.label}{event.by_system ? " (автоматически)" : ""}{event.note ? ` — ${event.note}` : ""}
                </li>
              ))}
            </ol>
          </Card>
        </div>
        <div className="flex flex-col gap-4">
          <RequestFacts request={data} />
          <Conversation
            request={data}
            staff
            canWrite={!data.closed}
            sending={comment.isPending}
            error={comment.isError ? comment.error.message : null}
            onSend={(body, internal) => comment.mutateAsync({ body, internal })}
          />
        </div>
      </div>
    </div>
  );
}

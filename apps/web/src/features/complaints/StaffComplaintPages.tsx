import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, ChevronRight, ShieldAlert, UserRound } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { Alert, Button, Card, CardTitle, EmptyState, ErrorState, PageHeader, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { AttachButton, DropZone, PendingFiles, useAttachments } from "../attachments/Attachments";
import { dateLabel, dateTimeLabel } from "../requests/api";
import { CATEGORIES, type StaffComplaint, type StaffDetail } from "./api";
import { StatusBadge, Thread, Tracker } from "./ComplaintPages";

type Queue = { items: StaffComplaint[]; counts: Record<string, number>; role: "curator" | "executor" };

const FILTERS = [
  { key: "open", label: "Открытые" },
  { key: "NEW", label: "Новые" },
  { key: "IN_PROGRESS", label: "В работе" },
  { key: "ESCALATED", label: "Переданы выше" },
  { key: "", label: "Все" },
];
const FLAG_LABELS: Record<string, string> = {
  disputed: "спорно: ИИ и классификатор разошлись", unclear: "мало деталей", stage1_insult: "классификатор: резкие слова",
  ai_insult: "ИИ: оскорбление", injection_pattern: "попытка управлять ИИ", risk_threat: "угроза", risk_self_harm: "риск для автора", risk_safety: "опасность",
};

function QueueRow({ item, base }: { item: StaffComplaint; base: string }) {
  return (
    <Link to={`${base}/${item.id}`} className={cn("nudge soft flex items-center gap-3 rounded-[var(--radius-tile)] p-4 hover:bg-primary-soft", item.overdue ? "bg-[#fff5f5] ring-1 ring-[#f3b8ba]" : "bg-surface-2")}>
      <span className={cn("grid size-8 shrink-0 place-items-center rounded-full text-[13px] font-medium", item.priority === 1 ? "bg-[#e5484d] text-white" : item.priority === 2 ? "bg-primary-soft text-primary-strong" : "bg-surface text-muted")} title={`Приоритет ${item.priority}`}>
        {item.priority}
      </span>
      <span className="min-w-0 flex-1">
        <span className="caption block">{item.number} · {item.category_label} · {item.author}</span>
        <span className="block truncate font-medium">{item.title}</span>
        <span className="caption block">{item.overdue ? "срок превышен" : `ответ до ${dateLabel(item.answer_due_at)}`}{item.flags.length ? ` · ${item.flags.map((f) => FLAG_LABELS[f] ?? f).join(", ")}` : ""}</span>
      </span>
      <StatusBadge status={item.status} label={item.status_label} />
      <ChevronRight aria-hidden className="size-5 shrink-0 text-muted" />
    </Link>
  );
}

/** А1 — очередь исполнителя и куратора. */
export function StaffComplaintsPage() {
  const [status, setStatus] = useState("open");
  const [category, setCategory] = useState("");
  const queue = useQuery({
    queryKey: ["staff-complaints", status, category],
    queryFn: () => api<Queue>(`/api/staff/complaints?${new URLSearchParams({ ...(status ? { status } : {}), ...(category ? { category } : {}) })}`),
    refetchInterval: 30_000,
  });
  const data = queue.data;
  return (
    <div className="flex flex-col gap-4">
      <PageHeader eyebrow="Красная кнопка · обязательное рассмотрение" title="Обращения" />
      {data?.role === "curator" && (data.counts.MODERATION ?? 0) > 0 && (
        <Link to="/staff/moderation" className="soft flex items-center gap-3 rounded-[var(--radius-card)] bg-[#fff4dc] p-4 text-[#6b4600] hover:bg-[#ffecc2]">
          <ShieldAlert aria-hidden className="size-6" />
          <span className="flex-1">На ручной модерации: <b>{data.counts.MODERATION}</b>. Цель — разобрать за 4 рабочих часа.</span>
          <ChevronRight aria-hidden className="size-5" />
        </Link>
      )}
      <div className="flex flex-wrap gap-1.5">
        {FILTERS.map((f) => (
          <button key={f.key} aria-pressed={status === f.key} onClick={() => setStatus(f.key)}
            className={cn("soft min-h-9 rounded-[10px] px-3.5 text-sm", status === f.key ? "bg-primary text-on-primary" : "bg-surface text-text-2 shadow-k-card hover:bg-primary-soft")}>
            {f.label}
          </button>
        ))}
        <select value={category} onChange={(event) => setCategory(event.target.value)} aria-label="Категория" className="soft min-h-9 rounded-[10px] bg-surface px-3 text-sm shadow-k-card">
          <option value="">Все категории</option>
          {CATEGORIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
        </select>
      </div>
      <Card>
        {queue.isPending && <Skeleton className="h-32" />}
        {queue.isError && <ErrorState message={queue.error.message} onRetry={() => queue.refetch()} />}
        {data?.items.length === 0 && <EmptyState>Обращений нет.</EmptyState>}
        <div className="flex flex-col gap-2.5">
          {data?.items.map((item) => <QueueRow key={item.id} item={item} base="/staff/complaints" />)}
        </div>
        {data?.role === "executor" && <p className="caption m-0 mt-3">Обращения, где вы указаны как субъект жалобы, в вашу очередь не попадают.</p>}
      </Card>
    </div>
  );
}

/** А3 — ручная модерация (куратор). */
export function ModerationPage() {
  const queue = useQuery({ queryKey: ["moderation"], queryFn: () => api<Queue>("/api/staff/moderation"), refetchInterval: 30_000 });
  return (
    <div className="flex flex-col gap-4">
      <PageHeader eyebrow="Эскалации, спорные вердикты, сбои ИИ, просьбы авторов" title="Ручная модерация" />
      <Card>
        {queue.isPending && <Skeleton className="h-32" />}
        {queue.isError && <ErrorState message={queue.error.message} />}
        {queue.data?.items.length === 0 && <EmptyState>Очередь модерации пуста.</EmptyState>}
        <div className="flex flex-col gap-2.5">
          {queue.data?.items.map((item) => <QueueRow key={item.id} item={item} base="/staff/complaints" />)}
        </div>
      </Card>
    </div>
  );
}

/** А2 — карточка для сотрудника. */
export function StaffComplaintPage() {
  const { id = "" } = useParams();
  const client = useQueryClient();
  const item = useQuery({ queryKey: ["staff-complaints", id], queryFn: () => api<StaffDetail>(`/api/staff/complaints/${id}`) });
  const [text, setText] = useState("");
  const files = useAttachments(`/api/staff/complaints/${id}/attachments`, (info) => `/api/complaints/attachments/${info.id}`);
  const act = useMutation({
    mutationFn: (action: string) => api<StaffDetail>(`/api/staff/complaints/${id}/status`, { method: "POST", body: { action, text: text.trim() || null, attachment_ids: ["message", "answer", "need_info"].includes(action) ? files.ids : [] } }),
    onSuccess: (data) => {
      setText("");
      files.reset();
      client.setQueryData(["staff-complaints", id], data);
      client.invalidateQueries({ queryKey: ["staff-complaints"], exact: false });
      client.invalidateQueries({ queryKey: ["moderation"] });
    },
  });
  const assign = useMutation({
    mutationFn: (assignee: string) => api<StaffDetail>(`/api/staff/complaints/${id}/assign`, { method: "POST", body: { assignee_id: assignee } }),
    onSuccess: (data) => client.setQueryData(["staff-complaints", id], data),
  });
  const data = item.data;
  const textActions = data?.actions.filter((a) => a.text) ?? [];
  const plainActions = data?.actions.filter((a) => !a.text) ?? [];
  return (
    <div className="flex flex-col gap-4">
      <PageHeader eyebrow={<Link to="/staff/complaints" className="text-primary hover:underline">← Обращения</Link>} title={data?.title ?? "Обращение"}>
        {data && (
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={data.status} label={data.status_label} />
            <span className="caption">{data.number} · {data.type_label} · {data.category_label} · приоритет {data.priority}</span>
          </div>
        )}
      </PageHeader>
      {item.isPending && <Skeleton className="h-64" />}
      {item.isError && <ErrorState message={item.error.message} />}
      {data && (
        <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-4 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
          <div className="flex flex-col gap-4">
            {data.status === "MODERATION" && (
              <Alert tone="info">Причина модерации: {data.moderation_reason_label ?? data.moderation_reason}. Исполнитель не видит обращение, пока куратор его не примет.</Alert>
            )}
            {data.summary && (
              <Card className="bg-primary-soft">
                <p className="m-0 flex items-center gap-1.5 text-[13px] font-medium text-primary-strong"><Bot aria-hidden className="size-4" />Сводка ИИ (GigaChat) — проверьте по полному тексту</p>
                <p className="m-0 mt-1 text-[15px]">{data.summary}</p>
              </Card>
            )}
            <Card>
              <CardTitle meta={<span className="caption flex items-center gap-1"><UserRound aria-hidden className="size-4" />{data.author}</span>}>Полный текст</CardTitle>
              {data.link_label && <p className="caption m-0 mb-2">{data.link_label}</p>}
              <p className="m-0 text-[15px] whitespace-pre-wrap">{data.text ?? "Текст удалён."}</p>
              {data.desired_label && <p className="caption m-0 mt-2">Чего хочет автор: {data.desired_label}</p>}
              {data.flags.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {data.flags.map((flag) => <span key={flag} className="rounded-full bg-[#fff4dc] px-2.5 py-1 text-[12px] text-[#8a5a00]">{FLAG_LABELS[flag] ?? flag}</span>)}
                </div>
              )}
            </Card>
            <Card>
              <CardTitle>Переписка</CardTitle>
              <Thread messages={data.messages} staff />
              {data.actions.length > 0 && (
                <div className="mt-4 flex flex-col gap-2">
                  {textActions.length > 0 && (
                    <DropZone state={files} className="flex flex-col gap-2">
                    <textarea rows={3} value={text} onChange={(event) => setText(event.target.value)} placeholder="Ответ, запрос информации или комментарий"
                      className="soft rounded-[var(--radius-control)] bg-surface-2 px-4 py-3 text-base focus:bg-surface focus:shadow-[var(--k-focus-ring)] focus:outline-none" />
                    <div className="flex items-start gap-2"><AttachButton state={files} disabled={act.isPending} /><div className="min-w-0 flex-1 pt-2.5"><PendingFiles state={files} hint="Файлы прикрепятся к сообщению, ответу или запросу информации." /></div></div>
                    </DropZone>
                  )}
                  <div className="flex flex-wrap gap-2">
                    {plainActions.map((a) => <Button key={a.action} loading={act.isPending && act.variables === a.action} onClick={() => act.mutate(a.action)}>{a.label}</Button>)}
                    {textActions.map((a) => (
                      <Button key={a.action} variant={a.action === "answer" ? "primary" : a.action === "return" ? "danger" : "secondary"} disabled={text.trim().length < 3}
                        loading={act.isPending && act.variables === a.action} onClick={() => act.mutate(a.action)}>{a.label}</Button>
                    ))}
                  </div>
                  {act.isError && <Alert>{act.error.message}</Alert>}
                </div>
              )}
            </Card>
          </div>
          <div className="flex flex-col gap-4">
            <Card>
              <CardTitle>Статус и сроки</CardTitle>
              <Tracker status={data.status} events={data.events} />
              <p className={cn("m-0 mt-4 rounded-[var(--radius-tile)] px-4 py-3 text-sm", data.overdue ? "bg-danger-soft text-danger" : "bg-surface-2 text-text-2")}>
                {data.department} · взять до {dateLabel(data.take_due_at)} · ответить до {dateLabel(data.answer_due_at)}{data.assignee ? ` · исполнитель: ${data.assignee}` : ""}
              </p>
              {data.role === "curator" && data.assignees.length > 0 && (
                <label className="mt-3 flex items-center gap-2 text-sm">Назначить:
                  <select onChange={(event) => event.target.value && assign.mutate(event.target.value)} defaultValue="" className="soft min-h-10 flex-1 rounded-[10px] bg-surface-2 px-3">
                    <option value="">выберите сотрудника</option>
                    {data.assignees.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                  </select>
                </label>
              )}
            </Card>
            {data.role === "curator" && (
              <Card>
                <CardTitle>Автоматическая проверка</CardTitle>
                <ul className="m-0 flex list-none flex-col gap-2 p-0 text-sm">
                  {data.moderation.map((m, index) => (
                    <li key={index} className="rounded-[var(--radius-tile)] bg-surface-2 px-3 py-2">
                      <span className="font-medium">Этап {m.stage}: {m.verdict}</span>
                      <span className="caption block">{Object.entries(m.scores).map(([k, v]) => `${k} ${typeof v === "number" ? v.toFixed?.(2) ?? v : String(v)}`).join(" · ") || "без оценок"}</span>
                      <span className="caption block">{Object.values(m.models).join(", ")} · {m.latency_ms} мс · {dateTimeLabel(m.at)}</span>
                    </li>
                  ))}
                </ul>
                <p className="caption m-0 mt-2">Тексты попыток и запросы к ИИ не хранятся — только вердикты и оценки.</p>
              </Card>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

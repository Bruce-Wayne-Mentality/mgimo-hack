import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertOctagon, ChevronRight, Copy, EyeOff, KeyRound, Lock, ShieldCheck, Unlock, UserRound } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router";
import { Alert, Button, Card, CardTitle, EmptyState, ErrorState, Field, Input, PageHeader, Skeleton } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { PublicFrame } from "../documents/VerifyPage";
import { dateLabel, dateTimeLabel } from "../requests/api";

type Complaint = {
  id: string;
  number: string;
  category: string;
  category_label: string;
  summary?: string;
  happened_on: string | null;
  context?: string | null;
  mode: "open" | "confidential" | "anonymous";
  mode_label: string;
  status: string;
  status_label: string;
  response: string | null;
  created_at: string;
  first_response_due: string;
  resolve_due: string;
  closed_at: string | null;
  overdue: boolean;
  events: { to: string; label: string; note: string | null; at: string }[];
  author?: string;
  revealed?: boolean;
  actions?: { to: string; label: string; note_required: boolean }[];
};

const CATEGORIES = [
  { value: "grade", label: "Спорная оценка" },
  { value: "pressure", label: "Давление или некорректное поведение" },
  { value: "regulation", label: "Нарушение регламента" },
  { value: "demand", label: "Неправомерное требование" },
  { value: "other", label: "Другое" },
];

const MODES = [
  { value: "open", label: "Открыто", icon: Unlock, text: "Администратор видит, кто вы. Проще уточнить детали." },
  { value: "confidential", label: "Конфиденциально", icon: Lock, text: "Имя скрыто. Раскрыть его может только омбудсмен с записью в журнале." },
  { value: "anonymous", label: "Анонимно", icon: EyeOff, text: "Автор не сохраняется. Статус — по одноразовому коду." },
] as const;

function Timeline({ item }: { item: Complaint }) {
  return (
    <ol className="m-0 flex list-none flex-col gap-3 p-0">
      {item.events.map((event, index) => (
        <li key={index} className="flex gap-3">
          <span aria-hidden className={cn("mt-1.5 size-2.5 shrink-0 rounded-full", index === item.events.length - 1 ? "bg-primary" : "bg-line-strong")} />
          <span>
            <span className="block font-medium">{event.label}</span>
            <span className="caption block">{dateTimeLabel(event.at)}</span>
            {event.note && <span className="mt-1 block text-[15px] text-text-2">{event.note}</span>}
          </span>
        </li>
      ))}
    </ol>
  );
}

function Deadlines({ item }: { item: Complaint }) {
  return (
    <div className={cn("rounded-[var(--radius-tile)] px-4 py-3 text-sm", item.overdue ? "bg-danger-soft text-danger" : "bg-surface-2 text-text-2")}>
      {item.overdue ? "Срок превышен. Обращение подсвечено красным в очереди администратора." : (
        <>Первичный ответ — до {dateLabel(item.first_response_due)}, решение — до {dateLabel(item.resolve_due)}.</>
      )}
    </div>
  );
}

export function ComplaintsPage() {
  const list = useQuery({ queryKey: ["complaints"], queryFn: async () => (await api<{ items: Complaint[] }>("/api/complaints")).items });
  return (
    <div className="flex flex-col gap-4">
      <PageHeader eyebrow="Жалоба на несправедливость с обязательным ответом" title="Красная кнопка" />
      <Card className="bg-[#fff5f5]">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
          <span className="grid size-14 shrink-0 place-items-center rounded-[18px] bg-[#e5484d] text-white"><AlertOctagon aria-hidden className="size-7" /></span>
          <div className="flex-1">
            <p className="m-0 text-lg font-medium">Столкнулись с несправедливостью?</p>
            <p className="m-0 mt-1 text-[15px] text-text-2">Спорная оценка, давление, нарушение регламента. Администратор обязан ответить по существу: первичный ответ — до 3 рабочих дней, решение — до 10.</p>
          </div>
          <Link to="/complaints/new" className="soft inline-flex min-h-12 items-center justify-center rounded-[var(--radius-control)] bg-[#e5484d] px-5 text-[15px] font-medium text-white hover:bg-[#cf3b40]">Подать обращение</Link>
        </div>
      </Card>
      <Card aria-labelledby="mine-heading">
        <CardTitle id="mine-heading" meta={<Link to="/track" className="text-sm font-medium text-primary">Проверить по коду</Link>}>Мои обращения</CardTitle>
        {list.isPending && <Skeleton className="h-20" />}
        {list.isError && <ErrorState message={list.error.message} onRetry={() => list.refetch()} />}
        {list.data?.length === 0 && <EmptyState>Открытых и конфиденциальных обращений нет. Анонимные здесь не показываются — их статус смотрите по коду.</EmptyState>}
        <div className="flex flex-col gap-2.5">
          {list.data?.map((item) => (
            <Link key={item.id} to={`/complaints/${item.id}`} className="nudge soft flex items-center gap-3 rounded-[var(--radius-tile)] bg-surface-2 p-4 hover:bg-primary-soft">
              <span className="min-w-0 flex-1">
                <span className="caption block">{item.number} · {item.mode_label} · {dateLabel(item.created_at)}</span>
                <span className="block truncate font-medium">{item.category_label}</span>
                <span className={cn("block text-sm", item.overdue ? "text-danger" : "text-text-2")}>{item.status_label}{item.overdue ? " · срок превышен" : ""}</span>
              </span>
              <ChevronRight aria-hidden className="size-5 text-muted" />
            </Link>
          ))}
        </div>
      </Card>
      <p className="caption m-0">Концепт: в реальном вузе нужен утверждённый регламент рассмотрения и юридическая проверка работы с персональными данными.</p>
    </div>
  );
}

export function NewComplaintPage() {
  const client = useQueryClient();
  const [category, setCategory] = useState("grade");
  const [mode, setMode] = useState<(typeof MODES)[number]["value"]>("open");
  const [summary, setSummary] = useState("");
  const [context, setContext] = useState("");
  const [happened, setHappened] = useState("");
  const [copied, setCopied] = useState(false);
  const create = useMutation({
    mutationFn: () =>
      api<{ complaint: Complaint; tracking_code: string | null }>("/api/complaints", {
        method: "POST",
        body: { category, mode, summary: summary.trim(), context: context.trim() || null, happened_on: happened || null },
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["complaints"] }),
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    create.mutate();
  };
  const error = create.error instanceof ApiError ? create.error : null;

  if (create.data) {
    const { complaint, tracking_code } = create.data;
    return (
      <div className="flex max-w-[640px] flex-col gap-4">
        <PageHeader eyebrow={complaint.number} title="Обращение подано" />
        <Card className="bg-[#e3f7ea]">
          <p className="m-0 flex items-center gap-2 text-lg font-medium text-[#146c3a]"><ShieldCheck aria-hidden className="size-6" />Администратор обязан ответить</p>
          <p className="m-0 mt-1 text-text-2">Первичный ответ — до {dateLabel(complaint.first_response_due)}, решение — до {dateLabel(complaint.resolve_due)}.</p>
        </Card>
        {tracking_code ? (
          <Card>
            <CardTitle meta={<KeyRound aria-hidden className="size-5 text-primary" />}>Ваш код отслеживания</CardTitle>
            <p className="m-0 rounded-[var(--radius-tile)] bg-surface-2 p-4 text-center font-mono text-[22px] tracking-wider">{tracking_code}</p>
            <Button variant="secondary" className="mt-3 w-full" onClick={async () => { await navigator.clipboard.writeText(tracking_code); setCopied(true); }}>
              <Copy aria-hidden className="size-4" /> {copied ? "Скопировано" : "Скопировать"}
            </Button>
            <p className="caption m-0 mt-3">Сохраните код: он показан один раз. В базе хранится только его отпечаток, а автор обращения не записан нигде — восстановить код нельзя.</p>
          </Card>
        ) : (
          <Link to={`/complaints/${complaint.id}`} className="text-primary underline">Открыть обращение</Link>
        )}
        <Link to={tracking_code ? "/track" : "/complaints"} className="soft inline-flex min-h-12 items-center justify-center rounded-[var(--radius-control)] bg-primary px-5 font-medium text-on-primary">
          {tracking_code ? "Проверить статус по коду" : "К обращениям"}
        </Link>
      </div>
    );
  }

  return (
    <div className="flex max-w-[720px] flex-col gap-4">
      <PageHeader eyebrow={<Link to="/complaints" className="text-primary hover:underline">← Красная кнопка</Link>} title="Новое обращение" />
      <form onSubmit={submit} className="flex flex-col gap-4">
        <Card>
          <fieldset className="m-0 border-0 p-0">
            <legend className="mb-3 text-lg font-medium">Режим</legend>
            <div className="grid gap-2 sm:grid-cols-3">
              {MODES.map((option) => (
                <label key={option.value} className={cn("soft flex cursor-pointer flex-col gap-1.5 rounded-[var(--radius-tile)] border-2 p-3.5", mode === option.value ? "border-primary bg-primary-soft" : "border-transparent bg-surface-2 hover:bg-bg")}>
                  <input type="radio" name="mode" value={option.value} checked={mode === option.value} onChange={() => setMode(option.value)} className="sr-only" />
                  <span className="flex items-center gap-2 font-medium"><option.icon aria-hidden className="size-4" />{option.label}</span>
                  <span className="text-[13px] text-text-2">{option.text}</span>
                </label>
              ))}
            </div>
            {mode === "anonymous" && (
              <Alert tone="info" className="mt-3">Честно предупреждаем: сам текст жалобы может выдать автора (даты, детали, номер группы). Пишите только то, что нужно для проверки. IP-адрес и браузер для этой формы не записываются.</Alert>
            )}
          </fieldset>
        </Card>
        <Card className="flex flex-col gap-4">
          <Field id="category" label="Категория">
            <select id="category" value={category} onChange={(event) => setCategory(event.target.value)} className="soft min-h-13 rounded-[var(--radius-control)] bg-surface-2 px-4 text-base focus:shadow-[var(--k-focus-ring)] focus:outline-none">
              {CATEGORIES.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </Field>
          <Field id="summary" label="Суть (от 30 символов)" error={error?.fields.summary} hint={`${summary.trim().length} / 4000`}>
            <textarea id="summary" rows={5} maxLength={4000} value={summary} onChange={(event) => setSummary(event.target.value)}
              className="soft rounded-[var(--radius-control)] bg-surface-2 px-4 py-3 text-base focus:bg-surface focus:shadow-[var(--k-focus-ring)] focus:outline-none" />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field id="happened" label="Когда это было (необязательно)">
              <Input id="happened" type="date" value={happened} onChange={(event) => setHappened(event.target.value)} />
            </Field>
            <Field id="context" label="Контекст (необязательно)">
              <Input id="context" maxLength={2000} value={context} onChange={(event) => setContext(event.target.value)} placeholder="Дисциплина, мероприятие…" />
            </Field>
          </div>
          {create.isError && <Alert>{create.error.message}</Alert>}
          <Button type="submit" loading={create.isPending} disabled={summary.trim().length < 30} className="bg-[#e5484d] hover:bg-[#cf3b40]">Отправить обращение</Button>
        </Card>
      </form>
    </div>
  );
}

export function ComplaintPage() {
  const { id = "" } = useParams();
  const item = useQuery({ queryKey: ["complaints", id], queryFn: () => api<Complaint>(`/api/complaints/${id}`) });
  return (
    <div className="flex max-w-[720px] flex-col gap-4">
      <PageHeader eyebrow={<Link to="/complaints" className="text-primary hover:underline">← Красная кнопка</Link>} title={item.data ? item.data.number : "Обращение"} />
      {item.isPending && <Skeleton className="h-64" />}
      {item.isError && <ErrorState message={item.error.message} />}
      {item.data && (
        <>
          <Card>
            <p className="caption m-0">{item.data.category_label} · {item.data.mode_label}</p>
            <p className="m-0 mt-1 text-xl font-medium">{item.data.status_label}</p>
            <p className="m-0 mt-3 text-[15px] whitespace-pre-line text-text-2">{item.data.summary}</p>
            <div className="mt-4"><Deadlines item={item.data} /></div>
            {item.data.response && <Alert tone="info" className="mt-3">Ответ администратора: {item.data.response}</Alert>}
          </Card>
          <Card><CardTitle>Ход рассмотрения</CardTitle><Timeline item={item.data} /></Card>
        </>
      )}
    </div>
  );
}

export function TrackPage() {
  const [code, setCode] = useState("");
  const track = useMutation({ mutationFn: (value: string) => api<Complaint>("/api/complaints/track", { method: "POST", body: { code: value }, quiet401: true }) });
  return (
    <PublicFrame title="Статус обращения по коду">
      <Card>
        <form onSubmit={(event) => { event.preventDefault(); track.mutate(code.trim()); }} className="flex flex-col gap-3">
          <Field id="code" label="Код отслеживания" hint="Например, RB-ABCD-EFGH-JKLM. Для демо: RB-DEMO-2026-TRACK">
            <Input id="code" value={code} onChange={(event) => setCode(event.target.value.toUpperCase())} autoComplete="off" className="font-mono" />
          </Field>
          <Button type="submit" loading={track.isPending} disabled={code.trim().length < 6}>Проверить</Button>
        </form>
      </Card>
      {track.isError && <Alert>{track.error.message}</Alert>}
      {track.data && (
        <Card>
          <p className="caption m-0">{track.data.number} · {track.data.category_label} · анонимно</p>
          <p className="m-0 mt-1 text-xl font-medium">{track.data.status_label}</p>
          <div className="my-4"><Deadlines item={track.data} /></div>
          {track.data.response && <Alert tone="info" className="mb-4">Ответ: {track.data.response}</Alert>}
          <Timeline item={track.data} />
        </Card>
      )}
    </PublicFrame>
  );
}

export function AdminComplaintsPage() {
  const list = useQuery({ queryKey: ["admin-complaints"], queryFn: async () => (await api<{ items: Complaint[] }>("/api/admin/complaints")).items, refetchInterval: 30_000 });
  return (
    <div className="flex flex-col gap-4">
      <PageHeader eyebrow="Красная кнопка · кабинет администратора" title="Обращения" />
      <Card>
        {list.isPending && <Skeleton className="h-32" />}
        {list.isError && <ErrorState message={list.error.message} onRetry={() => list.refetch()} />}
        <div className="flex flex-col gap-2.5">
          {list.data?.map((item) => (
            <Link key={item.id} to={`/admin/complaints/${item.id}`} className={cn("nudge soft flex items-center gap-3 rounded-[var(--radius-tile)] p-4 hover:bg-primary-soft", item.overdue ? "bg-[#fff5f5] ring-1 ring-[#f3b8ba]" : "bg-surface-2")}>
              <span className="min-w-0 flex-1">
                <span className="caption block">{item.number} · {item.mode_label} · {dateLabel(item.created_at)}</span>
                <span className="block truncate font-medium">{item.category_label}</span>
                <span className="block text-sm text-text-2">{item.author} · {item.status_label}</span>
              </span>
              {item.overdue && <span className="shrink-0 rounded-full bg-danger px-2.5 py-1 text-[12px] font-medium text-white">срок</span>}
              <ChevronRight aria-hidden className="size-5 text-muted" />
            </Link>
          ))}
        </div>
      </Card>
    </div>
  );
}

export function AdminComplaintPage() {
  const { id = "" } = useParams();
  const client = useQueryClient();
  const item = useQuery({ queryKey: ["admin-complaints", id], queryFn: () => api<Complaint>(`/api/admin/complaints/${id}`) });
  const [note, setNote] = useState("");
  const [reason, setReason] = useState("");
  const move = useMutation({
    mutationFn: (to: string) => api<Complaint>(`/api/admin/complaints/${id}/transition`, { method: "POST", body: { to, note: note.trim() || null } }),
    onSuccess: (data) => {
      client.setQueryData(["admin-complaints", id], data);
      client.invalidateQueries({ queryKey: ["admin-complaints"], exact: true });
      setNote("");
    },
  });
  const reveal = useMutation({
    mutationFn: () => api<Complaint>(`/api/admin/complaints/${id}/reveal`, { method: "POST", body: { reason } }),
    onSuccess: (data) => client.setQueryData(["admin-complaints", id], data),
  });
  const data = item.data;
  return (
    <div className="flex flex-col gap-4">
      <PageHeader eyebrow={<Link to="/admin/complaints" className="text-primary hover:underline">← Обращения</Link>} title={data?.number ?? "Обращение"} />
      {item.isPending && <Skeleton className="h-64" />}
      {item.isError && <ErrorState message={item.error.message} />}
      {data && (
        <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-4 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
          <div className="flex flex-col gap-4">
            <Card>
              <p className="caption m-0">{data.category_label} · {data.mode_label}{data.happened_on ? ` · было ${dateLabel(data.happened_on)}` : ""}</p>
              <p className="m-0 mt-1 text-xl font-medium">{data.status_label}</p>
              <p className="m-0 mt-3 flex items-center gap-2 text-sm"><UserRound aria-hidden className="size-4 text-muted" />{data.author}</p>
              <p className="m-0 mt-3 text-[15px] whitespace-pre-line">{data.summary}</p>
              {data.context && <p className="caption m-0 mt-2">Контекст: {data.context}</p>}
              <div className="mt-4"><Deadlines item={data} /></div>
            </Card>
            <Card><CardTitle>История</CardTitle><Timeline item={data} /></Card>
          </div>
          <div className="flex flex-col gap-4">
            {data.actions && data.actions.length > 0 && (
              <Card>
                <CardTitle>Решение</CardTitle>
                <label htmlFor="note" className="text-sm text-text-2">Мотивированный ответ (обязателен для «Решено», «Отклонено», «Передано выше»)</label>
                <textarea id="note" rows={4} value={note} onChange={(event) => setNote(event.target.value)} className="soft mt-1.5 w-full rounded-[var(--radius-control)] bg-surface-2 px-4 py-3 text-base focus:bg-surface focus:shadow-[var(--k-focus-ring)] focus:outline-none" />
                <div className="mt-3 flex flex-wrap gap-2">
                  {data.actions.map((action) => (
                    <Button key={action.to} variant={action.to === "rejected" ? "danger" : action.to === "resolved" ? "primary" : "secondary"}
                      disabled={action.note_required && !note.trim()} loading={move.isPending && move.variables === action.to} onClick={() => move.mutate(action.to)}>
                      {action.label}
                    </Button>
                  ))}
                </div>
                {move.isError && <Alert className="mt-3">{move.error.message}</Alert>}
              </Card>
            )}
            {data.mode === "confidential" && !data.revealed && (
              <Card>
                <CardTitle meta={<Lock aria-hidden className="size-5 text-muted" />}>Автор скрыт</CardTitle>
                <p className="m-0 text-sm text-text-2">Раскрытие — отдельное действие омбудсмена. Причина попадёт в журнал действий.</p>
                <Input className="mt-3" value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Причина раскрытия (от 10 символов)" />
                <Button variant="secondary" className="mt-2" disabled={reason.trim().length < 10} loading={reveal.isPending} onClick={() => reveal.mutate()}>Раскрыть автора</Button>
                {reveal.isError && <Alert className="mt-3">{reveal.error.message}</Alert>}
              </Card>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

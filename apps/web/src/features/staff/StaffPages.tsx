import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ClipboardList, Megaphone, Pin, ScanLine, Timer, Trash2, Zap } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import { Alert, Button, Card, CardTitle, EmptyState, ErrorState, Field, Input, MoreLink, PageHeader, Skeleton, Switch } from "@/components/ui";
import { api } from "@/lib/api";
import { useSession } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { dateTimeLabel } from "../requests/api";

type Dashboard = {
  requests: { open: number; submitted: number; needs_info: number; overdue: number; closed_week: number; auto_issued_week: number; avg_hours: number | null; by_type: { title: string; count: number }[] };
  risk: { red: number; yellow: number; green: number; grey: number };
  at_risk: { student: string; group: string; discipline: string; discipline_id: string; reason: string; disciplines: string[] }[];
  groups: { code: string; course: number; students: number }[];
};

function Stat({ label, value, to, tone, icon: Icon }: { label: string; value: string | number; to: string; tone?: "warn" | "danger"; icon: typeof Timer }) {
  return (
    <Link to={to} className={cn("soft flex flex-col gap-2 rounded-[var(--radius-card)] p-4 shadow-k-card hover:bg-surface-2", tone === "danger" ? "bg-[#fff5f5]" : tone === "warn" ? "bg-[#fffaf0]" : "bg-surface")}>
      <Icon aria-hidden className={cn("size-5", tone === "danger" ? "text-danger" : tone === "warn" ? "text-[#8a5a00]" : "text-primary")} />
      <span className="text-[30px] leading-none font-normal tracking-[-0.03em] tabular-nums">{value}</span>
      <span className="caption">{label}</span>
    </Link>
  );
}

export function StaffHome() {
  const user = useSession().data!.user;
  const board = useQuery({ queryKey: ["staff-dashboard"], queryFn: () => api<Dashboard>("/api/staff/dashboard"), refetchInterval: 60_000 });
  const data = board.data;
  const total = data ? data.risk.red + data.risk.yellow + data.risk.green + data.risk.grey : 0;
  return (
    <div className="flex flex-col gap-4">
      {board.isPending && <Skeleton className="h-40" />}
      {board.isError && <ErrorState message={board.error.message} onRetry={() => board.refetch()} />}
      {data && (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat icon={ClipboardList} label="заявок в работе" value={data.requests.open} to="/staff/requests" />
            <Stat icon={AlertTriangle} label="просрочено по SLA" value={data.requests.overdue} to="/staff/requests?overdue=1" tone={data.requests.overdue ? "danger" : undefined} />
            <Stat icon={Timer} label="ждут ответа студента" value={data.requests.needs_info} to="/staff/requests" tone={data.requests.needs_info ? "warn" : undefined} />
            <Stat icon={Zap} label="закрыто за неделю" value={`${data.requests.closed_week}`} to="/staff/requests" />
          </div>
          <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
            <Card aria-labelledby="risk-heading">
              <CardTitle id="risk-heading" meta={<MoreLink to="/staff/grades">Журнал</MoreLink>}>Светофор факультета</CardTitle>
              {total > 0 && (
                <div className="flex h-3 overflow-hidden rounded-full" role="img" aria-label={`Вне графика ${data.risk.red}, под риском ${data.risk.yellow}, в графике ${data.risk.green}, нет данных ${data.risk.grey} (пар студент × дисциплина)`}>
                  <span className="bg-[#e5484d]" style={{ width: `${(data.risk.red / total) * 100}%` }} />
                  <span className="bg-[#f5a524]" style={{ width: `${(data.risk.yellow / total) * 100}%` }} />
                  <span className="bg-[#22a35a]" style={{ width: `${(data.risk.green / total) * 100}%` }} />
                  <span className="bg-line-strong" style={{ width: `${(data.risk.grey / total) * 100}%` }} />
                </div>
              )}
              <p className="caption m-0 mt-2">Вне графика: {data.risk.red} · под риском: {data.risk.yellow} · в графике: {data.risk.green} (студент × дисциплина)</p>
              <h3 className="mt-5 mb-2 text-[15px] font-medium">Кому стоит написать первыми</h3>
              {data.at_risk.length === 0 ? <EmptyState>Красных статусов нет.</EmptyState> : (
                <ul className="m-0 flex list-none flex-col gap-2 p-0">
                  {data.at_risk.map((row, index) => (
                    <li key={index}>
                      <Link to={`/staff/grades/${row.discipline_id}`} className="soft flex items-center gap-3 rounded-[var(--radius-tile)] bg-[#fff5f5] p-3 hover:bg-primary-soft">
                        <span aria-hidden className="size-2.5 shrink-0 rounded-full bg-[#e5484d]" />
                        <span className="min-w-0 flex-1"><span className="block truncate font-medium">{row.student} · {row.group}</span><span className="caption block truncate">{row.disciplines.length > 1 ? `вне графика по ${row.disciplines.length} дисциплинам: ${row.disciplines.join(", ")}` : `${row.discipline}: ${row.reason.toLowerCase()}`}</span></span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <div className="flex flex-col gap-4">
              <Card aria-labelledby="types-heading">
                <CardTitle id="types-heading" meta={<MoreLink to="/staff/requests">Очередь</MoreLink>}>Открытые заявки</CardTitle>
                {data.requests.by_type.length === 0 ? <EmptyState>Очередь пуста.</EmptyState> : (
                  <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
                    {data.requests.by_type.map((row) => (
                      <li key={row.title} className="flex justify-between gap-3 rounded-[10px] bg-surface-2 px-3 py-2 text-sm"><span className="truncate">{row.title}</span><span className="font-medium tabular-nums">{row.count}</span></li>
                    ))}
                  </ul>
                )}
                <p className="caption m-0 mt-3">Автовыдано справок за неделю: {data.requests.auto_issued_week}{data.requests.avg_hours !== null ? ` · среднее время ручной обработки ${data.requests.avg_hours} ч` : ""}</p>
              </Card>
              <div className="grid grid-cols-2 gap-3">
                <Link to="/staff/announcements" className="soft flex flex-col gap-2 rounded-[var(--radius-card)] bg-surface p-4 shadow-k-card hover:bg-surface-2"><Megaphone aria-hidden className="size-5 text-primary" /><span className="font-medium">Объявление</span><span className="caption">группе, курсу, факультету</span></Link>
                <Link to="/staff/check" className="soft flex flex-col gap-2 rounded-[var(--radius-card)] bg-surface p-4 shadow-k-card hover:bg-surface-2"><ScanLine aria-hidden className="size-5 text-primary" /><span className="font-medium">Проверить QR</span><span className="caption">студенческий или справку</span></Link>
              </div>
              {user.role === "admin" && (
                <div className="grid grid-cols-2 gap-3">
                  <Link to="/admin/complaints" className="soft flex flex-col gap-2 rounded-[var(--radius-card)] bg-[#fff5f5] p-4 shadow-k-card hover:bg-surface-2"><AlertTriangle aria-hidden className="size-5 text-danger" /><span className="font-medium">Красная кнопка</span><span className="caption">обращения студентов</span></Link>
                  <Link to="/admin/audit" className="soft flex flex-col gap-2 rounded-[var(--radius-card)] bg-surface p-4 shadow-k-card hover:bg-surface-2"><ClipboardList aria-hidden className="size-5 text-primary" /><span className="font-medium">Журнал действий</span><span className="caption">кто, что и когда</span></Link>
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

type Announcement = { id: string; title: string; body: string; author: string; audience: string; audience_label: string; pinned: boolean; important: boolean; created_at: string; expires_at: string | null; recipients?: number };
type Meta = { items: Announcement[]; faculties: { id: string; title: string }[]; groups: { id: string; code: string; course: number; faculty_id: string }[]; can_all: boolean };

export function StaffAnnouncementsPage() {
  const client = useQueryClient();
  const meta = useQuery({ queryKey: ["staff-announcements"], queryFn: () => api<Meta>("/api/staff/announcements") });
  const [form, setForm] = useState({ title: "", body: "", audience: "group", group_id: "", faculty_id: "", course: "1", pinned: false, important: false, days: "14" });
  const [sent, setSent] = useState<number | null>(null);
  const publish = useMutation({
    mutationFn: () =>
      api<Announcement>("/api/staff/announcements", {
        method: "POST",
        body: {
          title: form.title, body: form.body, audience: form.audience, pinned: form.pinned, important: form.important, days: Number(form.days),
          group_id: form.audience === "group" ? form.group_id || meta.data?.groups[0]?.id : null,
          faculty_id: form.audience === "faculty" || form.audience === "course" ? form.faculty_id || meta.data?.faculties[0]?.id : null,
          course: form.audience === "course" ? Number(form.course) : null,
        },
      }),
    onSuccess: (data) => {
      setSent(data.recipients ?? 0);
      setForm({ ...form, title: "", body: "" });
      client.invalidateQueries({ queryKey: ["staff-announcements"] });
    },
  });
  const archive = useMutation({
    mutationFn: (id: string) => api<void>(`/api/staff/announcements/${id}`, { method: "DELETE" }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["staff-announcements"] }),
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    setSent(null);
    publish.mutate();
  };
  const select = "soft min-h-13 w-full rounded-[var(--radius-control)] bg-surface-2 px-4 text-base focus:shadow-[var(--k-focus-ring)] focus:outline-none";
  return (
    <div className="flex flex-col gap-4">
      <PageHeader eyebrow="Попадает в центр уведомлений адресатов" title="Объявления" />
      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Card>
          <CardTitle>Новое объявление</CardTitle>
          <form onSubmit={submit} className="flex flex-col gap-3">
            <Field id="a-title" label="Заголовок"><Input id="a-title" value={form.title} maxLength={200} onChange={(event) => setForm({ ...form, title: event.target.value })} /></Field>
            <Field id="a-body" label="Текст">
              <textarea id="a-body" rows={4} maxLength={4000} value={form.body} onChange={(event) => setForm({ ...form, body: event.target.value })} className="soft rounded-[var(--radius-control)] bg-surface-2 px-4 py-3 text-base focus:bg-surface focus:shadow-[var(--k-focus-ring)] focus:outline-none" />
            </Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field id="a-aud" label="Кому">
                <select id="a-aud" className={select} value={form.audience} onChange={(event) => setForm({ ...form, audience: event.target.value })}>
                  <option value="group">Группе</option>
                  <option value="course">Курсу</option>
                  <option value="faculty">Факультету</option>
                  {meta.data?.can_all && <option value="all">Всем студентам</option>}
                </select>
              </Field>
              {form.audience === "group" && (
                <Field id="a-group" label="Группа">
                  <select id="a-group" className={select} value={form.group_id} onChange={(event) => setForm({ ...form, group_id: event.target.value })}>
                    {meta.data?.groups.map((group) => <option key={group.id} value={group.id}>{group.code}</option>)}
                  </select>
                </Field>
              )}
              {form.audience === "course" && (
                <Field id="a-course" label="Курс">
                  <select id="a-course" className={select} value={form.course} onChange={(event) => setForm({ ...form, course: event.target.value })}>
                    {[1, 2, 3, 4].map((course) => <option key={course} value={course}>{course} курс</option>)}
                  </select>
                </Field>
              )}
              {(form.audience === "faculty" || form.audience === "course") && meta.data && meta.data.faculties.length > 1 && (
                <Field id="a-fac" label="Факультет">
                  <select id="a-fac" className={select} value={form.faculty_id} onChange={(event) => setForm({ ...form, faculty_id: event.target.value })}>
                    {meta.data.faculties.map((faculty) => <option key={faculty.id} value={faculty.id}>{faculty.title}</option>)}
                  </select>
                </Field>
              )}
              <Field id="a-days" label="Актуально, дней"><Input id="a-days" type="number" min={1} max={120} value={form.days} onChange={(event) => setForm({ ...form, days: event.target.value })} /></Field>
            </div>
            <label className="flex min-h-11 items-center justify-between gap-3 text-sm"><span>Закрепить сверху</span><Switch checked={form.pinned} onChange={(event) => setForm({ ...form, pinned: event.target.checked })} /></label>
            <label className="flex min-h-11 items-center justify-between gap-3 text-sm"><span>Важное</span><Switch checked={form.important} onChange={(event) => setForm({ ...form, important: event.target.checked })} /></label>
            {publish.isError && <Alert>{publish.error.message}</Alert>}
            {sent !== null && <Alert tone="info">Опубликовано. Уведомление получили {sent} студент(ов).</Alert>}
            <Button type="submit" loading={publish.isPending} disabled={form.title.trim().length < 3 || form.body.trim().length < 3}>Опубликовать</Button>
          </form>
        </Card>
        <Card>
          <CardTitle>Опубликованные</CardTitle>
          {meta.isPending && <Skeleton className="h-32" />}
          {meta.isError && <ErrorState message={meta.error.message} />}
          {meta.data?.items.length === 0 && <EmptyState>Объявлений нет.</EmptyState>}
          <ul className="m-0 flex list-none flex-col gap-2.5 p-0">
            {meta.data?.items.map((item) => (
              <li key={item.id} className="rounded-[var(--radius-tile)] bg-surface-2 p-4">
                <div className="flex items-start justify-between gap-2">
                  <p className="m-0 font-medium">{item.pinned && <Pin aria-label="Закреплено" className="mr-1 inline size-4 text-primary" />}{item.title}</p>
                  <button onClick={() => archive.mutate(item.id)} aria-label={`Снять «${item.title}»`} className="soft grid size-9 shrink-0 place-items-center rounded-[10px] text-muted hover:bg-danger-soft hover:text-danger"><Trash2 aria-hidden className="size-4" /></button>
                </div>
                <p className="m-0 mt-1 text-sm text-text-2">{item.body}</p>
                <p className="caption m-0 mt-2">{item.audience_label} · {item.author} · {dateTimeLabel(item.created_at)}</p>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  );
}

type AuditRow = { id: string; at: string; actor: string; action: string; action_label: string; object_type: string | null; object_id: string | null; meta: Record<string, unknown> };

export function AuditPage() {
  const audit = useQuery({ queryKey: ["audit"], queryFn: async () => (await api<{ items: AuditRow[] }>("/api/admin/audit?limit=200")).items });
  return (
    <div className="flex flex-col gap-4">
      <PageHeader eyebrow="Входы, оценки, документы, обращения" title="Журнал действий" />
      <Card className="p-0 sm:p-0">
        {audit.isPending && <Skeleton className="m-4 h-40" />}
        {audit.isError && <ErrorState message={audit.error.message} />}
        <ul className="m-0 flex list-none flex-col p-0">
          {audit.data?.map((row) => (
            <li key={row.id} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 border-b border-line px-5 py-3 last:border-0">
              <span className="w-40 shrink-0 text-sm text-muted tabular-nums">{dateTimeLabel(row.at)}</span>
              <span className="font-medium">{row.action_label}</span>
              <span className="text-sm text-text-2">{row.actor}</span>
              {Object.keys(row.meta).length > 0 && <span className="caption truncate">{Object.entries(row.meta).map(([key, value]) => `${key}: ${String(value)}`).join(" · ")}</span>}
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

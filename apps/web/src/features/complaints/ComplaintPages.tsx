import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertOctagon, CheckCircle2, ChevronRight, EyeOff, Link2, Lock, Send, ShieldCheck, Unlock, X } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { Alert, Button, Card, CardTitle, EmptyState, ErrorState, Field, Input, PageHeader, Skeleton } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { dateLabel, dateTimeLabel } from "../requests/api";
import {
  CATEGORIES,
  DESIRED,
  PRIVACY,
  STATUS_TONE,
  TYPES,
  hasObscenityHint,
  useMyComplaints,
  type ComplaintBase,
  type ComplaintDetail,
  type ComplaintEvent,
  type ComplaintMessage,
  type SubmitResult,
} from "./api";

const DRAFT_KEY = "dekanat:complaint-draft";
const PRIVACY_ICONS = { named: Unlock, confidential: Lock, anonymous: EyeOff } as const;

type Draft = {
  type: string;
  category: string | null;
  link: { type: string; id: string; label: string } | null;
  text: string;
  desired: string | null;
  privacy: "named" | "confidential" | "anonymous";
};

function loadDraft(params: URLSearchParams): Draft {
  // Spec: the draft lives only in sessionStorage and never reaches the server before sending.
  let draft: Draft = { type: "unfair", category: null, link: null, text: "", desired: null, privacy: "confidential" };
  try {
    const raw = sessionStorage.getItem(DRAFT_KEY);
    if (raw) draft = { ...draft, ...(JSON.parse(raw) as Partial<Draft>) };
  } catch {
    /* private mode */
  }
  const category = params.get("category");
  if (category && CATEGORIES.some((c) => c.value === category)) draft.category = category;
  const linkType = params.get("link_type");
  if (linkType && ["discipline", "lesson", "request", "room"].includes(linkType)) {
    draft.link = { type: linkType, id: params.get("link_id") ?? "", label: (params.get("link_label") ?? params.get("link_id") ?? "").slice(0, 120) };
  }
  const room = params.get("room");
  if (room) draft = { ...draft, category: "infrastructure", link: { type: "room", id: room.slice(0, 32), label: room.slice(0, 32) } };
  const text = params.get("text");
  if (text) draft.text = text.slice(0, 3000);
  return draft;
}

export function StatusBadge({ status, label }: { status: ComplaintBase["status"]; label: string }) {
  return <span className={cn("inline-flex min-h-7 shrink-0 items-center rounded-full px-2.5 text-[13px] font-medium", STATUS_TONE[status])}>{label}</span>;
}

/** К4 — «Мои обращения» (used in Заявки → Обращения and on /complaints). */
export function ComplaintsList() {
  const list = useMyComplaints();
  return (
    <div className="flex flex-col gap-4">
      <Card className="bg-[#fff5f5]">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
          <span className="grid size-14 shrink-0 place-items-center rounded-[18px] bg-[#e5484d] text-white"><AlertOctagon aria-hidden className="size-7" /></span>
          <div className="flex-1">
            <p className="m-0 text-lg font-medium">Красная кнопка</p>
            <p className="m-0 mt-1 text-[15px] text-text-2">Несправедливость, проблема, предложение или благодарность. Каждое принятое обращение читает человек; ответ — в срок.</p>
          </div>
          <Link to="/complaints/new" className="soft inline-flex min-h-12 items-center justify-center rounded-[var(--radius-control)] bg-[#e5484d] px-5 text-[15px] font-medium text-white hover:bg-[#cf3b40]">
            Сообщить о проблеме
          </Link>
        </div>
      </Card>
      <Card aria-labelledby="mine-heading">
        <CardTitle id="mine-heading">Мои обращения</CardTitle>
        {list.isPending && <Skeleton className="h-20" />}
        {list.isError && <ErrorState message={list.error.message} onRetry={() => list.refetch()} />}
        {list.data?.length === 0 && <EmptyState>Обращений пока нет — и это хорошо.</EmptyState>}
        <div className="flex flex-col gap-2.5">
          {list.data?.map((item) => (
            <Link key={item.id} to={`/complaints/${item.id}`} className={cn("nudge soft flex items-center gap-3 rounded-[var(--radius-tile)] p-4 hover:bg-primary-soft", item.waiting_for_me ? "bg-[#fff8e8]" : "bg-surface-2")}>
              <span className="min-w-0 flex-1">
                <span className="caption block">{item.number} · {item.privacy_label} · {dateLabel(item.created_at)}</span>
                <span className="block truncate font-medium">{item.title}</span>
                <span className="caption block">{item.category_label}{item.waiting_for_me ? " · ждём вас" : ""}</span>
              </span>
              <StatusBadge status={item.status} label={item.status_label} />
              <ChevronRight aria-hidden className="size-5 shrink-0 text-muted" />
            </Link>
          ))}
        </div>
      </Card>
    </div>
  );
}

export function ComplaintsPage() {
  return (
    <div className="flex flex-col gap-4">
      <PageHeader eyebrow={<Link to="/requests" className="text-primary hover:underline">← Заявки</Link>} title="Обращения" />
      <ComplaintsList />
    </div>
  );
}

function Highlighted({ text, spans }: { text: string; spans: { start: number; end: number }[] }) {
  const parts: ReactNode[] = [];
  let cursor = 0;
  spans.forEach((span, index) => {
    parts.push(text.slice(cursor, span.start));
    parts.push(<mark key={index} className="rounded bg-[#fdecec] px-0.5 text-[#b42318]">{text.slice(span.start, span.end)}</mark>);
    cursor = span.end;
  });
  parts.push(text.slice(cursor));
  return <p className="m-0 rounded-[var(--radius-tile)] bg-surface-2 p-4 text-[15px] whitespace-pre-wrap">{parts}</p>;
}

function LinkPicker({ value, onChange }: { value: Draft["link"]; onChange: (link: Draft["link"]) => void }) {
  const [kind, setKind] = useState<string | null>(null);
  const disciplines = useQuery({ queryKey: ["study"], queryFn: () => api<{ disciplines: { id: string; title: string }[] }>("/api/study"), enabled: kind === "discipline" });
  const requests = useQuery({ queryKey: ["requests", "list"], queryFn: async () => (await api<{ items: { id: string; number: string; type: { title: string } }[] }>("/api/requests")).items, enabled: kind === "request" });
  const [room, setRoom] = useState("");
  if (value) {
    return (
      <span className="inline-flex min-h-10 items-center gap-2 self-start rounded-full bg-primary-soft py-1 pr-1 pl-3.5 text-sm text-primary-strong">
        <Link2 aria-hidden className="size-4" />
        {value.label}
        <button type="button" aria-label="Убрать привязку" onClick={() => onChange(null)} className="soft grid size-8 place-items-center rounded-full hover:bg-primary-tint"><X aria-hidden className="size-4" /></button>
      </span>
    );
  }
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-1.5">
        {[{ k: "discipline", l: "Дисциплина" }, { k: "request", l: "Заявка" }, { k: "room", l: "Аудитория" }].map((option) => (
          <button key={option.k} type="button" aria-pressed={kind === option.k} onClick={() => setKind(kind === option.k ? null : option.k)}
            className={cn("soft min-h-9 rounded-full px-3.5 text-sm", kind === option.k ? "bg-text text-surface" : "bg-surface-2 text-text-2 hover:bg-primary-soft")}>
            + {option.l}
          </button>
        ))}
      </div>
      {kind === "discipline" && (
        <div className="flex flex-wrap gap-1.5">
          {disciplines.data?.disciplines.map((d) => (
            <button key={d.id} type="button" onClick={() => onChange({ type: "discipline", id: d.id, label: d.title })} className="soft min-h-9 rounded-[10px] bg-surface-2 px-3 text-sm hover:bg-primary-soft">{d.title}</button>
          ))}
        </div>
      )}
      {kind === "request" && (
        <div className="flex flex-wrap gap-1.5">
          {requests.data?.length === 0 && <span className="caption">Заявок нет.</span>}
          {requests.data?.map((r) => (
            <button key={r.id} type="button" onClick={() => onChange({ type: "request", id: r.id, label: `${r.number} · ${r.type.title}` })} className="soft min-h-9 rounded-[10px] bg-surface-2 px-3 text-sm hover:bg-primary-soft">{r.number} · {r.type.title}</button>
          ))}
        </div>
      )}
      {kind === "room" && (
        <div className="flex gap-2">
          <Input value={room} maxLength={32} onChange={(event) => setRoom(event.target.value)} placeholder="Например, Б-118" aria-label="Аудитория" />
          <Button type="button" variant="secondary" disabled={!room.trim()} onClick={() => onChange({ type: "room", id: room.trim(), label: room.trim() })}>Добавить</Button>
        </div>
      )}
    </div>
  );
}

/** К1 → К2 → К3а/б/в: form, checking, result. */
export function NewComplaintPage() {
  const [params] = useSearchParams();
  const client = useQueryClient();
  const [draft, setDraft] = useState<Draft>(() => loadDraft(params));
  const [session, setSession] = useState<string | null>(null);
  const [result, setResult] = useState<SubmitResult | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [phase, setPhase] = useState(0);

  useEffect(() => {
    try {
      sessionStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
    } catch {
      /* ignore */
    }
  }, [draft]);

  const submit = useMutation({
    mutationFn: (text: string) =>
      api<SubmitResult>("/api/complaints", {
        method: "POST",
        body: {
          session_id: session, type: draft.type, category: draft.category, text, desired_outcome: draft.desired, privacy: draft.privacy,
          link_type: draft.link?.type ?? null, link_id: draft.link?.id ?? null, link_label: draft.link?.label ?? null,
        },
      }),
    onMutate: () => {
      setPhase(1);
      const timer = setTimeout(() => setPhase(2), 700);
      return { timer };
    },
    onSettled: (_data, _error, _vars, context) => {
      if (context?.timer) clearTimeout(context.timer);
      setPhase(0);
    },
    onSuccess: (data) => {
      setResult(data);
      if ("session_id" in data) setSession(data.session_id);
      if (data.verdict === "ACCEPT" || data.verdict === "ESCALATE") {
        try {
          sessionStorage.removeItem(DRAFT_KEY);
        } catch {
          /* ignore */
        }
        client.invalidateQueries({ queryKey: ["complaints"] });
      }
    },
  });
  const manual = useMutation({
    mutationFn: () => api<ComplaintDetail>("/api/complaints/manual-review", { method: "POST", body: { session_id: session } }),
    onSuccess: (complaint) => {
      setResult({ verdict: "ACCEPT", complaint });
      client.invalidateQueries({ queryKey: ["complaints"] });
    },
  });

  useEffect(() => {
    if (result) window.scrollTo({ top: 0, behavior: "smooth" });
  }, [result]);

  const length = draft.text.trim().length;
  const hint = useMemo(() => hasObscenityHint(draft.text), [draft.text]);
  const back = <Link to="/requests?tab=complaints" className="text-primary hover:underline">← Обращения</Link>;

  const send = (event?: FormEvent) => {
    event?.preventDefault();
    submit.mutate(draft.text.trim());
  };

  // К3а — accepted
  if (result && (result.verdict === "ACCEPT" || result.verdict === "ESCALATE")) {
    const c = result.complaint;
    return (
      <div className="flex max-w-[640px] flex-col gap-4">
        <PageHeader eyebrow={c.number} title="Обращение принято" />
        {result.help && <Alert tone="info">{result.help}</Alert>}
        <Card className="bg-[#e3f7ea]">
          <p className="m-0 flex items-center gap-2 text-lg font-medium text-[#146c3a]"><ShieldCheck aria-hidden className="size-6" />{c.status === "MODERATION" ? "Принято, проверим в течение часа" : "Его обязательно рассмотрит человек"}</p>
          <p className="m-0 mt-1 text-text-2">Взять в работу — до {dateLabel(c.take_due_at)}, ответить — до {dateLabel(c.answer_due_at)}.</p>
        </Card>
        <Card>
          <dl className="m-0 grid gap-3 sm:grid-cols-2">
            {[["Номер", c.number], ["Категория", c.category_label], ["Куда направлено", c.department], ["Кто увидит имя", c.privacy_label]].map(([label, value]) => (
              <div key={label} className="rounded-[var(--radius-tile)] bg-surface-2 px-4 py-2.5"><dt className="caption">{label}</dt><dd className="m-0 font-medium">{value}</dd></div>
            ))}
          </dl>
          <p className="caption m-0 mt-3">Заголовок и категорию уточнит ИИ после проверки — текст обращения он не меняет. Черновики и технические данные удалены.</p>
        </Card>
        <Link to={`/complaints/${c.id}`} className="soft inline-flex min-h-12 items-center justify-center rounded-[var(--radius-control)] bg-primary px-5 font-medium text-on-primary">Открыть обращение</Link>
      </div>
    );
  }

  return (
    <div className="flex max-w-[720px] flex-col gap-4">
      <PageHeader eyebrow={back} title="Сообщить о проблеме" />
      {phase > 0 && (
        <Card aria-live="polite" className="flex items-center gap-3">
          <span className="size-5 animate-spin rounded-full border-2 border-primary border-t-transparent" aria-hidden />
          <span className="text-[15px]">{phase === 1 ? "Проверяем формулировки…" : "Подбираем исполнителя…"}</span>
        </Card>
      )}
      {result?.verdict === "REJECT_OBSCENE" && (
        <Card className="ring-2 ring-[#f3b8ba]">
          <CardTitle>Нужна правка</CardTitle>
          <p className="m-0 mb-3 text-[15px] text-text-2">{result.message}</p>
          <Highlighted text={draft.text} spans={result.spans} />
          <p className="caption m-0 mt-3">Резкая критика допустима — убрать нужно только брань. Исправьте текст ниже и отправьте снова.</p>
        </Card>
      )}
      {result?.verdict === "ASK_DETAILS" && (
        <Card className="ring-2 ring-[#ffd27a]">
          <CardTitle>Нужно подробнее</CardTitle>
          <p className="m-0 mb-3 text-[15px] text-text-2">{result.message}</p>
          <div className="flex flex-col gap-3">
            {result.missing.map((item) => (
              <Field key={item.code} id={`q-${item.code}`} label={item.question}>
                <Input id={`q-${item.code}`} value={answers[item.code] ?? ""} onChange={(event) => setAnswers({ ...answers, [item.code]: event.target.value })} />
              </Field>
            ))}
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button type="button" onClick={() => {
              const extra = result.missing.map((item) => answers[item.code]?.trim()).filter(Boolean).join(". ");
              const text = extra ? `${draft.text.trim()}\n${extra}.` : draft.text;
              setDraft({ ...draft, text });
              setAnswers({});
              submit.mutate(text.trim());
            }} loading={submit.isPending}>Дополнить и отправить</Button>
            {result.can_manual_review && <Button type="button" variant="secondary" loading={manual.isPending} onClick={() => manual.mutate()}>Отправить на ручную проверку</Button>}
          </div>
          {manual.isError && <Alert className="mt-3">{manual.error.message}</Alert>}
        </Card>
      )}

      <form onSubmit={send} className="flex flex-col gap-4">
        <Card className="flex flex-col gap-4">
          <div role="radiogroup" aria-label="Тип обращения" className="grid grid-cols-2 gap-1 rounded-[var(--radius-control)] bg-surface-2 p-1 sm:grid-cols-4">
            {TYPES.map((option) => (
              <button key={option.value} type="button" role="radio" aria-checked={draft.type === option.value}
                onClick={() => setDraft({ ...draft, type: option.value, privacy: option.value === "unfair" ? "confidential" : draft.privacy })}
                className={cn("soft min-h-10 rounded-[10px] text-sm", draft.type === option.value ? "bg-surface font-medium shadow-k-card" : "text-text-2")}>
                {option.label}
              </button>
            ))}
          </div>
          <div>
            <p className="m-0 mb-1.5 text-sm font-medium text-text-2">Категория <span className="font-normal text-muted">(необязательно — подскажет ИИ)</span></p>
            <div className="flex flex-wrap gap-1.5">
              {CATEGORIES.map((option) => (
                <button key={option.value} type="button" aria-pressed={draft.category === option.value} onClick={() => setDraft({ ...draft, category: draft.category === option.value ? null : option.value })}
                  className={cn("soft min-h-9 rounded-full px-3.5 text-sm", draft.category === option.value ? "bg-primary text-on-primary" : "bg-surface-2 text-text-2 hover:bg-primary-soft")}>
                  {option.label}
                </button>
              ))}
            </div>
          </div>
          <div>
            <p className="m-0 mb-1.5 text-sm font-medium text-text-2">Привязка <span className="font-normal text-muted">(необязательно)</span></p>
            <LinkPicker value={draft.link} onChange={(link) => setDraft({ ...draft, link })} />
          </div>
          <Field id="text" label="Что произошло" hint={`${length} / 3000 · от 30 символов`}>
            <textarea id="text" rows={6} maxLength={3000} value={draft.text} onChange={(event) => setDraft({ ...draft, text: event.target.value })}
              placeholder="Что произошло, когда и где, чего вы хотите добиться"
              className="soft rounded-[var(--radius-control)] bg-surface-2 px-4 py-3 text-base focus:bg-surface focus:shadow-[var(--k-focus-ring)] focus:outline-none" />
          </Field>
          {hint && <p className="m-0 -mt-2 text-[13px] text-[#8a5a00]">В тексте есть ненормативная лексика — её попросят убрать.</p>}
          <div>
            <p className="m-0 mb-1.5 text-sm font-medium text-text-2">Чего вы хотите <span className="font-normal text-muted">(необязательно)</span></p>
            <div className="flex flex-wrap gap-1.5">
              {DESIRED.map((option) => (
                <button key={option.value} type="button" aria-pressed={draft.desired === option.value} onClick={() => setDraft({ ...draft, desired: draft.desired === option.value ? null : option.value })}
                  className={cn("soft min-h-9 rounded-full px-3.5 text-sm", draft.desired === option.value ? "bg-text text-surface" : "bg-surface-2 text-text-2 hover:bg-primary-soft")}>
                  {option.label}
                </button>
              ))}
            </div>
          </div>
        </Card>
        <Card>
          <fieldset className="m-0 border-0 p-0">
            <legend className="mb-3 text-[15px] font-medium">Кто увидит моё имя</legend>
            <div className="flex flex-col gap-2">
              {PRIVACY.map((option) => {
                const Icon = PRIVACY_ICONS[option.value];
                return (
                  <label key={option.value} className={cn("soft flex cursor-pointer gap-3 rounded-[var(--radius-tile)] border-2 p-3.5", draft.privacy === option.value ? "border-primary bg-primary-soft" : "border-transparent bg-surface-2 hover:bg-bg")}>
                    <input type="radio" name="privacy" value={option.value} checked={draft.privacy === option.value} onChange={() => setDraft({ ...draft, privacy: option.value })} className="sr-only" />
                    <Icon aria-hidden className="mt-0.5 size-5 shrink-0 text-primary" />
                    <span><span className="block font-medium">{option.label}</span><span className="block text-[13px] text-text-2">{option.text}</span></span>
                  </label>
                );
              })}
            </div>
          </fieldset>
          <p className="caption m-0 mt-3">
            Текст проверит ИИ на мат и оскорбления: сначала локальная модель на нашем сервере, потом GigaChat получит копию без ваших личных данных. После принятия черновики и технические данные удаляются, IP и браузер не записываются.
          </p>
          {submit.isError && <Alert className="mt-3">{submit.error instanceof ApiError && submit.error.status === 429 ? submit.error.message : submit.error.message}</Alert>}
          <Button type="submit" className="mt-4 w-full bg-[#e5484d] hover:bg-[#cf3b40]" disabled={length < 30} loading={submit.isPending}>
            <Send aria-hidden className="size-4" /> Отправить
          </Button>
        </Card>
      </form>
    </div>
  );
}

const TRACK: ComplaintBase["status"][] = ["NEW", "IN_PROGRESS", "ANSWERED", "CLOSED"];

export function Tracker({ status, events }: { status: ComplaintBase["status"]; events: ComplaintEvent[] }) {
  const reached = new Set(events.map((event) => event.to));
  const terminal = ["WITHDRAWN", "RETURNED"].includes(status);
  return (
    <ol className="m-0 flex list-none flex-col gap-3 p-0">
      {(terminal ? [...TRACK.slice(0, 1), status] : status === "MODERATION" ? ["MODERATION", ...TRACK] : TRACK).map((step) => {
        const event = [...events].reverse().find((item) => item.to === step);
        const done = reached.has(step as ComplaintBase["status"]);
        const labels: Record<string, string> = { MODERATION: "На проверке", NEW: "Принято", IN_PROGRESS: "В работе", ANSWERED: "Есть ответ", CLOSED: "Закрыто", WITHDRAWN: "Отозвано", RETURNED: "Возвращено автору" };
        return (
          <li key={step} className="flex items-start gap-3">
            <span aria-hidden className={cn("mt-0.5 grid size-6 shrink-0 place-items-center rounded-full", done ? "bg-primary text-on-primary" : "bg-surface-2 text-muted")}>
              {done ? <CheckCircle2 className="size-4" /> : <span className="size-2 rounded-full bg-line-strong" />}
            </span>
            <span><span className={cn("block", step === status ? "font-medium" : done ? "" : "text-muted")}>{labels[step]}</span>{event && <span className="caption block">{dateTimeLabel(event.at)}</span>}</span>
          </li>
        );
      })}
    </ol>
  );
}

export function Thread({ messages }: { messages: ComplaintMessage[] }) {
  if (!messages.length) return <p className="caption m-0">Сообщений пока нет.</p>;
  const kinds: Record<string, string> = { answer: "Ответ", need_info: "Запрос информации", feedback: "Несогласие", message: "" };
  return (
    <div className="flex flex-col gap-2.5">
      {messages.map((m) => (
        <div key={m.id} className={cn("max-w-[88%] rounded-[var(--radius-tile)] px-4 py-3", m.from_role === "student" ? "self-end bg-primary text-on-primary" : m.kind === "answer" ? "self-start bg-[#e3f7ea]" : "self-start bg-surface-2")}>
          <p className={cn("m-0 text-[12px]", m.from_role === "student" ? "opacity-80" : "text-muted")}>
            {m.from_role === "student" ? "Студент" : m.author ?? "Деканат"}{kinds[m.kind] ? ` · ${kinds[m.kind]}` : ""} · {dateTimeLabel(m.at)}
          </p>
          <p className="m-0 mt-0.5 text-[15px] break-words whitespace-pre-wrap">{m.body ?? "Текст удалён"}</p>
        </div>
      ))}
    </div>
  );
}

/** К5 — карточка обращения. */
export function ComplaintPage() {
  const { id = "" } = useParams();
  const client = useQueryClient();
  const navigate = useNavigate();
  const item = useQuery({ queryKey: ["complaints", id], queryFn: () => api<ComplaintDetail>(`/api/complaints/${id}`), refetchInterval: 30_000 });
  const [text, setText] = useState("");
  const [disagree, setDisagree] = useState(false);
  const [comment, setComment] = useState("");
  const set = (data: ComplaintDetail) => {
    client.setQueryData(["complaints", id], data);
    client.invalidateQueries({ queryKey: ["complaints"], exact: true });
  };
  const message = useMutation({ mutationFn: () => api<ComplaintDetail>(`/api/complaints/${id}/messages`, { method: "POST", body: { text } }), onSuccess: (data) => { setText(""); set(data); } });
  const feedback = useMutation({
    mutationFn: (resolved: boolean) => api<ComplaintDetail>(`/api/complaints/${id}/feedback`, { method: "POST", body: { resolved, comment: resolved ? null : comment } }),
    onSuccess: (data) => { setDisagree(false); set(data); },
  });
  const withdraw = useMutation({ mutationFn: () => api<void>(`/api/complaints/${id}`, { method: "DELETE" }), onSuccess: () => item.refetch() });
  const data = item.data;
  return (
    <div className="flex flex-col gap-4">
      <PageHeader eyebrow={<Link to="/requests?tab=complaints" className="text-primary hover:underline">← Обращения</Link>} title={data?.title ?? "Обращение"}>
        {data && (
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={data.status} label={data.status_label} />
            <span className="caption">{data.number} · {data.type_label} · {data.privacy_label}</span>
          </div>
        )}
      </PageHeader>
      {item.isPending && <Skeleton className="h-64" />}
      {item.isError && <ErrorState message={item.error.message} />}
      {data && (
        <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
          <div className="flex flex-col gap-4">
            <Card>
              <CardTitle>Ход рассмотрения</CardTitle>
              <Tracker status={data.status} events={data.events} />
              <p className={cn("m-0 mt-4 rounded-[var(--radius-tile)] px-4 py-3 text-sm", data.overdue ? "bg-danger-soft text-danger" : "bg-surface-2 text-text-2")}>
                {data.overdue ? "Срок превышен — обращение подсвечено в очереди." : `${data.department}. Взять в работу — до ${dateLabel(data.take_due_at)}, ответ — до ${dateLabel(data.answer_due_at)}.`}
              </p>
              {data.can_withdraw && (
                <Button variant="ghost" className="mt-3 text-danger hover:bg-danger-soft" loading={withdraw.isPending} onClick={() => withdraw.mutate()}>Отозвать обращение</Button>
              )}
            </Card>
            {data.status === "RETURNED" && (
              <Card className="bg-[#fff5f5]">
                <CardTitle>Возвращено с комментарием</CardTitle>
                <p className="m-0 text-[15px]">{data.return_comment}</p>
                <Button className="mt-3" onClick={() => navigate(`/complaints/new?text=${encodeURIComponent(data.text ?? "")}`)}>Исправить и отправить заново</Button>
              </Card>
            )}
          </div>
          <div className="flex flex-col gap-4">
            <Card>
              <CardTitle>Текст обращения</CardTitle>
              {data.link_label && <p className="caption m-0 mb-2 flex items-center gap-1.5"><Link2 aria-hidden className="size-4" />{data.link_label}</p>}
              <p className="m-0 text-[15px] whitespace-pre-wrap">{data.text ?? "Текст удалён после отзыва."}</p>
              {data.desired_label && <p className="caption m-0 mt-2">Чего хочу: {data.desired_label}</p>}
            </Card>
            <Card>
              <CardTitle>Переписка</CardTitle>
              <Thread messages={data.messages} />
              {data.status === "ANSWERED" && (
                <div className="mt-4 rounded-[var(--radius-tile)] bg-surface-2 p-4">
                  <p className="m-0 font-medium">Проблема решена?</p>
                  {disagree ? (
                    <div className="mt-2 flex flex-col gap-2">
                      <textarea rows={3} value={comment} onChange={(event) => setComment(event.target.value)} placeholder="С чем вы не согласны (от 10 символов)"
                        className="soft rounded-[var(--radius-control)] bg-surface px-4 py-3 text-base focus:shadow-[var(--k-focus-ring)] focus:outline-none" />
                      <div className="flex gap-2">
                        <Button disabled={comment.trim().length < 10} loading={feedback.isPending} onClick={() => feedback.mutate(false)}>Передать выше</Button>
                        <Button variant="ghost" onClick={() => setDisagree(false)}>Отмена</Button>
                      </div>
                    </div>
                  ) : (
                    <div className="mt-2 flex flex-wrap gap-2">
                      <Button loading={feedback.isPending} onClick={() => feedback.mutate(true)}>Да, решена</Button>
                      {data.can_escalate && <Button variant="secondary" onClick={() => setDisagree(true)}>Не согласен — передать выше</Button>}
                    </div>
                  )}
                  {feedback.isError && <Alert className="mt-2">{feedback.error.message}</Alert>}
                </div>
              )}
              {data.can_message && (
                <form onSubmit={(event) => { event.preventDefault(); if (text.trim()) message.mutate(); }} className="mt-4 flex flex-col gap-2">
                  <label htmlFor="msg" className="sr-only">Сообщение</label>
                  <textarea id="msg" rows={3} maxLength={3000} value={text} onChange={(event) => setText(event.target.value)}
                    placeholder={data.status === "NEED_INFO" ? "Ответьте на запрос — срок рассмотрения продолжится" : "Сообщение исполнителю"}
                    className="soft rounded-[var(--radius-control)] bg-surface-2 px-4 py-3 text-base focus:bg-surface focus:shadow-[var(--k-focus-ring)] focus:outline-none" />
                  {message.isError && <Alert>{message.error.message}</Alert>}
                  <Button type="submit" className="self-end" disabled={!text.trim()} loading={message.isPending}><Send aria-hidden className="size-4" /> Отправить</Button>
                </form>
              )}
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}

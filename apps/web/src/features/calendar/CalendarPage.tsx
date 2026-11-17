import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, CalendarPlus, ClipboardList, Copy, GraduationCap, MapPin, Target, type LucideIcon } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router";
import { Alert, Button, Card, CardTitle, EmptyState, ErrorState, PageHeader, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { addDays, dayLabel, moscowDate, timeLabel } from "../schedule/lessons";

type Event = {
  id: string;
  kind: "lesson" | "deadline" | "exam" | "request" | "booking";
  title: string;
  subtitle: string | null;
  starts_at: string;
  ends_at: string;
  all_day: boolean;
  done?: boolean;
  place: string | null;
  link: string;
};

const KINDS: { key: Event["kind"]; label: string; icon: LucideIcon; tone: string }[] = [
  { key: "lesson", label: "Пары", icon: BookOpen, tone: "bg-primary-soft text-primary" },
  { key: "deadline", label: "Дедлайны", icon: Target, tone: "bg-[#fff4dc] text-[#8a5a00]" },
  { key: "exam", label: "Сессия", icon: GraduationCap, tone: "bg-[#fdecec] text-[#b42318]" },
  { key: "request", label: "Заявки", icon: ClipboardList, tone: "bg-[#e3f7ea] text-[#146c3a]" },
];

function Countdown({ events }: { events: Event[] }) {
  const now = Date.now();
  const next = events.find((event) => event.kind === "lesson" && new Date(event.ends_at).getTime() > now);
  if (!next) return null;
  const minutes = Math.round((new Date(next.starts_at).getTime() - now) / 60000);
  const running = minutes <= 0;
  const text = running ? "Пара идёт сейчас" : minutes < 60 ? `До следующей пары ${minutes} мин` : minutes < 24 * 60 ? `До следующей пары ${Math.floor(minutes / 60)} ч ${minutes % 60} мин` : `Следующая пара ${dayLabel(moscowDate(new Date(next.starts_at)))}`;
  return (
    <Card className="bg-primary text-on-primary">
      <p className="m-0 text-[13px] opacity-80">{text}</p>
      <p className="m-0 mt-1 text-[22px] font-medium tracking-[-0.01em]">{next.title}</p>
      <p className="m-0 mt-1 flex items-center gap-1.5 text-[14px] opacity-90"><MapPin aria-hidden className="size-4" />{next.place ?? "аудитория уточняется"} · {timeLabel(next.starts_at)}</p>
    </Card>
  );
}

function Subscription() {
  const client = useQueryClient();
  const status = useQuery({ queryKey: ["ics"], queryFn: () => api<{ active: boolean; created_at: string | null }>("/api/calendar/ics") });
  const [link, setLink] = useState<{ url: string; webcal: string } | null>(null);
  const [copied, setCopied] = useState(false);
  const issue = useMutation({
    mutationFn: () => api<{ url: string; webcal: string }>("/api/calendar/ics", { method: "POST" }),
    onSuccess: (data) => {
      setLink(data);
      client.invalidateQueries({ queryKey: ["ics"] });
    },
  });
  const revoke = useMutation({
    mutationFn: () => api<void>("/api/calendar/ics", { method: "DELETE" }),
    onSuccess: () => {
      setLink(null);
      client.invalidateQueries({ queryKey: ["ics"] });
    },
  });
  return (
    <Card aria-labelledby="ics-heading">
      <CardTitle id="ics-heading" meta={<CalendarPlus aria-hidden className="size-5 text-primary" />}>В календарь телефона</CardTitle>
      <p className="m-0 text-sm text-text-2">Персональная ссылка только для чтения: пары, дедлайны и экзамены сами появятся в Google, Apple или Яндекс Календаре и будут обновляться.</p>
      {link ? (
        <div className="mt-4 flex flex-col gap-2">
          <code className="block rounded-[var(--radius-tile)] bg-surface-2 p-3 text-[12px] break-all">{link.url}</code>
          <div className="flex flex-wrap gap-2">
            <a href={link.webcal} className="soft inline-flex min-h-11 items-center rounded-[var(--radius-control)] bg-primary px-4 text-sm font-medium text-on-primary hover:bg-primary-hover">Подписаться</a>
            <Button variant="secondary" className="min-h-11" onClick={async () => { await navigator.clipboard.writeText(link.url); setCopied(true); }}>
              <Copy aria-hidden className="size-4" /> {copied ? "Скопировано" : "Скопировать"}
            </Button>
          </div>
          <p className="caption m-0">Ссылку видно только сейчас: на сервере хранится лишь её отпечаток. Не пересылайте её — это доступ к вашему расписанию.</p>
        </div>
      ) : (
        <div className="mt-4 flex flex-wrap gap-2">
          <Button onClick={() => issue.mutate()} loading={issue.isPending}>{status.data?.active ? "Выпустить новую ссылку" : "Получить ссылку"}</Button>
          {status.data?.active && <Button variant="ghost" className="text-danger hover:bg-danger-soft" loading={revoke.isPending} onClick={() => revoke.mutate()}>Отключить</Button>}
        </div>
      )}
      {status.data?.active && !link && <p className="caption m-0 mt-2">Ссылка активна. Новая ссылка отключит старую.</p>}
      {(issue.isError || revoke.isError) && <Alert className="mt-3">{(issue.error ?? revoke.error)?.message}</Alert>}
    </Card>
  );
}

export function CalendarPage() {
  const today = moscowDate();
  const [range] = useState({ start: today, finish: addDays(today, 27) });
  const [hidden, setHidden] = useState<Set<Event["kind"]>>(new Set());
  const feed = useQuery({
    queryKey: ["calendar", range],
    queryFn: () => api<{ events: Event[] }>(`/api/calendar?start=${range.start}&finish=${range.finish}`),
  });
  const events = useMemo(() => (feed.data?.events ?? []).filter((event) => !hidden.has(event.kind)), [feed.data, hidden]);
  const days = useMemo(() => {
    const map = new Map<string, Event[]>();
    for (const event of events) {
      const day = moscowDate(new Date(event.starts_at));
      map.set(day, [...(map.get(day) ?? []), event]);
    }
    return [...map.entries()];
  }, [events]);

  return (
    <div className="flex flex-col gap-4">
      <PageHeader eyebrow="Пары, дедлайны, сессия и заявки в одной ленте" title="Календарь" />
      {feed.data && <Countdown events={feed.data.events} />}
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Фильтр событий">
        {KINDS.map((kind) => {
          const on = !hidden.has(kind.key);
          return (
            <button
              key={kind.key}
              aria-pressed={on}
              onClick={() => {
                const next = new Set(hidden);
                if (on) next.add(kind.key);
                else next.delete(kind.key);
                setHidden(next);
              }}
              className={cn("soft inline-flex min-h-10 items-center gap-2 rounded-[10px] px-3.5 text-sm", on ? "bg-surface font-medium text-text shadow-k-card" : "bg-transparent text-muted line-through")}
            >
              <kind.icon aria-hidden className="size-4" />
              {kind.label}
            </button>
          );
        })}
      </div>
      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <div className="flex flex-col gap-4">
          {feed.isPending && <Skeleton className="h-64" />}
          {feed.isError && <ErrorState message={feed.error.message} onRetry={() => feed.refetch()} />}
          {feed.data && days.length === 0 && <EmptyState>Событий нет.</EmptyState>}
          {days.map(([day, items]) => (
            <Card key={day} aria-label={dayLabel(day)} className="p-4 sm:p-5">
              <h2 className="m-0 mb-3 text-[15px] font-medium first-letter:uppercase">{day === today ? "Сегодня, " : ""}{dayLabel(day)}</h2>
              <ul className="m-0 flex list-none flex-col gap-2 p-0">
                {items.map((event) => {
                  const kind = KINDS.find((item) => item.key === event.kind)!;
                  return (
                    <li key={event.id}>
                      <Link to={event.link} className={cn("soft flex items-center gap-3 rounded-[var(--radius-tile)] bg-surface-2 p-3 hover:bg-primary-soft", event.done && "opacity-60")}>
                        <span className={cn("grid size-9 shrink-0 place-items-center rounded-[10px]", kind.tone)}><kind.icon aria-hidden className="size-[18px]" /></span>
                        <span className="min-w-0 flex-1">
                          <span className={cn("block truncate text-[15px] font-medium", event.done && "line-through")}>{event.title}</span>
                          <span className="caption block truncate">{[event.subtitle, event.place].filter(Boolean).join(" · ")}</span>
                        </span>
                        <span className="shrink-0 text-right text-sm tabular-nums text-text-2">{event.all_day ? "до 23:59" : timeLabel(event.starts_at)}</span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </Card>
          ))}
        </div>
        <Subscription />
      </div>
    </div>
  );
}

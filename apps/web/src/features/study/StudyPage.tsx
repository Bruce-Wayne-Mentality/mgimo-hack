import { CalendarClock, ChevronRight, HelpCircle } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { Card, CardTitle, EmptyState, ErrorState, PageHeader, Skeleton } from "@/components/ui";
import { cn } from "@/lib/cn";
import { daysLeftLabel, shortDate, useStudy, type DisciplineSummary, type Forecast, type StudyOverview } from "./api";
import { LevelBadge, MarkLabel, ScoreBar } from "./parts";

const TABS = [
  { key: "now", label: "Текущий семестр" },
  { key: "session", label: "Сессия" },
  { key: "history", label: "Прошлые семестры" },
] as const;

type Tab = (typeof TABS)[number]["key"];

function ForecastCard({ forecast }: { forecast: Forecast }) {
  const tone = forecast.status === "at_risk" ? "bg-[#fff8e8]" : forecast.status === "unknown" ? "bg-surface" : "bg-[#e3f7ea]";
  return (
    <Card aria-labelledby="forecast-heading" className={tone}>
      <CardTitle id="forecast-heading">Прогноз стипендии</CardTitle>
      <p className="m-0 text-[17px] font-medium">{forecast.label}</p>
      <ul className="m-0 mt-3 flex list-none flex-col gap-1.5 p-0">
        {forecast.rows.map((row) => (
          <li key={row.id} className="flex items-center justify-between gap-3 rounded-[var(--radius-tile)] bg-surface/70 px-3 py-2 text-sm">
            <Link to={`/study/${row.id}`} className="min-w-0 truncate hover:text-primary">{row.title}</Link>
            <span className={cn("shrink-0 tabular-nums", row.ok === false ? "font-medium text-[#8a5a00]" : "text-text-2")}>
              {row.projected === null ? "рано судить" : `≈ ${row.projected} · ${row.mark}`}
              {row.need !== null && ` · нужно ${row.need}% оставшегося`}
            </span>
          </li>
        ))}
      </ul>
      <p className="caption m-0 mt-3">{forecast.note}</p>
    </Card>
  );
}

export function RulesPanel({ rules }: { rules: string[] }) {
  return (
    <details className="group rounded-[var(--radius-card)] bg-surface shadow-k-card">
      <summary className="soft flex min-h-14 cursor-pointer list-none items-center gap-3 rounded-[var(--radius-card)] px-5 font-medium hover:bg-surface-2 [&::-webkit-details-marker]:hidden">
        <HelpCircle aria-hidden className="size-5 text-primary" />
        Как это считается
        <ChevronRight aria-hidden className="ml-auto size-5 text-muted transition-transform group-open:rotate-90" />
      </summary>
      <ul className="m-0 flex list-none flex-col gap-2 px-5 pt-1 pb-5 text-[15px] text-text-2">
        {rules.map((rule) => (
          <li key={rule} className="flex gap-2.5"><span aria-hidden className="mt-2 size-1.5 shrink-0 rounded-full bg-primary" />{rule}</li>
        ))}
      </ul>
    </details>
  );
}

export function DisciplineCard({ item }: { item: DisciplineSummary }) {
  const primary = item.actions[0];
  return (
    <article className="flex flex-col gap-3 rounded-[var(--radius-card)] bg-surface p-5 shadow-k-card">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Link to={`/study/${item.id}`} className="text-[17px] font-medium tracking-[-0.01em] hover:text-primary">
            {item.title}
          </Link>
          <p className="caption m-0 mt-0.5">{item.control_label} · {item.credits} з. е.</p>
        </div>
        <LevelBadge level={item.risk.level} label={item.risk.label} />
      </div>
      <div>
        <div className="mb-1 flex items-baseline justify-between text-sm">
          <span><span className="text-[22px] font-medium tracking-[-0.02em] tabular-nums">{item.risk.points}</span> <span className="text-muted">из 100</span></span>
          {item.risk.pace !== null && <span className="caption">темп {Math.round(item.risk.pace * 100)}%</span>}
        </div>
        <ScoreBar points={item.risk.points} expected={item.expected_by_today} threshold={item.threshold} level={item.risk.level} />
      </div>
      <p className="m-0 min-h-5 text-[14px] text-text-2">
        {item.risk.reasons[0]?.text ??
          (item.risk.level === "grey" ? "Ни один срок ещё не наступил" : "Всё по плану")}
        {item.next_checkpoint && (
          <span className="block text-muted">
            Дальше: {item.next_checkpoint.title}, {daysLeftLabel(item.next_checkpoint.days_left)}
          </span>
        )}
      </p>
      <div className="mt-auto flex flex-wrap gap-2">
        <Link to={`/study/${item.id}`} className="soft inline-flex min-h-10 items-center rounded-[10px] bg-primary-soft px-4 text-sm font-medium text-primary-strong hover:bg-primary-tint">
          Подробнее
        </Link>
        {primary && item.risk.level !== "green" && item.risk.level !== "grey" && (
          <Link to={primary.link} className="soft inline-flex min-h-10 items-center rounded-[10px] px-3 text-sm font-medium text-primary hover:bg-primary-soft">
            {primary.label}
          </Link>
        )}
      </div>
    </article>
  );
}

function Summary({ data }: { data: StudyOverview }) {
  const { counts } = data.summary;
  const chips = [
    { level: "red" as const, label: "вне графика", value: counts.red },
    { level: "yellow" as const, label: "под риском", value: counts.yellow },
    { level: "green" as const, label: "в графике", value: counts.green },
    { level: "grey" as const, label: "нет данных", value: counts.grey },
  ].filter((chip) => chip.value > 0);
  return (
    <Card className="bg-primary text-on-primary">
      <p className="m-0 text-[13px] opacity-80">Как у меня дела · {data.semester === "2026-осень" ? "осень 2026" : data.semester}</p>
      <p className="m-0 mt-1 text-[26px] leading-tight font-normal tracking-[-0.02em] sm:text-[30px]">{data.summary.headline}</p>
      <div className="mt-4 flex flex-wrap gap-2">
        {chips.map((chip) => (
          <span key={chip.level} className="inline-flex min-h-8 items-center gap-2 rounded-full bg-white/15 px-3 text-sm">
            <span aria-hidden className={cn("size-2 rounded-full", { red: "bg-[#ff8a8f]", yellow: "bg-[#ffd27a]", green: "bg-[#7ee2a5]", grey: "bg-white/60" }[chip.level])} />
            {chip.value} {chip.label}
          </span>
        ))}
        {data.gpa !== null && <span className="inline-flex min-h-8 items-center rounded-full bg-white/15 px-3 text-sm">средний балл {data.gpa.toFixed(2)}</span>}
      </div>
    </Card>
  );
}

function Dynamics({ data }: { data: StudyOverview }) {
  if (!data.dynamics.length) {
    return <EmptyState>Закрытых семестров пока нет — средний балл появится после первой сессии.</EmptyState>;
  }
  const max = 5;
  return (
    <div className="flex flex-col gap-4">
      <Card aria-labelledby="dyn-heading">
        <CardTitle id="dyn-heading" meta={data.gpa !== null && <span className="caption">общий {data.gpa.toFixed(2)}</span>}>Средний балл по семестрам</CardTitle>
        <div className="flex h-40 items-end gap-3" role="list" aria-label="Средний балл по семестрам">
          {data.dynamics.map((semester) => (
            <div key={semester.no} role="listitem" className="flex flex-1 flex-col items-center gap-2">
              <span className="text-sm font-medium tabular-nums">{semester.average?.toFixed(2) ?? "—"}</span>
              <div className="flex h-28 w-full max-w-16 items-end rounded-[10px] bg-surface-2">
                <div className="w-full rounded-[10px] bg-primary" style={{ height: `${((semester.average ?? 0) - 2) / (max - 2) * 100}%` }} />
              </div>
              <span className="caption text-center">{semester.label}</span>
            </div>
          ))}
        </div>
      </Card>
      {[...data.dynamics].reverse().map((semester) => (
        <Card key={semester.no} aria-label={semester.label}>
          <CardTitle>{semester.label}</CardTitle>
          <ul className="m-0 flex list-none flex-col p-0">
            {semester.items.map((item) => (
              <li key={item.title} className="flex items-center justify-between gap-3 border-b border-line py-2.5 last:border-0">
                <span className="min-w-0"><span className="block truncate">{item.title}</span><span className="caption">{item.control_label} · {item.credits} з. е.</span></span>
                <MarkLabel mark={item.mark} />
              </li>
            ))}
          </ul>
        </Card>
      ))}
    </div>
  );
}

function Session({ data }: { data: StudyOverview }) {
  if (!data.session.length) return <EmptyState>Сессия ещё не запланирована.</EmptyState>;
  return (
    <Card aria-labelledby="session-heading">
      <CardTitle id="session-heading">Зачёты и экзамены</CardTitle>
      <ul className="m-0 flex list-none flex-col gap-2.5 p-0">
        {data.session.map((row) => (
          <li key={row.discipline_id}>
            <Link to={`/study/${row.discipline_id}`} className="nudge soft flex items-center gap-4 rounded-[var(--radius-tile)] bg-surface-2 p-4 hover:bg-primary-soft">
              <span className="grid w-14 shrink-0 place-items-center rounded-[12px] bg-surface py-2 text-center shadow-k-card">
                <span className="text-[20px] leading-none font-medium tabular-nums">{new Intl.DateTimeFormat("ru", { day: "numeric", timeZone: "Europe/Moscow" }).format(new Date(row.at))}</span>
                <span className="caption">{new Intl.DateTimeFormat("ru", { month: "short", timeZone: "Europe/Moscow" }).format(new Date(row.at))}</span>
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">{row.title}</span>
                <span className="caption block">{row.control_label} · {new Intl.DateTimeFormat("ru", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Moscow" }).format(new Date(row.at))}{row.room ? ` · ауд. ${row.room}` : ""}</span>
                <span className={cn("mt-1 block text-[13px]", row.level === "red" ? "text-danger" : row.level === "yellow" ? "text-[#8a5a00]" : "text-text-2")}>{row.admission}</span>
              </span>
              <ChevronRight aria-hidden className="size-5 shrink-0 text-muted" />
            </Link>
          </li>
        ))}
      </ul>
    </Card>
  );
}

export function StudyPage() {
  const study = useStudy();
  const [tab, setTab] = useState<Tab>("now");
  return (
    <div className="flex flex-col gap-4">
      <PageHeader eyebrow="Оценки, допуск и сессия" title="Учёба" />
      {study.isPending && <Skeleton className="h-40" />}
      {study.isError && <ErrorState message={study.error.message} onRetry={() => study.refetch()} />}
      {study.data && (
        <>
          <Summary data={study.data} />
          <div role="tablist" aria-label="Разделы учёбы" className="flex gap-1.5 overflow-x-auto [scrollbar-width:none]">
            {TABS.map((option) => (
              <button
                key={option.key}
                role="tab"
                aria-selected={tab === option.key}
                onClick={() => setTab(option.key)}
                className={cn("soft min-h-10 shrink-0 rounded-[10px] px-4 text-sm", tab === option.key ? "bg-primary text-on-primary" : "bg-surface text-text-2 shadow-k-card hover:bg-primary-soft")}
              >
                {option.label}
              </button>
            ))}
          </div>
          {tab === "now" && (
            study.data.disciplines.length === 0 ? (
              <EmptyState>Оценок ещё нет. Первая контрольная точка появится здесь вместе с датой.</EmptyState>
            ) : (
              <>
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                  {study.data.disciplines.map((item) => <DisciplineCard key={item.id} item={item} />)}
                </div>
                <ForecastCard forecast={study.data.forecast} />
                <RulesPanel rules={study.data.rules} />
                <p className="caption m-0 flex items-center gap-1.5"><CalendarClock aria-hidden className="size-4" /> Данные на {shortDate(study.data.today)}. Это статус для помощи, а не рейтинг.</p>
              </>
            )
          )}
          {tab === "session" && <Session data={study.data} />}
          {tab === "history" && <Dynamics data={study.data} />}
        </>
      )}
    </div>
  );
}

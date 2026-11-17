import { useMutation } from "@tanstack/react-query";
import { CheckCircle2, Clock3, FlaskConical, History, MessageCircle, XCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import { Alert, Card, CardTitle, ErrorState, PageHeader, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { dateTimeLabel } from "../requests/api";
import { shortDate, useDiscipline, type Checkpoint, type DisciplineDetail, type WhatIf } from "./api";
import { BarLegend, LEVEL_STYLE, LevelBadge, ScoreBar } from "./parts";

const STATE: Record<Checkpoint["state"], { label: string; className: string }> = {
  graded: { label: "оценено", className: "text-[#146c3a]" },
  missed: { label: "не сдано", className: "text-danger" },
  waiting: { label: "на проверке", className: "text-[#8a5a00]" },
  upcoming: { label: "впереди", className: "text-muted" },
};

function Checkpoints({ data }: { data: DisciplineDetail }) {
  return (
    <Card aria-labelledby="cp-heading">
      <CardTitle id="cp-heading" meta={<span className="caption">веса в сумме 100</span>}>Контрольные точки</CardTitle>
      <ul className="m-0 flex list-none flex-col gap-2 p-0">
        {data.checkpoints.map((cp) => (
          <li key={cp.id} className={cn("flex items-center gap-3 rounded-[var(--radius-tile)] p-3.5", cp.state === "missed" ? "bg-[#fff5f5]" : "bg-surface-2")}>
            <span aria-hidden className={cn("grid size-9 shrink-0 place-items-center rounded-full bg-surface", STATE[cp.state].className)}>
              {cp.state === "graded" ? <CheckCircle2 className="size-5" /> : cp.state === "missed" ? <XCircle className="size-5" /> : <Clock3 className="size-5" />}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block font-medium">{cp.title}{cp.critical && <span className="ml-1.5 align-middle text-[12px] font-normal text-muted">обязательная</span>}</span>
              <span className="caption block">
                {cp.due_on ? shortDate(cp.due_on) : "без даты"} · вес {cp.weight} · <span className={STATE[cp.state].className}>{STATE[cp.state].label}</span>
              </span>
            </span>
            <span className="shrink-0 text-right">
              {cp.score !== null ? (
                <>
                  <span className="block font-medium tabular-nums">{cp.score} / {cp.max_score}</span>
                  <span className="caption">+{cp.points} балла</span>
                </>
              ) : (
                <span className="caption">макс. {cp.max_score}</span>
              )}
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function WhatIfPanel({ data }: { data: DisciplineDetail }) {
  const open = useMemo(() => data.checkpoints.filter((cp) => cp.score === null && cp.state !== "missed"), [data.checkpoints]);
  const [values, setValues] = useState<Record<string, number>>(() =>
    Object.fromEntries(open.map((cp) => [cp.id, Math.round(cp.max_score * 0.7)])),
  );
  const run = useMutation({
    mutationFn: (scores: Record<string, number>) => api<WhatIf>(`/api/study/disciplines/${data.id}/what-if`, { method: "POST", body: { scores } }),
  });
  useEffect(() => {
    if (!open.length) return;
    const timer = setTimeout(() => run.mutate(values), 250);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [values]);
  if (!open.length) return null;
  const result = run.data;
  return (
    <Card aria-labelledby="whatif-heading">
      <CardTitle id="whatif-heading" meta={<FlaskConical aria-hidden className="size-5 text-primary" />}>Что если</CardTitle>
      <p className="caption m-0 mb-4">Подвигайте ползунки: сколько получится, если сдать оставшиеся работы так. Ничего не сохраняется.</p>
      <div className="flex flex-col gap-4">
        {open.map((cp) => (
          <label key={cp.id} className="flex flex-col gap-1.5">
            <span className="flex justify-between text-sm"><span>{cp.title}</span><span className="font-medium tabular-nums">{values[cp.id]} / {cp.max_score}</span></span>
            <input
              type="range"
              min={0}
              max={cp.max_score}
              step={cp.max_score > 20 ? 1 : 0.5}
              value={values[cp.id]}
              onChange={(event) => setValues({ ...values, [cp.id]: Number(event.target.value) })}
              className="w-full accent-[var(--primary)]"
            />
          </label>
        ))}
      </div>
      <div aria-live="polite" className="mt-5 rounded-[var(--radius-tile)] bg-surface-2 p-4">
        {run.isError ? (
          <Alert>{run.error.message}</Alert>
        ) : result ? (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="m-0 text-[28px] leading-none font-medium tracking-[-0.02em] tabular-nums">{result.total} <span className="text-base font-normal text-muted">из 100</span></p>
              <p className="m-0 mt-1 text-sm text-text-2">Итог: {result.mark}{result.passes ? "" : " — ниже порога допуска"}</p>
            </div>
            <LevelBadge level={result.risk.level} label={result.risk.label} />
          </div>
        ) : (
          <p className="caption m-0">Считаю…</p>
        )}
      </div>
    </Card>
  );
}

function Trend({ data }: { data: DisciplineDetail }) {
  if (data.trend.length < 2) return null;
  return (
    <Card aria-labelledby="trend-heading">
      <CardTitle id="trend-heading">Динамика</CardTitle>
      <ol className="m-0 flex list-none items-end gap-2 overflow-x-auto p-0 pb-1">
        {data.trend.map((point, index) => (
          <li key={index} className="flex min-w-16 flex-1 flex-col items-center gap-1.5">
            <span className="text-sm font-medium tabular-nums">{point.points}</span>
            <span className={cn("h-2 w-full rounded-full", LEVEL_STYLE[point.level].bar)} />
            <span className="caption">{shortDate(point.at)}</span>
          </li>
        ))}
      </ol>
    </Card>
  );
}

export function DisciplinePage() {
  const { id } = useParams();
  const discipline = useDiscipline(id);
  const back = <Link to="/study" className="text-primary hover:underline">← Учёба</Link>;
  if (discipline.isPending) return <Skeleton className="h-96" />;
  if (discipline.isError) {
    return (
      <div className="flex flex-col gap-4">
        <PageHeader eyebrow={back} title="Дисциплина" />
        <ErrorState message={discipline.error.message} onRetry={() => discipline.refetch()} />
      </div>
    );
  }
  const data = discipline.data;
  const missing = Math.max(0, data.threshold - data.risk.points);
  return (
    <div className="flex flex-col gap-4">
      <PageHeader eyebrow={back} title={data.title}>
        <div className="flex flex-wrap items-center gap-2">
          <LevelBadge level={data.risk.level} label={data.risk.label} />
          <span className="caption">{data.control_label} · {data.teacher}</span>
        </div>
      </PageHeader>

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <div className="flex flex-col gap-4">
          <Card className={LEVEL_STYLE[data.risk.level].tile}>
            <div className="flex flex-wrap items-end justify-between gap-4">
              <div>
                <p className="caption m-0">Набрано</p>
                <p className="m-0 text-[44px] leading-none font-normal tracking-[-0.03em] tabular-nums">{data.risk.points}<span className="text-lg text-muted"> / 100</span></p>
              </div>
              <dl className="m-0 grid grid-cols-3 gap-4 text-right">
                <div><dt className="caption">темп</dt><dd className="m-0 font-medium tabular-nums">{data.risk.pace === null ? "—" : `${Math.round(data.risk.pace * 100)}%`}</dd></div>
                <div><dt className="caption">максимум</dt><dd className="m-0 font-medium tabular-nums">{data.risk.reachable}</dd></div>
                <div><dt className="caption">посещ.</dt><dd className="m-0 font-medium tabular-nums">{data.attendance ? `${data.attendance.attended}/${data.attendance.total}` : "—"}</dd></div>
              </dl>
            </div>
            <ScoreBar className="mt-5" points={data.risk.points} expected={data.expected_by_today} threshold={data.threshold} level={data.risk.level} />
            <BarLegend expected={data.expected_by_today} threshold={data.threshold} />
            <div className="mt-4 flex flex-col gap-1.5 text-[15px]">
              {data.risk.reasons.length > 0 ? (
                data.risk.reasons.map((reason) => <p key={reason.code} className="m-0">• {reason.text}{reason.code.startsWith("MISSED") && data.risk.missed.length ? `: ${data.risk.missed.join(", ")}` : ""}</p>)
              ) : (
                <p className="m-0 text-text-2">{data.risk.level === "grey" ? "Сроков пока не было — светофор включится после первой контрольной." : "Всё идёт по плану."}</p>
              )}
              <p className="m-0 text-text-2">
                {missing > 0
                  ? `До допуска осталось ${missing} балл(ов)` + (data.need_for_admission !== null ? ` — это ${Math.round(data.need_for_admission * 100)}% от оставшихся работ.` : ".")
                  : "Порог допуска по баллам уже пройден."}
                {data.need_for_excellent !== null && data.need_for_excellent > 0 && ` На «отлично» нужно ${Math.round(data.need_for_excellent * 100)}% оставшегося.`}
              </p>
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              {data.actions.map((action, index) => (
                <Link
                  key={action.kind}
                  to={action.link}
                  className={cn(
                    "soft inline-flex min-h-11 items-center gap-2 rounded-[var(--radius-control)] px-4 text-[15px] font-medium",
                    index === 0 && data.risk.level !== "green" && data.risk.level !== "grey" ? "bg-primary text-on-primary hover:bg-primary-hover" : "bg-surface text-primary hover:bg-primary-soft",
                  )}
                >
                  {action.kind === "assistant" && <MessageCircle aria-hidden className="size-4" />}
                  {action.label}
                </Link>
              ))}
            </div>
          </Card>
          <Checkpoints data={data} />
        </div>
        <div className="flex flex-col gap-4">
          <WhatIfPanel data={data} />
          <Trend data={data} />
          <Card aria-labelledby="history-heading">
            <CardTitle id="history-heading" meta={<History aria-hidden className="size-5 text-muted" />}>История изменений</CardTitle>
            {data.history.length === 0 ? (
              <p className="caption m-0">Оценок ещё нет.</p>
            ) : (
              <ul className="m-0 flex list-none flex-col gap-2.5 p-0">
                {data.history.map((row, index) => (
                  <li key={index} className="text-sm">
                    <span className="font-medium">{row.checkpoint}</span>: {row.old === null ? "" : <span className="text-muted line-through">{row.old}</span>} {row.old !== null && "→ "}<span className="font-medium">{row.new ?? "удалено"}</span>
                    <span className="caption block">{row.by} · {dateTimeLabel(row.at)}{row.reason ? ` · ${row.reason}` : ""}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <p className="caption m-0">Пороги и формула — допущения концепта. <Link className="text-primary" to="/assistant?q=Как работает светофор">Спросить ассистента</Link></p>
        </div>
      </div>
    </div>
  );
}

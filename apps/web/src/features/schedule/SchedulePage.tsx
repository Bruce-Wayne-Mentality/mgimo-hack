import { useState, type FormEvent } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button, Card, EmptyState, ErrorState, Field, Input, PageHeader, Skeleton } from "@/components/ui";
import { addDays, calendarWeek, dayLabel, groupByDay, LessonCard, useSchedule } from "./lessons";

export function SchedulePage() {
  const [range, setRange] = useState(() => calendarWeek());
  const [draft, setDraft] = useState(range);
  const schedule = useSchedule(range.start, range.finish);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (draft.start && draft.finish) setRange(draft);
  };

  const selectWeek = (day?: string) => {
    const week = calendarWeek(day);
    setDraft(week);
    setRange(week);
  };

  return (
    <div className="flex flex-col gap-4">
      <PageHeader eyebrow="Личное расписание · учебная неделя Пн–Вс" title="Расписание" />
      <Card className="flex flex-col gap-4">
        <div role="group" aria-label="Выбрать учебную неделю" className="flex items-center gap-2 rounded-[var(--radius-tile)] bg-surface-2 p-1.5">
          <Button type="button" variant="onBlue" className="min-h-10 px-3 text-sm" aria-label="Предыдущая неделя" onClick={() => selectWeek(addDays(range.start, -7))}>
            <ChevronLeft className="size-4" aria-hidden />
            <span className="hidden sm:inline">Предыдущая</span>
          </Button>
          <Button type="button" variant="ghost" className="min-h-10 flex-1 px-3 text-sm font-medium" onClick={() => selectWeek()}>Эта неделя</Button>
          <Button type="button" variant="onBlue" className="min-h-10 px-3 text-sm" aria-label="Следующая неделя" onClick={() => selectWeek(addDays(range.start, 7))}>
            <span className="hidden sm:inline">Следующая</span>
            <ChevronRight className="size-4" aria-hidden />
          </Button>
        </div>
        <form onSubmit={submit} className="grid grid-cols-2 gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
          <Field id="start" label="С даты">
            <Input id="start" type="date" required value={draft.start} onChange={(e) => setDraft({ ...draft, start: e.target.value })} />
          </Field>
          <Field id="finish" label="По дату">
            <Input id="finish" type="date" required value={draft.finish} onChange={(e) => setDraft({ ...draft, finish: e.target.value })} />
          </Field>
          <Button type="submit" className="col-span-2 min-h-13 sm:col-span-1">Показать</Button>
        </form>
      </Card>
      <div aria-live="polite" className="flex flex-col gap-4">
        {schedule.isPending && <Skeleton className="h-40" />}
        {schedule.isError && <ErrorState message={schedule.error.message} onRetry={() => schedule.refetch()} />}
        {schedule.data && schedule.data.lessons.length === 0 && (
          <EmptyState>На эти даты пар нет. Можно выбрать другую неделю или период.</EmptyState>
        )}
        {schedule.data &&
          groupByDay(schedule.data.lessons).map(([day, lessons]) => (
            <Card key={day}>
              <div className="mb-4 flex items-baseline justify-between gap-3">
                <h2 className="m-0 text-lg font-medium first-letter:uppercase">{dayLabel(day)}</h2>
                <span className="caption">{lessons.length} {lessons.length === 1 ? "пара" : lessons.length < 5 ? "пары" : "пар"}</span>
              </div>
              <div className="flex flex-col gap-2.5">
                {lessons.map((lesson) => (
                  <LessonCard key={lesson.id} lesson={lesson} />
                ))}
              </div>
            </Card>
          ))}
      </div>
    </div>
  );
}

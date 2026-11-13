import { useState, type FormEvent } from "react";
import { Button, Card, EmptyState, ErrorState, Field, Input, Skeleton } from "@/components/ui";
import { addDays, dayLabel, groupByDay, LessonCard, moscowDate, useSchedule } from "./lessons";

export function SchedulePage() {
  const today = moscowDate();
  const [range, setRange] = useState({ start: today, finish: addDays(today, 7) });
  const [draft, setDraft] = useState(range);
  const schedule = useSchedule(range.start, range.finish);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (draft.start && draft.finish) setRange(draft);
  };

  return (
    <div className="flex flex-col gap-4">
      <h1 className="m-0 text-[28px] font-semibold">Расписание</h1>
      <Card>
        <form onSubmit={submit} className="grid grid-cols-2 gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
          <Field id="start" label="С даты">
            <Input id="start" type="date" required value={draft.start} onChange={(e) => setDraft({ ...draft, start: e.target.value })} />
          </Field>
          <Field id="finish" label="По дату">
            <Input id="finish" type="date" required value={draft.finish} onChange={(e) => setDraft({ ...draft, finish: e.target.value })} />
          </Field>
          <Button type="submit" className="col-span-2 sm:col-span-1">Показать</Button>
        </form>
      </Card>
      <div aria-live="polite" className="flex flex-col gap-4">
        {schedule.isPending && <Skeleton className="h-40" />}
        {schedule.isError && <ErrorState message={schedule.error.message} onRetry={() => schedule.refetch()} />}
        {schedule.data && schedule.data.lessons.length === 0 && (
          <EmptyState>На эти даты пар нет. Можно выбрать другой период.</EmptyState>
        )}
        {schedule.data &&
          groupByDay(schedule.data.lessons).map(([day, lessons]) => (
            <Card key={day}>
              <h2 className="m-0 mb-3 text-base font-semibold first-letter:uppercase">{dayLabel(day)}</h2>
              <div className="flex flex-col gap-2">
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

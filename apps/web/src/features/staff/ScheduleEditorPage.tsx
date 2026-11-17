import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Undo2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Alert, Button, Card, EmptyState, ErrorState, Field, Input, PageHeader, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { Lesson } from "@/lib/types";
import { addDays, calendarWeek, dayLabel, groupByDay, LessonCard } from "../schedule/lessons";

type Week = { group: string; start: string; finish: string; lessons: Lesson[] };
type Kind = "moved" | "cancelled" | "room";

const KIND_LABELS: Record<Kind, string> = { moved: "Перенести", cancelled: "Отменить", room: "Сменить аудиторию" };

export function ScheduleEditorPage() {
  const client = useQueryClient();
  const groups = useQuery({ queryKey: ["schedule-groups"], queryFn: async () => (await api<{ items: { code: string; course: number }[] }>("/api/staff/schedule/groups")).items });
  const [group, setGroup] = useState<string | null>(null);
  const [week, setWeek] = useState(calendarWeek());
  const current = group ?? groups.data?.[0]?.code ?? null;
  const data = useQuery({
    queryKey: ["staff-schedule", current, week.start],
    queryFn: () => api<Week>(`/api/staff/schedule?group=${encodeURIComponent(current!)}&start=${week.start}`),
    enabled: !!current,
  });
  const [edit, setEdit] = useState<{ lesson: Lesson; kind: Kind } | null>(null);
  const [form, setForm] = useState({ date: "", start: "", room: "", note: "" });
  const refresh = () => client.invalidateQueries({ queryKey: ["staff-schedule"] });
  const save = useMutation({
    mutationFn: () =>
      api("/api/staff/schedule/changes", {
        method: "POST",
        body: {
          lesson_id: edit!.lesson.id, group: current, kind: edit!.kind, note: form.note.trim() || null,
          new_date: edit!.kind === "moved" ? form.date : null, new_start: edit!.kind === "moved" ? form.start : null,
          new_room: form.room.trim() || null,
        },
      }),
    onSuccess: () => {
      setEdit(null);
      refresh();
    },
  });
  const revert = useMutation({ mutationFn: (id: string) => api(`/api/staff/schedule/changes/${id}`, { method: "DELETE" }), onSuccess: refresh });

  const open = (lesson: Lesson, kind: Kind) => {
    save.reset();
    setForm({ date: lesson.date, start: "", room: lesson.room ?? "", note: "" });
    setEdit({ lesson, kind });
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate();
  };

  return (
    <div className="flex flex-col gap-4">
      <PageHeader eyebrow="Перенос, отмена, замена аудитории → уведомление студентам группы" title="Расписание групп" />
      <div className="flex flex-wrap items-center gap-2">
        {groups.data?.map((item) => (
          <button key={item.code} aria-pressed={current === item.code} onClick={() => setGroup(item.code)}
            className={cn("soft min-h-10 rounded-[10px] px-4 text-sm", current === item.code ? "bg-primary text-on-primary" : "bg-surface text-text-2 shadow-k-card hover:bg-primary-soft")}>
            {item.code}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-1">
          <Button variant="ghost" aria-label="Предыдущая неделя" onClick={() => setWeek(calendarWeek(addDays(week.start, -7)))}><ChevronLeft aria-hidden className="size-5" /></Button>
          <span className="text-sm tabular-nums">{week.start.slice(8)}.{week.start.slice(5, 7)} – {week.finish.slice(8)}.{week.finish.slice(5, 7)}</span>
          <Button variant="ghost" aria-label="Следующая неделя" onClick={() => setWeek(calendarWeek(addDays(week.start, 7)))}><ChevronRight aria-hidden className="size-5" /></Button>
        </div>
      </div>
      {(groups.isPending || data.isPending) && <Skeleton className="h-64" />}
      {data.isError && <ErrorState message={data.error.message} onRetry={() => data.refetch()} />}
      {data.data && data.data.lessons.length === 0 && <EmptyState>На этой неделе пар нет.</EmptyState>}
      <div className="grid grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-2">
        {data.data && groupByDay(data.data.lessons).map(([day, lessons]) => (
          <Card key={day} aria-label={dayLabel(day)} className="p-4 sm:p-5">
            <h2 className="m-0 mb-3 text-[15px] font-medium first-letter:uppercase">{dayLabel(day)}</h2>
            <div className="flex flex-col gap-3">
              {lessons.map((lesson) => (
                <div key={lesson.id} className="flex flex-col gap-1.5">
                  <LessonCard lesson={lesson} />
                  <div className="flex flex-wrap gap-1">
                    {lesson.change?.change_id ? (
                      <Button variant="ghost" className="min-h-9 px-2 text-sm" loading={revert.isPending} onClick={() => revert.mutate(lesson.change!.change_id!)}>
                        <Undo2 aria-hidden className="size-4" /> Вернуть как было
                      </Button>
                    ) : (
                      (Object.keys(KIND_LABELS) as Kind[]).map((kind) => (
                        <Button key={kind} variant="ghost" className={cn("min-h-9 px-2 text-sm", kind === "cancelled" && "text-danger hover:bg-danger-soft")} onClick={() => open(lesson, kind)}>
                          {KIND_LABELS[kind]}
                        </Button>
                      ))
                    )}
                  </div>
                </div>
              ))}
            </div>
          </Card>
        ))}
      </div>
      {revert.isError && <Alert>{revert.error.message}</Alert>}
      {edit && (
        <div role="dialog" aria-modal="true" aria-labelledby="change-title" className="fixed inset-0 z-50 grid place-items-end bg-black/30 p-3 sm:place-items-center" onClick={() => setEdit(null)}>
          <form onClick={(event) => event.stopPropagation()} onSubmit={submit} className="flex w-full max-w-[440px] flex-col gap-3 rounded-[var(--radius-card)] bg-surface p-5 shadow-k-float">
            <h2 id="change-title" className="m-0 text-lg font-medium">{KIND_LABELS[edit.kind]}: {edit.lesson.title}</h2>
            <p className="caption m-0">{dayLabel(edit.lesson.date)}, ауд. {edit.lesson.room ?? "—"}</p>
            {edit.kind === "moved" && (
              <div className="grid grid-cols-2 gap-3">
                <Field id="c-date" label="Новая дата"><Input id="c-date" type="date" value={form.date} onChange={(event) => setForm({ ...form, date: event.target.value })} /></Field>
                <Field id="c-start" label="Начало"><Input id="c-start" type="time" step={600} value={form.start} onChange={(event) => setForm({ ...form, start: event.target.value })} /></Field>
              </div>
            )}
            {edit.kind !== "cancelled" && (
              <Field id="c-room" label={edit.kind === "room" ? "Новая аудитория" : "Аудитория (если меняется)"}><Input id="c-room" value={form.room} onChange={(event) => setForm({ ...form, room: event.target.value })} /></Field>
            )}
            <Field id="c-note" label="Причина для студентов"><Input id="c-note" maxLength={300} value={form.note} onChange={(event) => setForm({ ...form, note: event.target.value })} placeholder="Например: преподаватель на конференции" /></Field>
            <p className="caption m-0">Студенты группы увидят «было → стало» и получат уведомление в течение минуты.</p>
            {save.isError && <Alert>{save.error.message}</Alert>}
            <div className="flex gap-2">
              <Button type="submit" variant={edit.kind === "cancelled" ? "danger" : "primary"} loading={save.isPending}
                disabled={(edit.kind === "moved" && (!form.date || !form.start)) || (edit.kind === "room" && !form.room.trim())}>
                Сохранить
              </Button>
              <Button type="button" variant="ghost" onClick={() => setEdit(null)}>Отмена</Button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}

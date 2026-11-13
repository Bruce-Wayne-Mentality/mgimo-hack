import { useQuery } from "@tanstack/react-query";
import { MapPin, UserRound } from "lucide-react";
import { api } from "@/lib/api";
import type { Lesson, Schedule } from "@/lib/types";

const TZ = "Europe/Moscow";

export function moscowDate(value = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" }).format(value);
}

export function addDays(day: string, days: number): string {
  const date = new Date(`${day}T12:00:00+03:00`);
  date.setUTCDate(date.getUTCDate() + days);
  return moscowDate(date);
}

export function dayLabel(day: string): string {
  return new Intl.DateTimeFormat("ru", { weekday: "long", day: "numeric", month: "long", timeZone: TZ }).format(
    new Date(`${day}T12:00:00+03:00`),
  );
}

export function timeLabel(value: string): string {
  return new Intl.DateTimeFormat("ru", { hour: "2-digit", minute: "2-digit", timeZone: TZ }).format(new Date(value));
}

export function useSchedule(start: string, finish: string) {
  return useQuery({
    queryKey: ["schedule", start, finish],
    queryFn: () => api<Schedule>(`/api/me/schedule?${new URLSearchParams({ start, finish })}`),
    refetchInterval: 60_000,
  });
}

export function groupByDay(lessons: Lesson[]): [string, Lesson[]][] {
  const days = new Map<string, Lesson[]>();
  for (const lesson of lessons) days.set(lesson.date, [...(days.get(lesson.date) ?? []), lesson]);
  return [...days.entries()];
}

export function LessonCard({ lesson }: { lesson: Lesson }) {
  const place = [lesson.room ? `ауд. ${lesson.room}` : "", lesson.building ?? ""].filter(Boolean).join(" · ");
  return (
    <article className="flex gap-4 rounded-[var(--radius-control)] border border-border p-3">
      <div className="w-14 shrink-0 text-right tabular-nums">
        <div className="font-semibold">{timeLabel(lesson.starts_at)}</div>
        <div className="text-sm text-muted">{timeLabel(lesson.ends_at)}</div>
      </div>
      <div className="min-w-0 flex-1">
        <p className="m-0 text-xs font-medium tracking-wide text-primary uppercase">{lesson.kind || "Занятие"}</p>
        <h3 className="m-0 text-base font-semibold">{lesson.title}</h3>
        {lesson.teachers.length > 0 && (
          <p className="m-0 mt-1 flex items-center gap-1.5 text-sm text-muted">
            <UserRound className="size-4 shrink-0" aria-hidden />
            {lesson.teachers.join(", ")}
          </p>
        )}
        {place && (
          <p className="m-0 flex items-center gap-1.5 text-sm text-muted">
            <MapPin className="size-4 shrink-0" aria-hidden />
            {place}
          </p>
        )}
      </div>
    </article>
  );
}

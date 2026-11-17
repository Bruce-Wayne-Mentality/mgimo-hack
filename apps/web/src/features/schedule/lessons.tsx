import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, MapPin, UserRound } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { Lesson, Schedule } from "@/lib/types";

const TZ = "Europe/Moscow";

export function moscowDate(value = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(value);
  const fields = Object.fromEntries(parts.map(({ type, value }) => [type, value]));
  return `${fields.year}-${fields.month}-${fields.day}`;
}

function calendarDate(day: string): Date {
  const date = new Date(`${day}T00:00:00Z`);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day) || !Number.isFinite(date.getTime()) || date.toISOString().slice(0, 10) !== day) {
    throw new RangeError("Invalid calendar date");
  }
  return date;
}

export function addDays(day: string, days: number): string {
  const date = calendarDate(day);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

export function calendarWeek(day = moscowDate()): { start: string; finish: string } {
  const weekday = calendarDate(day).getUTCDay();
  const start = addDays(day, -((weekday + 6) % 7));
  return { start, finish: addDays(start, 6) };
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

function changeText(lesson: Lesson): string | null {
  const change = lesson.change;
  if (!change) return null;
  const when = (value: string | null) =>
    value ? new Intl.DateTimeFormat("ru", { weekday: "short", day: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Moscow" }).format(new Date(value)) : "";
  if (change.kind === "cancelled") return "Пара отменена";
  if (change.kind === "room") return `Замена аудитории: было ${change.was_room ?? "—"}`;
  const wasRoom = change.was_room && change.was_room !== lesson.room ? `, ауд. ${change.was_room}` : "";
  return `Перенесена: было ${when(change.was_starts_at)}${wasRoom}`;
}

/** Lesson tile: light inner tile on a white card, time in a blue chip. Deanery edits show «было → стало». */
export function LessonCard({ lesson }: { lesson: Lesson }) {
  const place = [lesson.room ? `ауд. ${lesson.room}` : "", lesson.building ?? ""].filter(Boolean).join(" · ");
  const cancelled = lesson.change?.kind === "cancelled";
  const note = changeText(lesson);
  return (
    <article className={cn("flex gap-4 rounded-[var(--radius-tile)] p-3.5 sm:p-4", note ? (cancelled ? "bg-[#fff5f5]" : "bg-[#fff8e8]") : "bg-surface-2")}>
      <div className={cn("flex w-[68px] shrink-0 flex-col items-center justify-center gap-0.5 rounded-[var(--radius-control)] py-2 tabular-nums", cancelled ? "bg-line-strong text-text-2 line-through" : "bg-primary text-on-primary")}>
        <span className="text-[17px] leading-none font-medium">{timeLabel(lesson.starts_at)}</span>
        <span className="text-[12px] leading-none opacity-80">{timeLabel(lesson.ends_at)}</span>
      </div>
      <div className="min-w-0 flex-1">
        {note && (
          <p className={cn("m-0 mb-1 inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[12px] font-medium", cancelled ? "bg-[#fdecec] text-[#b42318]" : "bg-[#fff0c7] text-[#7a4f00]")}>
            <AlertTriangle className="size-3.5" aria-hidden />
            {note}
          </p>
        )}
        <p className="caption m-0 mb-0.5 first-letter:uppercase">{lesson.kind || "Занятие"}</p>
        <h3 className={cn("m-0 text-base leading-snug font-medium tracking-normal", cancelled && "text-text-2 line-through")}>{lesson.title}</h3>
        <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-text-2">
          {lesson.teachers.length > 0 && (
            <span className="flex items-center gap-1.5">
              <UserRound className="size-4 shrink-0 text-muted" aria-hidden />
              {lesson.teachers.join(", ")}
            </span>
          )}
          {place && (
            <span className="flex items-center gap-1.5">
              <MapPin className="size-4 shrink-0 text-muted" aria-hidden />
              {place}
            </span>
          )}
        </div>
        {lesson.change?.note && <p className="m-0 mt-1 text-[13px] text-text-2">{lesson.change.note}</p>}
      </div>
    </article>
  );
}

import { useQuery } from "@tanstack/react-query";
import { BellRing, CalendarDays, CheckCircle2, ClipboardList, type LucideIcon } from "lucide-react";
import { Link } from "react-router";
import { Card, CardTitle, EmptyState, ErrorState, IconChip, MoreLink, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { useSession } from "@/lib/auth";
import type { NotificationPage } from "@/lib/types";
import { OPEN, useMyRequests } from "../requests/api";
import { dayLabel, LessonCard, moscowDate, timeLabel, useSchedule } from "../schedule/lessons";

function plural(count: number, one: string, few: string, many: string): string {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}

/** Small status tile: grey caption on top, value with a status mark below (like "Состояние дома · Отлично ✓"). */
function StatusTile({ label, value, icon: Icon, to, tone = "ok" }: { label: string; value: string; icon: LucideIcon; to: string; tone?: "ok" | "warn" | "idle" }) {
  return (
    <Link to={to} className="soft flex items-center gap-3 rounded-[var(--radius-card)] bg-surface p-4 shadow-k-card hover:bg-surface-2">
      <IconChip>
        <Icon className="size-5" strokeWidth={1.75} aria-hidden />
      </IconChip>
      <span className="min-w-0 flex-1">
        <span className="caption block">{label}</span>
        <span className="flex items-center gap-1.5 text-[15px] font-medium">
          {value}
          {tone === "ok" && <CheckCircle2 aria-hidden className="size-4 text-ok" />}
          {tone === "warn" && <span aria-hidden className="size-2 rounded-full bg-warn" />}
        </span>
      </span>
    </Link>
  );
}

function useLatest() {
  return useQuery({
    queryKey: ["notifications", "latest"],
    queryFn: () => api<NotificationPage>("/api/me/notifications?limit=3"),
    refetchInterval: 30_000,
  });
}

function StudentHome() {
  const today = moscowDate();
  const schedule = useSchedule(today, today);
  const latest = useLatest();
  const lessons = schedule.data?.lessons ?? [];
  const now = Date.now();
  const next = lessons.find((lesson) => new Date(lesson.ends_at).getTime() > now);
  const unread = latest.data?.unread_count ?? 0;
  const requests = useMyRequests();
  const active = (requests.data ?? []).filter((item) => OPEN.includes(item.status));
  const waiting = active.filter((item) => item.status === "needs_info").length;

  return (
    <>
      <div className="grid gap-3 sm:grid-cols-3">
        <StatusTile
          to="/schedule"
          icon={CalendarDays}
          label="Пары сегодня"
          value={schedule.isPending ? "…" : lessons.length ? `${lessons.length} ${plural(lessons.length, "пара", "пары", "пар")}` : "Свободный день"}
        />
        <StatusTile
          to="/notifications"
          icon={BellRing}
          label="Уведомления"
          tone={unread ? "warn" : "ok"}
          value={latest.isPending ? "…" : unread ? `${unread} ${plural(unread, "новое", "новых", "новых")}` : "Всё прочитано"}
        />
        <StatusTile
          to="/requests"
          icon={ClipboardList}
          label="Заявки"
          tone={waiting ? "warn" : "ok"}
          value={requests.isPending ? "…" : waiting ? `Нужен ответ: ${waiting}` : active.length ? `${active.length} в работе` : "Нет активных"}
        />
      </div>

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <Card aria-labelledby="today-heading">
          <CardTitle id="today-heading" meta={<MoreLink to="/schedule">Неделя</MoreLink>}>
            Сегодня
          </CardTitle>
          {next && (
            <div className="mb-4 flex items-end justify-between gap-4 rounded-[var(--radius-tile)] bg-primary p-5 text-on-primary">
              <div className="min-w-0">
                <p className="m-0 text-[13px] opacity-80">Следующая пара</p>
                <p className="m-0 mt-1 truncate text-lg font-medium">{next.title}</p>
                <p className="m-0 text-[13px] opacity-80">{next.room ? `ауд. ${next.room}` : next.kind}</p>
              </div>
              <div className="shrink-0 text-right">
                <p className="m-0 text-[32px] leading-none font-medium tracking-[-0.02em] tabular-nums">{timeLabel(next.starts_at)}</p>
                <p className="m-0 mt-1 text-[13px] opacity-80">начало</p>
              </div>
            </div>
          )}
          <p className="caption mt-0 mb-3 first-letter:uppercase">{dayLabel(today)}</p>
          <div aria-live="polite" className="flex flex-col gap-2.5">
            {schedule.isPending && <Skeleton className="h-20" />}
            {schedule.isError && <ErrorState message={schedule.error.message} onRetry={() => schedule.refetch()} />}
            {schedule.data?.lessons.length === 0 && <EmptyState>Сегодня пар нет.</EmptyState>}
            {lessons.map((lesson) => <LessonCard key={lesson.id} lesson={lesson} />)}
          </div>
        </Card>

        <Card aria-labelledby="latest-heading">
          <CardTitle id="latest-heading" meta={<MoreLink to="/notifications">Все</MoreLink>}>
            Уведомления
          </CardTitle>
          <div className="flex flex-col gap-2.5">
            {latest.isPending && <Skeleton className="h-16" />}
            {latest.isError && <ErrorState message={latest.error.message} onRetry={() => latest.refetch()} />}
            {latest.data?.items.length === 0 && <EmptyState>Новых уведомлений нет.</EmptyState>}
            {latest.data?.items.map((item) => (
              <div key={item.id} className="flex gap-3 rounded-[var(--radius-tile)] bg-surface-2 p-3.5">
                <span aria-hidden className={`mt-1.5 size-2 shrink-0 rounded-full ${item.read_at ? "bg-line-strong" : "bg-primary"}`} />
                <div className="min-w-0">
                  <p className="m-0 text-[15px] font-medium">{item.title}</p>
                  <p className="m-0 text-sm text-text-2">{item.body}</p>
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </>
  );
}

export function HomePage() {
  const { data } = useSession();
  const user = data!.user;
  const firstName = user.display_name.split(/\s+/)[0] ?? user.display_name;
  return (
    <div className="flex flex-col gap-4">
      <header className="mb-1">
        <h1 className="m-0 text-[30px] font-normal tracking-[-0.03em] sm:text-[40px]">{firstName}, привет!</h1>
        <p className="caption m-0 mt-1">Добро пожаловать в личный кабинет · {user.role_label.toLowerCase()}</p>
      </header>
      {user.role === "student" ? (
        <StudentHome />
      ) : (
        <Card>
          <CardTitle meta={<MoreLink to="/staff/requests">Очередь</MoreLink>}>Кабинет сотрудника</CardTitle>
          <p className="m-0 text-text-2">Заявки студентов вашего факультета — в очереди, по сроку. Панель факультета и объявления появятся в следующих модулях.</p>
        </Card>
      )}
    </div>
  );
}

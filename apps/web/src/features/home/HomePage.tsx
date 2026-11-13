import { useQuery } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import { Link } from "react-router";
import { Card, EmptyState, ErrorState, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { useSession } from "@/lib/auth";
import type { NotificationPage } from "@/lib/types";
import { dayLabel, LessonCard, moscowDate, useSchedule } from "../schedule/lessons";

function greeting(): string {
  const hour = Number(new Intl.DateTimeFormat("ru", { hour: "numeric", hourCycle: "h23", timeZone: "Europe/Moscow" }).format(new Date()));
  if (hour < 6) return "Доброй ночи";
  if (hour < 12) return "Доброе утро";
  if (hour < 18) return "Добрый день";
  return "Добрый вечер";
}

function Today() {
  const today = moscowDate();
  const schedule = useSchedule(today, today);
  return (
    <Card aria-labelledby="today-heading">
      <div className="mb-3 flex items-center justify-between">
        <h2 id="today-heading" className="m-0 text-xl font-semibold">Сегодня</h2>
        <Link to="/schedule" className="flex min-h-11 items-center gap-1 text-sm font-medium text-primary">
          Вся неделя <ChevronRight className="size-4" aria-hidden />
        </Link>
      </div>
      <p className="mt-0 mb-3 text-sm text-muted first-letter:uppercase">{dayLabel(today)}</p>
      <div aria-live="polite" className="flex flex-col gap-2">
        {schedule.isPending && <Skeleton className="h-20" />}
        {schedule.isError && <ErrorState message={schedule.error.message} onRetry={() => schedule.refetch()} />}
        {schedule.data?.lessons.length === 0 && <EmptyState>Сегодня пар нет.</EmptyState>}
        {schedule.data?.lessons.map((lesson) => <LessonCard key={lesson.id} lesson={lesson} />)}
      </div>
    </Card>
  );
}

function Latest() {
  const latest = useQuery({
    queryKey: ["notifications", "latest"],
    queryFn: () => api<NotificationPage>("/api/me/notifications?limit=3"),
    refetchInterval: 30_000,
  });
  return (
    <Card aria-labelledby="latest-heading">
      <div className="mb-3 flex items-center justify-between">
        <h2 id="latest-heading" className="m-0 text-xl font-semibold">Уведомления</h2>
        <Link to="/notifications" className="flex min-h-11 items-center gap-1 text-sm font-medium text-primary">
          Все <ChevronRight className="size-4" aria-hidden />
        </Link>
      </div>
      <div className="flex flex-col gap-2">
        {latest.isPending && <Skeleton className="h-16" />}
        {latest.isError && <ErrorState message={latest.error.message} onRetry={() => latest.refetch()} />}
        {latest.data?.items.length === 0 && <EmptyState>Новых уведомлений нет.</EmptyState>}
        {latest.data?.items.map((item) => (
          <div key={item.id} className="rounded-[var(--radius-control)] bg-surface-2 p-3">
            <p className="m-0 text-[15px] font-medium">{item.title}</p>
            <p className="m-0 text-sm text-muted">{item.body}</p>
          </div>
        ))}
      </div>
    </Card>
  );
}

export function HomePage() {
  const { data } = useSession();
  const user = data!.user;
  const firstName = user.display_name.split(/\s+/)[0] ?? user.display_name;
  return (
    <div className="flex flex-col gap-4">
      <div>
        <p className="m-0 text-sm text-muted">{user.role_label}</p>
        <h1 className="m-0 text-[28px] leading-tight font-semibold">
          {greeting()}, {firstName}
        </h1>
      </div>
      {user.role === "student" ? (
        <>
          <Today />
          <Latest />
        </>
      ) : (
        <Card>
          <h2 className="m-0 mb-1 text-xl font-semibold">Кабинет сотрудника</h2>
          <p className="m-0 text-muted">Очередь заявок и панель факультета появятся в следующих модулях. Профиль доступен в меню.</p>
        </Card>
      )}
    </div>
  );
}

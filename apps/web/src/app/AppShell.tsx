import { useQuery } from "@tanstack/react-query";
import { Bell, CalendarDays, ClipboardList, GraduationCap, House, Menu, type LucideIcon } from "lucide-react";
import { Link, NavLink, Outlet } from "react-router";
import { BrandMark, ConceptNotice } from "@/components/Brand";
import { api } from "@/lib/api";
import { useSession } from "@/lib/auth";
import { cn } from "@/lib/cn";
import type { NotificationPage } from "@/lib/types";

type Item = { to: string; label: string; icon: LucideIcon; studentOnly?: boolean };

// Section 6: Главная · Расписание · Учёба · Заявки · Ещё.
const NAV: Item[] = [
  { to: "/", label: "Главная", icon: House },
  { to: "/schedule", label: "Расписание", icon: CalendarDays, studentOnly: true },
  { to: "/study", label: "Учёба", icon: GraduationCap, studentOnly: true },
  { to: "/requests", label: "Заявки", icon: ClipboardList, studentOnly: true },
  { to: "/more", label: "Ещё", icon: Menu },
];

function initials(name: string): string {
  const parts = name.split(/\s+/).filter(Boolean);
  const first = parts[0]?.[0] ?? "";
  const last = parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? "") : "";
  return (first + last).toUpperCase() || "?";
}

export function useUnreadCount(enabled: boolean) {
  return useQuery({
    queryKey: ["notifications", "unread"],
    queryFn: async () => (await api<NotificationPage>("/api/me/notifications?limit=1")).unread_count,
    enabled,
    refetchInterval: 30_000,
  });
}

export function AppShell() {
  const { data } = useSession();
  const user = data!.user;
  const isStudent = user.role === "student";
  const unread = useUnreadCount(isStudent);
  const items = NAV.filter((item) => isStudent || !item.studentOnly);

  return (
    <div className="flex min-h-dvh flex-col md:flex-row">
      <aside className="hidden w-60 shrink-0 flex-col gap-1 border-r border-border bg-surface p-4 md:flex">
        <Link to="/" className="mb-5 flex items-center gap-2.5 rounded-[var(--radius-control)] p-1">
          <BrandMark />
          <span className="leading-tight">
            <span className="block font-semibold">Цифровой деканат</span>
            <span className="block text-xs text-muted">концепт</span>
          </span>
        </Link>
        <nav aria-label="Основное меню" className="flex flex-col gap-1">
          {items.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                cn(
                  "flex min-h-11 items-center gap-3 rounded-[var(--radius-control)] px-3 text-[15px] font-medium",
                  isActive ? "bg-primary-soft text-primary" : "text-muted hover:bg-surface-2 hover:text-text",
                )
              }
            >
              <item.icon className="size-5" aria-hidden />
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <ConceptNotice />
        <header className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-border bg-surface/95 px-4 py-2.5 backdrop-blur">
          <Link to="/" className="flex items-center gap-2 md:hidden" aria-label="Цифровой деканат, главная">
            <BrandMark className="size-9" />
          </Link>
          <p className="m-0 hidden truncate text-sm text-muted md:block">{user.role_label}</p>
          <div className="flex items-center gap-1">
            {isStudent && (
              <Link
                to="/notifications"
                className="relative grid size-11 place-items-center rounded-full text-text hover:bg-surface-2"
                aria-label={unread.data ? `Уведомления, непрочитанных: ${unread.data}` : "Уведомления"}
              >
                <Bell className="size-6" aria-hidden />
                {!!unread.data && (
                  <span className="absolute top-1.5 right-1.5 grid h-5 min-w-5 place-items-center rounded-full bg-danger px-1 text-[11px] font-semibold text-white">
                    {unread.data > 99 ? "99+" : unread.data}
                  </span>
                )}
              </Link>
            )}
            <Link
              to="/profile"
              className="grid size-11 place-items-center rounded-full"
              aria-label={`Профиль: ${user.display_name}`}
            >
              <span className="grid size-9 place-items-center rounded-full bg-primary text-sm font-semibold text-on-primary">
                {initials(user.display_name)}
              </span>
            </Link>
          </div>
        </header>

        <main className="mx-auto w-full max-w-4xl flex-1 px-4 pt-5 pb-28 md:pb-10">
          <Outlet />
        </main>
        <footer className="hidden px-4 pb-6 md:block">
          <ConceptNotice variant="footer" />
        </footer>
      </div>

      <nav
        aria-label="Основное меню"
        className="fixed inset-x-0 bottom-0 z-20 flex border-t border-border bg-surface pb-[env(safe-area-inset-bottom)] md:hidden"
      >
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/"}
            className={({ isActive }) =>
              cn(
                "flex min-h-14 flex-1 flex-col items-center justify-center gap-0.5 text-[11px] font-medium",
                isActive ? "text-primary" : "text-muted",
              )
            }
          >
            <item.icon className="size-6" aria-hidden />
            {item.label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}

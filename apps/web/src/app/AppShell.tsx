import { useQuery } from "@tanstack/react-query";
import { Bell, CalendarDays, ClipboardList, GraduationCap, House, LayoutGrid, type LucideIcon } from "lucide-react";
import { Link, NavLink, Outlet } from "react-router";
import { BrandMark, ConceptNotice } from "@/components/Brand";
import { api } from "@/lib/api";
import { useSession } from "@/lib/auth";
import { cn } from "@/lib/cn";
import type { NotificationPage } from "@/lib/types";

type Item = { to: string; label: string; icon: LucideIcon; studentOnly?: boolean; desktopOnly?: boolean };

// Section 6: Главная · Расписание · Учёба · Заявки · Ещё (+ уведомления в сайдбаре на десктопе).
const NAV: Item[] = [
  { to: "/", label: "Главная", icon: House },
  { to: "/schedule", label: "Расписание", icon: CalendarDays, studentOnly: true },
  { to: "/study", label: "Учёба", icon: GraduationCap, studentOnly: true },
  { to: "/requests", label: "Заявки", icon: ClipboardList, studentOnly: true },
  { to: "/notifications", label: "Уведомления", icon: Bell, studentOnly: true, desktopOnly: true },
  { to: "/more", label: "Ещё", icon: LayoutGrid },
];

export function initials(name: string): string {
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

function Dot({ show, className }: { show: boolean; className?: string }) {
  if (!show) return null;
  return <span aria-hidden className={cn("absolute size-2 rounded-full bg-danger ring-2 ring-surface", className)} />;
}

export function Avatar({ name, className }: { name: string; className?: string }) {
  return (
    <span
      className={cn(
        "grid size-10 place-items-center rounded-full bg-primary text-[13px] font-medium text-on-primary",
        className,
      )}
    >
      {initials(name)}
    </span>
  );
}

/* Desktop rail: a floating white card — logo · items (icon over caption) · profile. */
function Sidebar({ items, unread, name }: { items: Item[]; unread: number; name: string }) {
  return (
    <aside className="fixed top-3 bottom-3 left-3 z-30 hidden w-[104px] flex-col rounded-[var(--radius-card)] bg-surface shadow-k-card md:flex">
      <Link to="/" className="flex shrink-0 justify-center pt-5 pb-4" aria-label="Цифровой деканат, главная">
        <BrandMark className="size-11" />
      </Link>

      <nav aria-label="Основное меню" className="flex flex-1 flex-col justify-center gap-1 overflow-y-auto px-2.5 [scrollbar-width:none]">
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/"}
            aria-label={item.to === "/notifications" && unread ? `${item.label}, непрочитанных: ${unread}` : undefined}
            className={({ isActive }) =>
              cn(
                "soft flex flex-col items-center gap-1 rounded-[var(--radius-tile)] px-1 py-2.5 text-center text-[12px] leading-tight",
                isActive ? "bg-primary-soft font-medium text-primary" : "text-muted hover:bg-surface-2 hover:text-text",
              )
            }
          >
            <span className="relative">
              <item.icon aria-hidden strokeWidth={1.75} className="size-[22px]" />
              {item.to === "/notifications" && <Dot show={!!unread} className="-top-0.5 -right-0.5" />}
            </span>
            {item.label}
          </NavLink>
        ))}
      </nav>

      <NavLink
        to="/profile"
        aria-label={`Профиль: ${name}`}
        className={({ isActive }) =>
          cn(
            "soft mx-2.5 mt-2 mb-3 flex flex-col items-center gap-1.5 rounded-[var(--radius-tile)] py-2.5 text-[12px]",
            isActive ? "bg-primary-soft font-medium text-primary" : "text-muted hover:bg-surface-2 hover:text-text",
          )
        }
      >
        <Avatar name={name} className="size-9 text-[12px]" />
        Профиль
      </NavLink>
    </aside>
  );
}

/* Mobile tab bar: floating rounded white bar, icon over caption, active item in brand blue. */
function TabBar({ items }: { items: Item[] }) {
  return (
    <nav aria-label="Основное меню" className="fixed inset-x-3 bottom-[calc(10px+env(safe-area-inset-bottom))] z-30 md:hidden">
      <ul className="m-0 flex h-[68px] list-none items-stretch rounded-[22px] bg-surface p-1.5 shadow-k-float">
        {items.map((item) => (
          <li key={item.to} className="flex flex-1">
            <NavLink
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                cn(
                  "soft flex flex-1 flex-col items-center justify-center gap-1 rounded-[16px] text-[11px] leading-none",
                  isActive ? "font-medium text-primary" : "text-muted",
                )
              }
            >
              {({ isActive }) => (
                <>
                  <item.icon aria-hidden strokeWidth={isActive ? 2 : 1.6} className="size-[23px]" />
                  {item.label}
                </>
              )}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}

export function AppShell() {
  const { data } = useSession();
  const user = data!.user;
  const isStudent = user.role === "student";
  const unread = useUnreadCount(isStudent);
  const items = NAV.filter((item) => isStudent || !item.studentOnly);

  return (
    <div className="min-h-dvh md:pl-[116px]">
      <Sidebar items={items} unread={unread.data ?? 0} name={user.display_name} />

      <div className="flex min-h-dvh min-w-0 flex-col">
        <ConceptNotice />
        <header className="sticky top-0 z-20 flex h-16 items-center justify-between gap-3 bg-bg/80 px-4 backdrop-blur-[var(--k-blur)] md:hidden">
          <Link to="/" className="flex items-center gap-2.5" aria-label="Цифровой деканат, главная">
            <BrandMark className="size-9" />
            <span className="text-[16px] font-medium tracking-[-0.01em]">Цифровой деканат</span>
          </Link>
          <div className="flex items-center gap-2">
            {isStudent && (
              <Link
                to="/notifications"
                className="soft relative grid size-10 place-items-center rounded-full bg-surface text-text shadow-k-card"
                aria-label={unread.data ? `Уведомления, непрочитанных: ${unread.data}` : "Уведомления"}
              >
                <Bell className="size-5" strokeWidth={1.75} aria-hidden />
                <Dot show={!!unread.data} className="top-2 right-2.5" />
              </Link>
            )}
            <Link to="/profile" aria-label={`Профиль: ${user.display_name}`}>
              <Avatar name={user.display_name} />
            </Link>
          </div>
        </header>

        <main className="mx-auto w-full max-w-[1200px] flex-1 px-4 pt-5 pb-[calc(100px+env(safe-area-inset-bottom))] sm:px-6 md:px-8 md:pt-8 md:pb-10">
          <Outlet />
        </main>
        <footer className="hidden px-8 pb-6 md:block">
          <ConceptNotice variant="footer" />
        </footer>
      </div>

      <TabBar items={items.filter((item) => !item.desktopOnly)} />
    </div>
  );
}

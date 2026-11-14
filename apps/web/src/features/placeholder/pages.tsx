import { Bell, ChevronRight, UserRound } from "lucide-react";
import { Link } from "react-router";
import { Card, IconChip, PageHeader } from "@/components/ui";
import { useSession } from "@/lib/auth";

export function ComingSoon({ title, text }: { title: string; text: string }) {
  return (
    <div className="flex flex-col gap-4">
      <PageHeader eyebrow="Скоро" title={title} />
      <Card>
        <p className="m-0 text-text-2">{text}</p>
      </Card>
    </div>
  );
}

export function MorePage() {
  const isStudent = useSession().data?.user.role === "student";
  const links = [
    { to: "/profile", label: "Профиль и безопасность", icon: UserRound },
    ...(isStudent ? [{ to: "/notifications", label: "Уведомления и каналы", icon: Bell }] : []),
  ];
  return (
    <div className="flex flex-col gap-4">
      <PageHeader eyebrow="Сервисы и настройки" title="Ещё" />
      <Card className="p-2 sm:p-2">
        <ul className="m-0 flex list-none flex-col gap-1 p-0">
          {links.map((link) => (
            <li key={link.to}>
              <Link to={link.to} className="nudge soft flex min-h-16 items-center gap-3 rounded-[var(--radius-tile)] px-3 font-medium hover:bg-surface-2">
                <IconChip>
                  <link.icon className="size-5" strokeWidth={1.75} aria-hidden />
                </IconChip>
                <span className="flex-1">{link.label}</span>
                <ChevronRight className="size-5 text-muted" aria-hidden />
              </Link>
            </li>
          ))}
        </ul>
      </Card>
      <p className="caption m-0">Цифровой студенческий, бронирование и другие сервисы появятся здесь позже.</p>
    </div>
  );
}

export function NotFoundPage() {
  return (
    <ComingSoon title="Страница не найдена" text="Такой страницы нет. Вернитесь на главную через меню." />
  );
}

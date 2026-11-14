import { Bell, ChevronRight, UserRound } from "lucide-react";
import { Link } from "react-router";
import { Card } from "@/components/ui";
import { useSession } from "@/lib/auth";

export function ComingSoon({ title, text }: { title: string; text: string }) {
  return (
    <div className="flex flex-col gap-4">
      <h1 className="m-0 text-[28px] font-semibold">{title}</h1>
      <Card>
        <p className="m-0 text-muted">{text}</p>
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
      <h1 className="m-0 text-[28px] font-semibold">Ещё</h1>
      <Card className="p-2">
        <ul className="m-0 list-none p-0">
          {links.map((link) => (
            <li key={link.to}>
              <Link to={link.to} className="flex min-h-12 items-center gap-3 rounded-[var(--radius-control)] px-3 hover:bg-surface-2">
                <link.icon className="size-5 text-primary" aria-hidden />
                <span className="flex-1">{link.label}</span>
                <ChevronRight className="size-5 text-muted" aria-hidden />
              </Link>
            </li>
          ))}
        </ul>
      </Card>
      <p className="m-0 text-sm text-muted">Цифровой студенческий, бронирование и другие сервисы появятся здесь позже.</p>
    </div>
  );
}

export function NotFoundPage() {
  return (
    <ComingSoon title="Страница не найдена" text="Такой страницы нет. Вернитесь на главную через меню." />
  );
}

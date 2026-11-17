import {
  AlertOctagon,
  Bell,
  BookOpenCheck,
  Bot,
  CalendarRange,
  ChevronRight,
  ClipboardList,
  IdCard,
  Info,
  LifeBuoy,
  Megaphone,
  ScanLine,
  ScrollText,
  UserRound,
  type LucideIcon,
} from "lucide-react";
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

type Entry = { to: string; label: string; hint: string; icon: LucideIcon; tone?: string };

function Group({ title, links }: { title: string; links: Entry[] }) {
  return (
    <section aria-label={title} className="flex flex-col gap-2">
      <h2 className="caption m-0 px-1 uppercase tracking-wide">{title}</h2>
      <Card className="p-2 sm:p-2">
        <ul className="m-0 flex list-none flex-col gap-1 p-0">
          {links.map((link) => (
            <li key={link.to}>
              <Link to={link.to} className="nudge soft flex min-h-16 items-center gap-3 rounded-[var(--radius-tile)] px-3 hover:bg-surface-2">
                <IconChip className={link.tone}>
                  <link.icon className="size-5" strokeWidth={1.75} aria-hidden />
                </IconChip>
                <span className="min-w-0 flex-1">
                  <span className="block font-medium">{link.label}</span>
                  <span className="caption block truncate">{link.hint}</span>
                </span>
                <ChevronRight className="size-5 text-muted" aria-hidden />
              </Link>
            </li>
          ))}
        </ul>
      </Card>
    </section>
  );
}

export function MorePage() {
  const role = useSession().data?.user.role;
  const student: Entry[] = [
    { to: "/assistant", label: "Ассистент", hint: "Вопросы о правилах, оценках и заявках", icon: Bot },
    { to: "/student-id", label: "Студенческий билет", hint: "QR-код для входа в корпус", icon: IdCard },
    { to: "/calendar", label: "Календарь", hint: "Пары, дедлайны, сессия и подписка .ics", icon: CalendarRange },
    { to: "/situations", label: "Жизненные ситуации", hint: "Академ, перевод, несданный экзамен", icon: LifeBuoy },
    { to: "/complaints", label: "Красная кнопка", hint: "Жалоба на несправедливость", icon: AlertOctagon, tone: "bg-[#fdecec] text-[#b42318]" },
  ];
  const staff: Entry[] = [
    { to: "/staff/requests", label: "Очередь заявок", hint: "По сроку, с подсветкой просрочки", icon: ClipboardList },
    { to: "/staff/grades", label: "Журнал оценок", hint: "Баллы и светофор групп", icon: BookOpenCheck },
    { to: "/staff/announcements", label: "Объявления", hint: "Группе, курсу или факультету", icon: Megaphone },
    { to: "/staff/check", label: "Проверить QR", hint: "Студенческий билет или справка", icon: ScanLine },
  ];
  const admin: Entry[] = [
    { to: "/admin/complaints", label: "Красная кнопка", hint: "Обращения студентов", icon: AlertOctagon, tone: "bg-[#fdecec] text-[#b42318]" },
    { to: "/admin/audit", label: "Журнал действий", hint: "Входы, оценки, документы", icon: ScrollText },
  ];
  const settings: Entry[] = [
    { to: "/profile", label: "Профиль и безопасность", hint: "Данные, пароль, сеансы", icon: UserRound },
    ...(role === "student" ? [{ to: "/notifications", label: "Уведомления и каналы", hint: "Лента, объявления, push и Telegram", icon: Bell }] : []),
    { to: "/about", label: "О проекте", hint: "Концепт, безопасность, лицензии", icon: Info },
  ];
  return (
    <div className="flex flex-col gap-5">
      <PageHeader eyebrow="Сервисы и настройки" title="Ещё" />
      {role === "student" && <Group title="Сервисы" links={student} />}
      {role !== "student" && <Group title="Деканат" links={staff} />}
      {role === "admin" && <Group title="Администратор" links={admin} />}
      <Group title="Настройки" links={settings} />
    </div>
  );
}

export function NotFoundPage() {
  return <ComingSoon title="Страница не найдена" text="Такой страницы нет. Вернитесь на главную через меню." />;
}

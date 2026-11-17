import { useMutation } from "@tanstack/react-query";
import { RotateCcw } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { Alert, Button, Card, CardTitle } from "@/components/ui";
import { api } from "@/lib/api";
import { useSession } from "@/lib/auth";
import { PublicFrame } from "../documents/VerifyPage";

const FEATURES = [
  ["Как у меня дела", "Светофор по каждой дисциплине с причиной и следующим шагом, «Что если» и прозрачные правила расчёта."],
  ["Деканат пишет первым", "Подсказки о рисках, дедлайнах и ожидающих ответа заявках — до того, как студент заметит проблему."],
  ["Справка за минуту", "Трекер заявок «как посылка», автовыдача справок и PDF с QR-кодом и публичной проверкой подлинности."],
  ["Цифровой студенческий", "QR-код обновляется каждые 60 секунд — скриншот не сработает."],
  ["Ассистент", "Отвечает по базе правил и данным студента, готовит заявки и передаёт сложные вопросы сотруднику."],
  ["Красная кнопка", "Жалоба на несправедливость с обязательным ответом в срок; можно анонимно."],
  ["Умный календарь", "Пары, дедлайны и сессия в одной ленте и подписка в календарь телефона."],
  ["Жизненные ситуации", "Академ, перевод, несданный экзамен — пошагово до готовой заявки."],
  ["Кабинет сотрудника", "Очередь по SLA, журнал оценок с пересчётом светофора, объявления, панель факультета."],
];

const LICENSES = [
  ["React, React Router, TanStack Query, Vite, Tailwind CSS", "MIT"],
  ["lucide-react (иконки)", "ISC"],
  ["Шрифт Onest", "SIL OFL 1.1"],
  ["FastAPI, SQLAlchemy, Alembic, Pydantic, Uvicorn", "MIT"],
  ["argon2-cffi, segno, httpx", "MIT / BSD-3-Clause"],
  ["ReportLab (PDF)", "BSD"],
  ["PostgreSQL", "PostgreSQL License"],
];

export function AboutPage() {
  const session = useSession();
  const isAdmin = session.data?.user.role === "admin";
  const [confirm, setConfirm] = useState(false);
  const reset = useMutation({ mutationFn: () => api<{ ok: boolean }>("/api/admin/demo-reset", { method: "POST" }) });

  return (
    <PublicFrame title="О проекте">
      <Card className="bg-primary text-on-primary">
        <p className="m-0 text-[13px] opacity-80">Концепт для конкурса</p>
        <p className="m-0 mt-1 text-[22px] leading-snug tracking-[-0.01em]">«Цифровой деканат» — личный кабинет студента, в котором деканат пишет первым, а не ждёт студента в очереди.</p>
      </Card>
      <Alert tone="info">
        Это не официальный сервис какого-либо вуза. Вуз, люди, оценки, документы и правила — вымышлены. Логотип — собственный знак проекта. Демо-подпись документов не является УКЭП и не имеет юридической силы.
      </Alert>
      <Card>
        <CardTitle>Что внутри</CardTitle>
        <ul className="m-0 flex list-none flex-col gap-3 p-0">
          {FEATURES.map(([title, text]) => (
            <li key={title}><span className="font-medium">{title}.</span> <span className="text-text-2">{text}</span></li>
          ))}
        </ul>
      </Card>
      <Card>
        <CardTitle>Безопасность простыми словами</CardTitle>
        <ul className="m-0 flex list-none flex-col gap-2 p-0 text-[15px] text-text-2">
          <li>Пароли хранятся только как хэш argon2id; после 5 неудачных попыток вход временно блокируется.</li>
          <li>Сессия — в защищённой куке, недоступной скриптам; каждое изменение подтверждается CSRF-токеном.</li>
          <li>Студент видит только свои данные: чужая заявка, оценка или документ выглядят как «не найдено». Это проверяют автотесты.</li>
          <li>Публичные ссылки (проверка справки, студенческий, календарь) подписаны или хранятся только в виде отпечатка.</li>
          <li>Для анонимных обращений автор и IP-адрес не сохраняются.</li>
        </ul>
      </Card>
      <Card>
        <CardTitle>Лицензии</CardTitle>
        <ul className="m-0 flex list-none flex-col gap-1.5 p-0 text-sm">
          {LICENSES.map(([name, license]) => (
            <li key={name} className="flex justify-between gap-3 border-b border-line py-1.5 last:border-0"><span>{name}</span><span className="shrink-0 text-muted">{license}</span></li>
          ))}
        </ul>
        <p className="caption m-0 mt-2">Полный список — в файле LICENSES.md репозитория.</p>
      </Card>
      {isAdmin && (
        <Card>
          <CardTitle meta={<RotateCcw aria-hidden className="size-5 text-muted" />}>Сброс демо-данных</CardTitle>
          <p className="m-0 text-sm text-text-2">Вернёт заявки, оценки, обращения и уведомления в исходное состояние. Все пользователи выйдут из кабинета.</p>
          {reset.isSuccess ? (
            <Alert tone="info" className="mt-3">Данные сброшены. <a href="/login" className="underline">Войти заново</a></Alert>
          ) : confirm ? (
            <div className="mt-3 flex gap-2">
              <Button variant="danger" loading={reset.isPending} onClick={() => reset.mutate()}>Да, сбросить</Button>
              <Button variant="ghost" onClick={() => setConfirm(false)}>Отмена</Button>
            </div>
          ) : (
            <Button variant="secondary" className="mt-3" onClick={() => setConfirm(true)}>Сбросить демо</Button>
          )}
          {reset.isError && <Alert className="mt-3">{reset.error.message}</Alert>}
        </Card>
      )}
      <Link to="/" className="soft inline-flex min-h-12 items-center justify-center rounded-[var(--radius-control)] bg-primary px-5 font-medium text-on-primary">{session.data ? "В кабинет" : "Войти"}</Link>
    </PublicFrame>
  );
}

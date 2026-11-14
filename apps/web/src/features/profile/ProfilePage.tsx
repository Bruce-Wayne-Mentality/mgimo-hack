import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery } from "@tanstack/react-query";
import { LogOut, MonitorSmartphone } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Alert, Button, Card, CardTitle, ErrorState, Field, Input, PageHeader, Skeleton } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { useLogout } from "@/lib/auth";
import { initials } from "@/app/AppShell";
import type { Profile } from "@/lib/types";

const passwordSchema = z
  .object({
    current_password: z.string().min(1, "Введите текущий пароль."),
    new_password: z.string().min(10, "Минимум 10 символов.").max(256, "Слишком длинный пароль."),
    confirm: z.string(),
  })
  .refine((values) => values.new_password === values.confirm, { path: ["confirm"], message: "Пароли не совпадают." });

type PasswordValues = z.infer<typeof passwordSchema>;

function Row({ label, value, wide }: { label: string; value: string | number | null | undefined; wide?: boolean }) {
  return (
    <div className={`rounded-[var(--radius-tile)] bg-surface-2 px-4 py-3 ${wide ? "sm:col-span-2" : ""}`}>
      <dt className="caption">{label}</dt>
      <dd className="m-0 mt-0.5 font-medium">{value ?? "—"}</dd>
    </div>
  );
}

function PasswordForm() {
  const [done, setDone] = useState(false);
  const form = useForm<PasswordValues>({ resolver: zodResolver(passwordSchema), defaultValues: { current_password: "", new_password: "", confirm: "" } });
  const change = useMutation({
    mutationFn: (values: PasswordValues) =>
      api("/api/auth/password", { method: "POST", body: { current_password: values.current_password, new_password: values.new_password } }),
    onSuccess: () => {
      setDone(true);
      form.reset();
    },
    onError: (error) => {
      if (error instanceof ApiError) {
        for (const [name, text] of Object.entries(error.fields)) {
          if (name === "current_password" || name === "new_password") form.setError(name, { message: text });
        }
      }
    },
  });
  const { errors } = form.formState;
  const generalError = change.error instanceof ApiError && !Object.keys(change.error.fields).length ? change.error.message : null;

  return (
    <form noValidate onSubmit={form.handleSubmit((values) => { setDone(false); change.mutate(values); })} className="flex flex-col gap-4">
      <Field id="current_password" label="Текущий пароль" error={errors.current_password?.message}>
        <Input id="current_password" type="password" autoComplete="current-password" aria-invalid={!!errors.current_password} {...form.register("current_password")} />
      </Field>
      <Field id="new_password" label="Новый пароль" hint="Не короче 10 символов. Спецсимволы не обязательны." error={errors.new_password?.message}>
        <Input id="new_password" type="password" autoComplete="new-password" aria-invalid={!!errors.new_password} {...form.register("new_password")} />
      </Field>
      <Field id="confirm" label="Повторите новый пароль" error={errors.confirm?.message}>
        <Input id="confirm" type="password" autoComplete="new-password" aria-invalid={!!errors.confirm} {...form.register("confirm")} />
      </Field>
      {generalError && <Alert>{generalError}</Alert>}
      {done && <Alert tone="info">Пароль изменён. На других устройствах нужно войти заново.</Alert>}
      <Button type="submit" loading={change.isPending} className="w-full sm:w-auto sm:self-start">Сменить пароль</Button>
    </form>
  );
}

export function ProfilePage() {
  const profile = useQuery({ queryKey: ["profile"], queryFn: () => api<Profile>("/api/me/profile") });
  const logout = useLogout();
  const data = profile.data;

  return (
    <div className="flex flex-col gap-4">
      <PageHeader eyebrow="Учётная запись" title="Профиль" />

      {data && (
        <section className="flex flex-col gap-5 rounded-[var(--radius-card)] bg-[image:var(--k-gradient-primary)] p-6 text-on-primary sm:flex-row sm:items-center">
          <span className="grid size-16 shrink-0 place-items-center rounded-full bg-white/20 text-xl font-medium">{initials(data.full_name)}</span>
          <div className="min-w-0 flex-1">
            <p className="m-0 text-[24px] leading-tight font-medium tracking-[-0.02em]">{data.full_name}</p>
            <p className="m-0 mt-1 text-sm opacity-80">{data.kind === "student" ? data.faculty : data.role}</p>
          </div>
          {data.kind === "student" && (
            <div className="flex flex-wrap gap-2">
              {[data.group, `${data.course} курс`, data.status].map((chip) => (
                <span key={chip} className="rounded-[10px] bg-white/16 px-3 py-1.5 text-[13px]">{chip}</span>
              ))}
            </div>
          )}
        </section>
      )}

      <Card aria-labelledby="profile-heading">
        <CardTitle id="profile-heading" meta={<span className="caption">только чтение</span>}>Личные данные</CardTitle>
        {profile.isPending && <Skeleton className="h-48" />}
        {profile.isError && <ErrorState message={profile.error.message} onRetry={() => profile.refetch()} />}
        {data?.kind === "student" && (
          <dl className="m-0 grid gap-2.5 sm:grid-cols-2">
            <Row label="ФИО" value={data.full_name} wide />
            <Row label="Направление" value={`${data.program.code} ${data.program.title}`} wide />
            <Row label="Факультет" value={data.faculty} />
            <Row label="Группа" value={data.group} />
            <Row label="Курс" value={data.course} />
            <Row label="Форма обучения" value={data.study_form} />
            <Row label="Статус" value={data.status} />
            <Row label="Номер зачётной книжки" value={data.record_book_no} />
            <Row label="Email" value={data.contacts.email} />
            <Row label="Телефон" value={data.contacts.phone} />
          </dl>
        )}
        {data && data.kind !== "student" && (
          <dl className="m-0 grid gap-2.5 sm:grid-cols-2">
            <Row label="ФИО" value={data.full_name} wide />
            <Row label="Роль" value={data.role} />
            <Row label="Должность" value={data.position} />
            <Row label="Факультет" value={data.faculty} wide />
          </dl>
        )}
        <p className="caption mt-3 mb-0">Учебные данные меняет только деканат.</p>
      </Card>

      <div className="grid items-start gap-4 lg:grid-cols-2">
        <Card aria-labelledby="password-heading">
          <CardTitle id="password-heading">Смена пароля</CardTitle>
          <PasswordForm />
        </Card>
        <Card aria-labelledby="sessions-heading" className="flex flex-col gap-3">
          <CardTitle id="sessions-heading">Выход</CardTitle>
          <p className="m-0 text-sm text-text-2">Выход на этом устройстве удаляет сессию на сервере. «На всех устройствах» завершит вход везде, где вы открывали кабинет.</p>
          {logout.isError && <Alert>{logout.error.message}</Alert>}
          <div className="flex flex-col gap-2 sm:flex-row">
            <Button variant="secondary" loading={logout.isPending && logout.variables === false} onClick={() => logout.mutate(false)}>
              <LogOut className="size-5" aria-hidden />
              Выйти
            </Button>
            <Button variant="danger" loading={logout.isPending && logout.variables === true} onClick={() => logout.mutate(true)}>
              <MonitorSmartphone className="size-5" aria-hidden />
              Выйти на всех устройствах
            </Button>
          </div>
        </Card>
      </div>
    </div>
  );
}

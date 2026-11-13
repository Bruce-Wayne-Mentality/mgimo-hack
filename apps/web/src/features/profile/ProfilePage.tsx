import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery } from "@tanstack/react-query";
import { LogOut, MonitorSmartphone } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Alert, Button, Card, ErrorState, Field, Input, Skeleton } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { useLogout } from "@/lib/auth";
import type { Profile } from "@/lib/types";

const passwordSchema = z
  .object({
    current_password: z.string().min(1, "Введите текущий пароль."),
    new_password: z.string().min(10, "Минимум 10 символов.").max(256, "Слишком длинный пароль."),
    confirm: z.string(),
  })
  .refine((values) => values.new_password === values.confirm, { path: ["confirm"], message: "Пароли не совпадают." });

type PasswordValues = z.infer<typeof passwordSchema>;

function Row({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div className="flex flex-col gap-0.5 border-b border-border py-2.5 last:border-0 sm:flex-row sm:gap-4">
      <dt className="text-sm text-muted sm:w-48 sm:shrink-0">{label}</dt>
      <dd className="m-0">{value ?? "—"}</dd>
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
      <Button type="submit" loading={change.isPending} className="self-start">Сменить пароль</Button>
    </form>
  );
}

export function ProfilePage() {
  const profile = useQuery({ queryKey: ["profile"], queryFn: () => api<Profile>("/api/me/profile") });
  const logout = useLogout();

  return (
    <div className="flex flex-col gap-4">
      <h1 className="m-0 text-[28px] font-semibold">Профиль</h1>
      <Card aria-labelledby="profile-heading">
        <h2 id="profile-heading" className="m-0 mb-1 text-xl font-semibold">Личные данные</h2>
        <p className="mt-0 mb-2 text-sm text-muted">Учебные данные меняет только деканат.</p>
        {profile.isPending && <Skeleton className="h-48" />}
        {profile.isError && <ErrorState message={profile.error.message} onRetry={() => profile.refetch()} />}
        {profile.data?.kind === "student" && (
          <dl className="m-0">
            <Row label="ФИО" value={profile.data.full_name} />
            <Row label="Факультет" value={profile.data.faculty} />
            <Row label="Направление" value={`${profile.data.program.code} ${profile.data.program.title}`} />
            <Row label="Курс" value={profile.data.course} />
            <Row label="Группа" value={profile.data.group} />
            <Row label="Форма обучения" value={profile.data.study_form} />
            <Row label="Статус" value={profile.data.status} />
            <Row label="Номер зачётной книжки" value={profile.data.record_book_no} />
            <Row label="Email" value={profile.data.contacts.email} />
            <Row label="Телефон" value={profile.data.contacts.phone} />
          </dl>
        )}
        {profile.data && profile.data.kind !== "student" && (
          <dl className="m-0">
            <Row label="ФИО" value={profile.data.full_name} />
            <Row label="Роль" value={profile.data.role} />
            <Row label="Должность" value={profile.data.position} />
            <Row label="Факультет" value={profile.data.faculty} />
          </dl>
        )}
      </Card>
      <Card aria-labelledby="password-heading">
        <h2 id="password-heading" className="m-0 mb-4 text-xl font-semibold">Смена пароля</h2>
        <PasswordForm />
      </Card>
      <Card aria-labelledby="sessions-heading" className="flex flex-col gap-3">
        <h2 id="sessions-heading" className="m-0 text-xl font-semibold">Выход</h2>
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
  );
}

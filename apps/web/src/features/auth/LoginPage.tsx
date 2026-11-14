import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { Eye, EyeOff, LogIn, UserRound } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { Navigate, useNavigate, useSearchParams } from "react-router";
import { z } from "zod";
import { ConceptNotice, Wordmark } from "@/components/Brand";
import { Alert, Button, Card, Field, Input } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { safeNext, useLogin, useSession } from "@/lib/auth";
import type { DemoAccount } from "@/lib/types";

const schema = z.object({
  login: z.string().trim().min(1, "Введите логин.").max(64, "Слишком длинный логин."),
  password: z.string().min(1, "Введите пароль.").max(256, "Слишком длинный пароль."),
  remember: z.boolean(),
});

type Values = z.infer<typeof schema>;

function useDemoAccounts() {
  return useQuery({
    queryKey: ["auth", "demo-accounts"],
    queryFn: () => api<{ accounts: DemoAccount[] }>("/api/auth/demo-accounts", { quiet401: true }),
    retry: false,
    staleTime: Infinity,
  });
}

export function LoginPage() {
  const session = useSession();
  const [params] = useSearchParams();
  const next = safeNext(params.get("next"));
  const navigate = useNavigate();
  const login = useLogin();
  const demo = useDemoAccounts();
  const [showPassword, setShowPassword] = useState(false);
  const errorRef = useRef<HTMLDivElement>(null);
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { login: "", password: "", remember: false } });
  const { errors } = form.formState;

  useEffect(() => {
    if (login.error) errorRef.current?.focus();
  }, [login.error]);

  if (session.data) return <Navigate to={next} replace />;

  const onSubmit = form.handleSubmit((values) =>
    login.mutate(values, { onSuccess: () => navigate(next, { replace: true }) }),
  );

  const fill = (account: DemoAccount) => {
    form.setValue("login", account.login, { shouldValidate: true });
    form.setValue("password", account.password, { shouldValidate: true });
    login.reset();
    form.setFocus("password");
  };

  const serverError = login.error instanceof ApiError ? login.error.message : login.error ? "Не удалось войти. Попробуйте ещё раз." : null;

  return (
    <div className="flex min-h-dvh flex-col">
      <ConceptNotice />
      <main className="mx-auto flex w-full max-w-[440px] flex-1 flex-col gap-5 px-4 py-8 sm:py-14">
        <Wordmark />
        <Card className="p-5 sm:p-6">
          <h1 className="m-0 mb-1 text-[28px] font-semibold leading-tight">Вход</h1>
          <p className="mt-0 mb-5 text-muted">Войдите в личный кабинет студента или сотрудника.</p>
          <form noValidate onSubmit={onSubmit} className="flex flex-col gap-4" aria-describedby={serverError ? "login-server-error" : undefined}>
            <div ref={errorRef} tabIndex={-1} aria-live="assertive" className="outline-none">
              {serverError && <Alert><span id="login-server-error">{serverError}</span></Alert>}
            </div>
            <Field id="login" label="Логин" error={errors.login?.message}>
              <Input
                id="login"
                autoComplete="username"
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck={false}
                inputMode="text"
                aria-invalid={!!errors.login}
                aria-describedby={errors.login ? "login-error" : undefined}
                {...form.register("login")}
              />
            </Field>
            <Field id="password" label="Пароль" error={errors.password?.message}>
              <div className="relative">
                <Input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  autoComplete="current-password"
                  className="pr-12"
                  aria-invalid={!!errors.password}
                  aria-describedby={errors.password ? "password-error" : undefined}
                  {...form.register("password")}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((value) => !value)}
                  className="absolute inset-y-0 right-0 grid w-11 place-items-center rounded-r-[var(--radius-control)] text-muted hover:text-text"
                  aria-label={showPassword ? "Скрыть пароль" : "Показать пароль"}
                  aria-pressed={showPassword}
                >
                  {showPassword ? <EyeOff className="size-5" aria-hidden /> : <Eye className="size-5" aria-hidden />}
                </button>
              </div>
            </Field>
            <label className="flex min-h-11 cursor-pointer items-center gap-3 text-[15px]">
              <input type="checkbox" className="size-5 accent-[var(--primary)]" {...form.register("remember")} />
              Запомнить меня на 30 дней
            </label>
            <Button type="submit" loading={login.isPending} className="w-full">
              {!login.isPending && <LogIn className="size-5" aria-hidden />}
              Войти
            </Button>
            <p className="m-0 text-sm text-muted">
              Забыли пароль? Его сбрасывает сотрудник деканата — обратитесь в свой деканат.
            </p>
          </form>
        </Card>

        {demo.data && demo.data.accounts.length > 0 && (
          <Card aria-labelledby="demo-heading">
            <h2 id="demo-heading" className="m-0 mb-1 text-base font-semibold">Тестовые аккаунты</h2>
            <p className="mt-0 mb-3 text-sm text-muted">Для жюри и проверки. Нажмите, чтобы подставить логин и пароль.</p>
            <ul className="m-0 flex list-none flex-col gap-2 p-0">
              {demo.data.accounts.map((account) => (
                <li key={account.login}>
                  <button
                    type="button"
                    onClick={() => fill(account)}
                    className="flex min-h-11 w-full items-center gap-3 rounded-[var(--radius-control)] border border-border px-3 py-2 text-left hover:bg-surface-2"
                  >
                    <UserRound className="size-5 shrink-0 text-primary" aria-hidden />
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm font-medium">{account.description}</span>
                      <span className="block truncate font-mono text-xs text-muted">
                        {account.login} · {account.password}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </Card>
        )}
        <div className="mt-auto pt-4">
          <ConceptNotice variant="footer" />
        </div>
      </main>
    </div>
  );
}

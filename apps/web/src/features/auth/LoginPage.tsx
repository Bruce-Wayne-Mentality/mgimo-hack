import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, CheckCircle2, Eye, EyeOff, UserRound } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { Navigate, useNavigate, useSearchParams } from "react-router";
import { z } from "zod";
import { BrandMark, ConceptNotice, Wordmark } from "@/components/Brand";
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

/** Blue stage with floating cabinet widgets — our own UI, no third-party imagery. */
function Stage() {
  return (
    <aside className="relative hidden overflow-hidden rounded-[var(--k-r-xl)] bg-[image:var(--k-gradient-primary)] p-10 text-on-primary lg:sticky lg:top-3 lg:flex lg:h-[calc(100dvh-1.5rem)] lg:max-h-[900px] lg:min-h-[560px] lg:flex-col lg:self-start">
      <span
        aria-hidden
        className="pointer-events-none absolute -right-8 -bottom-14 text-[200px] leading-none font-medium tracking-[-0.06em] text-[color:var(--k-on-blue-watermark)] select-none"
      >
        деканат
      </span>
      <div className="flex items-center gap-3">
        <span className="grid size-11 place-items-center rounded-[var(--radius-control)] bg-white/15">
          <BrandMark className="size-9" />
        </span>
        <span className="rounded-[10px] bg-[color:var(--k-on-blue-chip)] px-3 py-1.5 text-[13px]">Личный кабинет</span>
      </div>
      <h2 className="m-0 mt-auto max-w-[520px] text-[52px] leading-[1.04] font-normal tracking-[-0.035em] xl:text-[60px]">
        Вся учёба в&nbsp;одном окне
      </h2>
      <p className="m-0 mt-4 max-w-[440px] text-[17px] leading-relaxed opacity-85">
        Расписание, заявки и уведомления деканата — с телефона и компьютера.
      </p>
      <div aria-hidden className="relative mt-10 h-[150px]">
        <div className="absolute top-0 left-0 w-[250px] rounded-[var(--radius-card)] bg-surface p-4 text-text shadow-k-float">
          <p className="caption m-0">Следующая пара</p>
          <div className="mt-1 flex items-end justify-between gap-3">
            <span className="text-[15px] font-medium">Микроэкономика</span>
            <span className="text-[22px] leading-none font-medium text-primary">10:40</span>
          </div>
          <p className="caption m-0 mt-1">ауд. 305 · семинар</p>
        </div>
        <div className="absolute top-14 left-[270px] w-[200px] rounded-[var(--radius-card)] bg-surface/90 p-4 text-text shadow-k-float backdrop-blur-[var(--k-blur)]">
          <p className="caption m-0">Состояние учёбы</p>
          <p className="m-0 mt-1 flex items-center gap-1.5 text-[15px] font-medium">
            Всё в порядке <CheckCircle2 className="size-4 text-ok" />
          </p>
        </div>
      </div>
    </aside>
  );
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
      <div className="grid flex-1 gap-3 p-3 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
        <Stage />
        <main className="flex flex-col items-center justify-center px-1 py-6 sm:py-10">
          <div className="flex w-full max-w-[440px] flex-col gap-4">
            <div className="lg:hidden">
              <Wordmark />
            </div>
            <Card className="p-6 sm:p-8">
              <h1 className="m-0 text-[32px] font-normal tracking-[-0.03em]">Вход</h1>
              <p className="mt-1 mb-6 text-text-2">Войдите в личный кабинет студента или сотрудника.</p>
              <form noValidate onSubmit={onSubmit} className="flex flex-col gap-4" aria-describedby={serverError ? "login-server-error" : undefined}>
                <div ref={errorRef} tabIndex={-1} aria-live="assertive" className="outline-none empty:hidden">
                  {serverError && <Alert><span id="login-server-error">{serverError}</span></Alert>}
                </div>
                <Field id="login" label="Логин" error={errors.login?.message}>
                  <Input
                    id="login"
                    placeholder="student.anna"
                    autoComplete="username"
                    autoCapitalize="none"
                    autoCorrect="off"
                    spellCheck={false}
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
                      className="soft absolute inset-y-1.5 right-1.5 grid w-10 place-items-center rounded-[10px] text-muted hover:bg-surface hover:text-text"
                      aria-label={showPassword ? "Скрыть пароль" : "Показать пароль"}
                      aria-pressed={showPassword}
                    >
                      {showPassword ? <EyeOff className="size-5" aria-hidden /> : <Eye className="size-5" aria-hidden />}
                    </button>
                  </div>
                </Field>
                <label className="flex min-h-11 cursor-pointer items-center gap-3 text-[15px] text-text-2">
                  <input type="checkbox" className="size-5 shrink-0 accent-[var(--primary)]" {...form.register("remember")} />
                  Запомнить меня на 30 дней
                </label>
                <Button type="submit" loading={login.isPending} className="min-h-13 w-full text-base">
                  Войти
                </Button>
                <p className="caption m-0 text-center">Забыли пароль? Его сбрасывает сотрудник деканата — обратитесь в свой деканат.</p>
              </form>
            </Card>

            {demo.data && demo.data.accounts.length > 0 && (
              <Card aria-labelledby="demo-heading">
                <h2 id="demo-heading" className="m-0 mb-1 text-lg font-medium">Тестовые аккаунты</h2>
                <p className="caption mt-0 mb-3">Для жюри и проверки. Нажмите, чтобы подставить логин и пароль.</p>
                <ul className="m-0 flex list-none flex-col gap-2 p-0">
                  {demo.data.accounts.map((account) => (
                    <li key={account.login}>
                      <button
                        type="button"
                        onClick={() => fill(account)}
                        className="nudge soft flex min-h-14 w-full items-center gap-3 rounded-[var(--radius-tile)] bg-surface-2 px-3 py-2.5 text-left hover:bg-primary-soft"
                      >
                        <span className="grid size-10 shrink-0 place-items-center rounded-[var(--radius-control)] bg-surface text-primary">
                          <UserRound className="size-5" strokeWidth={1.75} aria-hidden />
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block text-[15px] font-medium">{account.description}</span>
                          <span className="caption block truncate">
                            {account.login} · {account.password}
                          </span>
                        </span>
                        <span className="grid size-8 shrink-0 place-items-center rounded-[var(--k-r-xs)] bg-primary text-on-primary">
                          <ArrowRight className="size-4" aria-hidden />
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </Card>
            )}
            <div className="pt-2">
              <ConceptNotice variant="footer" />
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}

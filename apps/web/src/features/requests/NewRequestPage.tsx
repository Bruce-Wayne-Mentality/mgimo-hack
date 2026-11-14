import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Check, FileText, Zap } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import { Alert, Button, Card, CardTitle, ErrorState, Field, IconChip, Input, PageHeader, Skeleton } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { StudentProfile } from "@/lib/types";
import { slaLabel, useRequestTypes, type FormField, type RequestDetail, type RequestType } from "./api";

const DRAFT_KEY = "dekanat:request-draft";
type Draft = { type: string | null; values: Record<string, string>; step: 1 | 2 | 3; key: string | null };
const EMPTY: Draft = { type: null, values: {}, step: 1, key: null };

function loadDraft(): Draft {
  try {
    const raw = localStorage.getItem(DRAFT_KEY);
    return raw ? { ...EMPTY, ...JSON.parse(raw) } : EMPTY;
  } catch {
    return EMPTY;
  }
}

function saveDraft(draft: Draft | null) {
  try {
    if (draft) localStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
    else localStorage.removeItem(DRAFT_KEY);
  } catch {
    // Private mode: the form still works, only the draft is not kept.
  }
}

/** Client-side mirror of the server checks, so mistakes show before sending. */
function validate(fields: FormField[], values: Record<string, string>): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const field of fields) {
    const value = (values[field.name] ?? "").trim();
    if (!value) {
      if (field.required) errors[field.name] = "Заполните поле.";
      continue;
    }
    if (field.kind === "int") {
      const number = Number(value);
      if (!Number.isInteger(number)) errors[field.name] = "Нужно целое число.";
      else if ((field.min !== undefined && number < field.min) || (field.max !== undefined && number > field.max)) errors[field.name] = `От ${field.min} до ${field.max}.`;
    }
    if ((field.kind === "text" || field.kind === "textarea") && field.max_length && value.length > field.max_length) errors[field.name] = `Не больше ${field.max_length} символов.`;
  }
  if (values.period_from && values.period_to && values.period_to < values.period_from) errors.period_to = "Окончание раньше начала.";
  return errors;
}

function toPayload(fields: FormField[], values: Record<string, string>) {
  const payload: Record<string, string | number> = {};
  for (const field of fields) {
    const value = (values[field.name] ?? "").trim();
    if (value) payload[field.name] = field.kind === "int" ? Number(value) : value;
  }
  return payload;
}

function display(field: FormField, value: string): string {
  if (field.kind === "select") return field.options?.find((option) => option.value === value)?.label ?? value;
  if (field.kind === "date" && value) return value.split("-").reverse().join(".");
  return value;
}

function Steps({ step }: { step: number }) {
  const labels = ["Тип", "Данные", "Проверка"];
  return (
    <ol className="m-0 flex list-none gap-2 p-0" aria-label="Шаги">
      {labels.map((label, index) => {
        const number = index + 1;
        const state = number < step ? "done" : number === step ? "current" : "next";
        return (
          <li key={label} aria-current={state === "current" ? "step" : undefined} className="flex flex-1 items-center gap-2 rounded-[var(--radius-control)] bg-surface p-2.5 shadow-k-card">
            <span className={cn("grid size-7 shrink-0 place-items-center rounded-full text-[13px] font-medium",
              state === "next" ? "bg-surface-2 text-muted" : "bg-primary text-on-primary")}>
              {state === "done" ? <Check className="size-4" aria-hidden /> : number}
            </span>
            <span className={cn("text-sm", state === "next" ? "text-muted" : "font-medium")}>{label}</span>
          </li>
        );
      })}
    </ol>
  );
}

function FieldInput({ field, value, error, onChange }: { field: FormField; value: string; error?: string; onChange: (value: string) => void }) {
  const common = { id: field.name, "aria-invalid": !!error, "aria-describedby": error ? `${field.name}-error` : field.hint ? `${field.name}-hint` : undefined };
  return (
    <Field id={field.name} label={field.label + (field.required ? "" : " (необязательно)")} error={error} hint={field.hint}>
      {field.kind === "select" ? (
        <div role="radiogroup" aria-label={field.label} className="flex flex-wrap gap-2">
          {field.options?.map((option) => (
            <button
              type="button"
              key={option.value}
              role="radio"
              aria-checked={value === option.value}
              onClick={() => onChange(option.value)}
              className={cn("soft min-h-11 rounded-[var(--radius-control)] border px-4 text-[15px]",
                value === option.value ? "border-primary bg-primary-soft font-medium text-primary-strong" : "border-transparent bg-surface-2 hover:bg-primary-soft")}
            >
              {option.label}
            </button>
          ))}
        </div>
      ) : field.kind === "textarea" ? (
        <textarea
          {...common}
          rows={4}
          maxLength={field.max_length}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className="soft w-full rounded-[var(--radius-control)] border border-transparent bg-surface-2 px-4 py-3 text-base hover:bg-bg focus:border-primary focus:bg-surface focus:shadow-[var(--k-focus-ring)] focus:outline-none aria-[invalid=true]:border-danger"
        />
      ) : (
        <Input
          {...common}
          type={field.kind === "int" ? "number" : field.kind === "date" ? "date" : "text"}
          inputMode={field.kind === "int" ? "numeric" : undefined}
          min={field.min}
          max={field.max}
          maxLength={field.max_length}
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
    </Field>
  );
}

export function NewRequestPage() {
  const types = useRequestTypes();
  const profile = useQuery({ queryKey: ["profile"], queryFn: () => api<StudentProfile>("/api/me/profile") });
  const navigate = useNavigate();
  const [draft, setDraft] = useState<Draft>(loadDraft);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const selected = useMemo(() => types.data?.find((type) => type.code === draft.type) ?? null, [types.data, draft.type]);

  useEffect(() => saveDraft(draft.type ? draft : null), [draft]);

  const choose = (type: RequestType) => {
    setErrors({});
    setDraft((current) => ({ type: type.code, values: current.type === type.code ? current.values : {}, step: 2, key: null }));
  };

  const toReview = (event: FormEvent) => {
    event.preventDefault();
    if (!selected) return;
    const found = validate(selected.fields, draft.values);
    setErrors(found);
    if (Object.keys(found).length) return;
    // One key per confirmed form: a double tap or retry never creates a duplicate (FR-REQ-2).
    setDraft((current) => ({ ...current, step: 3, key: current.key ?? crypto.randomUUID() }));
  };

  const send = async () => {
    if (!selected || !draft.key) return;
    setSending(true);
    setSendError(null);
    try {
      const created = await api<RequestDetail>("/api/requests", {
        method: "POST",
        body: { type_code: selected.code, payload: toPayload(selected.fields, draft.values) },
        headers: { "Idempotency-Key": draft.key },
      });
      saveDraft(null);
      setDraft(EMPTY);
      navigate(`/requests/${created.id}`, { replace: true });
    } catch (error) {
      if (error instanceof ApiError && Object.keys(error.fields).length) {
        setErrors(error.fields);
        setDraft((current) => ({ ...current, step: 2 }));
      }
      setSendError(error instanceof Error ? error.message : "Не удалось отправить заявку.");
    } finally {
      setSending(false);
    }
  };

  const reset = () => {
    saveDraft(null);
    setDraft(EMPTY);
    setErrors({});
  };

  return (
    <div className="flex flex-col gap-4">
      <PageHeader eyebrow={<Link to="/requests" className="text-primary hover:underline">← Все заявки</Link>} title="Новая заявка" />
      <Steps step={draft.step} />

      {types.isPending && <Skeleton className="h-64" />}
      {types.isError && <ErrorState message={types.error.message} onRetry={() => types.refetch()} />}

      {types.data && draft.step === 1 && (
        <div className="grid gap-3 sm:grid-cols-2">
          {types.data.map((type) => (
            <button
              key={type.code}
              type="button"
              onClick={() => choose(type)}
              className={cn("nudge soft flex flex-col items-start gap-3 rounded-[var(--radius-card)] bg-surface p-5 text-left shadow-k-card hover:bg-primary-soft",
                draft.type === type.code && "ring-2 ring-primary")}
            >
              <div className="flex w-full items-start justify-between gap-3">
                <IconChip>{type.auto_issue ? <Zap className="size-5" aria-hidden /> : <FileText className="size-5" aria-hidden />}</IconChip>
                <span className={cn("rounded-full px-2.5 py-1 text-[12px]", type.auto_issue ? "bg-primary text-on-primary" : "bg-surface-2 text-text-2")}>
                  {type.auto_issue ? "Сразу" : slaLabel(type.sla_days)}
                </span>
              </div>
              <span>
                <span className="block text-[17px] leading-snug font-medium">{type.title}</span>
                <span className="mt-1 block text-sm text-text-2">{type.description}</span>
              </span>
              <span className="caption flex w-full items-center justify-between gap-2">
                {type.result}
                <ArrowRight className="size-4 shrink-0 text-primary" aria-hidden />
              </span>
            </button>
          ))}
        </div>
      )}

      {selected && draft.step === 2 && (
        <form noValidate onSubmit={toReview} className="grid items-start gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
          <Card>
            <CardTitle>{selected.title}</CardTitle>
            <div className="flex flex-col gap-4">
              {selected.fields.map((field) => (
                <FieldInput
                  key={field.name}
                  field={field}
                  value={draft.values[field.name] ?? ""}
                  error={errors[field.name]}
                  onChange={(value) => setDraft((current) => ({ ...current, values: { ...current.values, [field.name]: value }, key: null }))}
                />
              ))}
            </div>
            <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-between">
              <Button type="button" variant="ghost" onClick={() => setDraft((current) => ({ ...current, step: 1 }))}>
                <ArrowLeft className="size-4" aria-hidden /> Другой тип
              </Button>
              <Button type="submit">Дальше</Button>
            </div>
            <p className="caption mt-3 mb-0">Черновик сохраняется на этом устройстве автоматически.</p>
          </Card>
          <Card>
            <CardTitle>Из профиля</CardTitle>
            {profile.data?.kind === "student" ? (
              <dl className="m-0 flex flex-col gap-2">
                {[["ФИО", profile.data.full_name], ["Группа", profile.data.group], ["Курс", String(profile.data.course)], ["Зачётная книжка", profile.data.record_book_no]].map(([label, value]) => (
                  <div key={label} className="rounded-[var(--radius-tile)] bg-surface-2 px-4 py-2.5">
                    <dt className="caption">{label}</dt>
                    <dd className="m-0 font-medium">{value}</dd>
                  </div>
                ))}
              </dl>
            ) : (
              <Skeleton className="h-40" />
            )}
            <p className="caption mt-3 mb-0">Эти данные подставятся в заявку автоматически. Ошибка? Напишите в деканат.</p>
          </Card>
        </form>
      )}

      {selected && draft.step === 3 && (
        <Card>
          <CardTitle>Проверьте заявку</CardTitle>
          <div className="mb-4 rounded-[var(--radius-tile)] bg-primary p-5 text-on-primary">
            <p className="m-0 text-[13px] opacity-80">{selected.auto_issue ? "Будет готова сразу после отправки" : `Срок: ${slaLabel(selected.sla_days)}`}</p>
            <p className="m-0 mt-1 text-[20px] font-medium">{selected.title}</p>
            <p className="m-0 mt-1 text-[13px] opacity-80">Результат: {selected.result}</p>
          </div>
          <dl className="m-0 grid gap-2 sm:grid-cols-2">
            {selected.fields.filter((field) => (draft.values[field.name] ?? "").trim()).map((field) => (
              <div key={field.name} className="rounded-[var(--radius-tile)] bg-surface-2 px-4 py-2.5">
                <dt className="caption">{field.label}</dt>
                <dd className="m-0 font-medium break-words">{display(field, draft.values[field.name] ?? "")}</dd>
              </div>
            ))}
          </dl>
          {sendError && <Alert className="mt-4">{sendError}</Alert>}
          <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-between">
            <Button type="button" variant="ghost" onClick={() => setDraft((current) => ({ ...current, step: 2 }))}>
              <ArrowLeft className="size-4" aria-hidden /> Изменить
            </Button>
            <Button type="button" loading={sending} onClick={send}>Отправить заявку</Button>
          </div>
        </Card>
      )}

      {draft.type && draft.step !== 3 && (
        <button type="button" onClick={reset} className="caption self-start hover:text-danger">
          Очистить черновик
        </button>
      )}
    </div>
  );
}

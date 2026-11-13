// Small shadcn/ui-style primitives on the design tokens (section 6).
import { Loader2 } from "lucide-react";
import { forwardRef, type ButtonHTMLAttributes, type HTMLAttributes, type InputHTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/cn";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  loading?: boolean;
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", loading = false, className, children, disabled, ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        "inline-flex min-h-11 items-center justify-center gap-2 rounded-[var(--radius-control)] px-4 text-[15px] font-semibold transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-60",
        variant === "primary" && "bg-primary text-on-primary hover:bg-primary-hover",
        variant === "secondary" && "border border-border bg-surface text-text hover:bg-surface-2",
        variant === "ghost" && "text-primary hover:bg-primary-soft",
        variant === "danger" && "border border-border bg-surface text-danger hover:bg-danger-soft",
        className,
      )}
      {...props}
    >
      {loading && <Loader2 aria-hidden className="size-4 animate-spin" />}
      {children}
    </button>
  );
});

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...props },
  ref,
) {
  return (
    <input
      ref={ref}
      className={cn(
        "min-h-11 w-full rounded-[var(--radius-control)] border border-border bg-surface px-3 text-base text-text placeholder:text-muted aria-[invalid=true]:border-danger",
        className,
      )}
      {...props}
    />
  );
});

export function Field({
  id,
  label,
  error,
  hint,
  children,
}: {
  id: string;
  label: string;
  error?: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      {children}
      {hint && !error && (
        <p id={`${id}-hint`} className="text-sm text-muted">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="text-sm text-danger">
          {error}
        </p>
      )}
    </div>
  );
}

export function Card({ className, ...props }: HTMLAttributes<HTMLElement>) {
  return <section className={cn("rounded-[var(--radius-card)] border border-border bg-surface p-4 sm:p-5", className)} {...props} />;
}

export function Alert({ tone = "danger", children, className }: { tone?: "danger" | "info"; children: ReactNode; className?: string }) {
  return (
    <div
      role={tone === "danger" ? "alert" : "status"}
      className={cn(
        "rounded-[var(--radius-control)] px-3 py-2.5 text-sm",
        tone === "danger" ? "bg-danger-soft text-danger" : "bg-primary-soft text-text",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn("animate-pulse rounded-[var(--radius-control)] bg-surface-2", className)} />;
}

export function EmptyState({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-start gap-3 rounded-[var(--radius-control)] bg-surface-2 p-4 text-sm text-muted">
      <p className="m-0">{children}</p>
      {action}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-start gap-3 rounded-[var(--radius-control)] bg-danger-soft p-4 text-sm text-danger">
      <p className="m-0">{message || "Что-то пошло не так."}</p>
      {onRetry && (
        <Button variant="secondary" onClick={onRetry}>
          Повторить
        </Button>
      )}
    </div>
  );
}

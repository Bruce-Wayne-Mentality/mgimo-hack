// Soft Blue UI primitives (see obsidian "Design System - Цифровой деканат").
// White 24px cards, 12px controls, one brand blue, faint blue-tinted shadows.
import { ChevronRight, Loader2 } from "lucide-react";
import {
  forwardRef,
  type ButtonHTMLAttributes,
  type HTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
} from "react";
import { Link } from "react-router";
import { cn } from "@/lib/cn";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger" | "onBlue";
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
        "soft inline-flex min-h-12 items-center justify-center gap-2 rounded-[var(--radius-control)] px-5 text-[15px] font-medium disabled:cursor-not-allowed disabled:opacity-50",
        variant === "primary" && "bg-primary text-on-primary hover:bg-primary-hover",
        variant === "secondary" && "bg-primary-soft text-primary-strong hover:bg-primary-tint",
        variant === "ghost" && "min-h-10 px-3 text-primary hover:bg-primary-soft",
        variant === "danger" && "bg-danger-soft text-danger hover:bg-[#fbdcdc]",
        variant === "onBlue" && "bg-surface text-primary hover:bg-primary-soft",
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
        "soft min-h-13 w-full rounded-[var(--radius-control)] border border-transparent bg-surface-2 px-4 text-base text-text placeholder:text-muted hover:bg-bg focus:border-primary focus:bg-surface focus:shadow-[var(--k-focus-ring)] focus:outline-none aria-[invalid=true]:border-danger",
        className,
      )}
      {...props}
    />
  );
});

/** Pill switch (44×24) on a native checkbox: keyboard and screen readers work as usual. */
export const Switch = forwardRef<HTMLInputElement, Omit<InputHTMLAttributes<HTMLInputElement>, "type">>(function Switch(
  { className, ...props },
  ref,
) {
  return (
    <input
      ref={ref}
      type="checkbox"
      role="switch"
      className={cn(
        "soft relative h-6 w-11 shrink-0 cursor-pointer appearance-none rounded-full bg-line-strong",
        "before:absolute before:top-0.5 before:left-0.5 before:size-5 before:rounded-full before:bg-surface before:shadow-sm before:transition-transform before:duration-200 before:content-['']",
        "checked:bg-primary checked:before:translate-x-5 disabled:cursor-wait disabled:opacity-60",
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
      <label htmlFor={id} className="text-sm font-medium text-text-2">
        {label}
      </label>
      {children}
      {hint && !error && (
        <p id={`${id}-hint`} className="caption m-0">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="m-0 text-[13px] text-danger">
          {error}
        </p>
      )}
    </div>
  );
}

export function Card({ className, ...props }: HTMLAttributes<HTMLElement>) {
  return (
    <section
      className={cn("rounded-[var(--radius-card)] bg-surface p-5 shadow-k-card sm:p-6", className)}
      {...props}
    />
  );
}

/** Card heading: 18/500 title with an optional action on the right ("Все ›", switch). */
export function CardTitle({ id, children, meta }: { id?: string; children: ReactNode; meta?: ReactNode }) {
  return (
    <div className="mb-4 flex items-center justify-between gap-3">
      <h2 id={id} className="m-0 text-lg font-medium tracking-[-0.01em]">
        {children}
      </h2>
      {meta}
    </div>
  );
}

/** "Все ›" style action link. */
export function MoreLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="nudge soft flex min-h-9 items-center gap-0.5 rounded-[10px] px-2 text-sm font-medium text-primary hover:bg-primary-soft">
      {children}
      <ChevronRight aria-hidden className="size-4" />
    </Link>
  );
}

/** Page heading: small grey eyebrow + light, tightly tracked title. */
export function PageHeader({ eyebrow, title, children }: { eyebrow?: ReactNode; title: ReactNode; children?: ReactNode }) {
  return (
    <header className="mb-1 flex flex-col gap-1.5">
      {eyebrow && <p className="caption m-0">{eyebrow}</p>}
      <h1 className="m-0 text-[30px] font-normal tracking-[-0.03em] sm:text-[40px]">{title}</h1>
      {children}
    </header>
  );
}

/** Square icon chip on a light-blue tile (used in lists, chips, status tiles). */
export function IconChip({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span className={cn("grid size-10 shrink-0 place-items-center rounded-[var(--radius-control)] bg-primary-soft text-primary", className)}>
      {children}
    </span>
  );
}

export function Alert({ tone = "danger", children, className }: { tone?: "danger" | "info"; children: ReactNode; className?: string }) {
  return (
    <div
      role={tone === "danger" ? "alert" : "status"}
      className={cn(
        "rounded-[var(--radius-control)] px-4 py-3 text-sm",
        tone === "danger" ? "bg-danger-soft text-danger" : "bg-primary-soft text-primary-strong",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn("animate-pulse rounded-[var(--radius-tile)] bg-surface-2", className)} />;
}

export function EmptyState({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-start gap-3 rounded-[var(--radius-tile)] bg-surface-2 p-4 text-sm text-text-2">
      <p className="m-0">{children}</p>
      {action}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-start gap-3 rounded-[var(--radius-tile)] bg-danger-soft p-4 text-sm text-danger">
      <p className="m-0">{message || "Что-то пошло не так."}</p>
      {onRetry && (
        <Button variant="secondary" onClick={onRetry}>
          Повторить
        </Button>
      )}
    </div>
  );
}

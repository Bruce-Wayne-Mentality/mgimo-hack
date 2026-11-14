import { AlertCircle, Ban, CheckCircle2, CircleDot, Clock3, MessageCircleQuestion, XCircle, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/cn";
import { dateTimeLabel, type RequestDetail, type RequestStatus } from "./api";

const STATUS_STYLE: Record<RequestStatus, { icon: LucideIcon; className: string }> = {
  submitted: { icon: CircleDot, className: "bg-primary-soft text-primary-strong" },
  in_review: { icon: Clock3, className: "bg-primary-soft text-primary-strong" },
  needs_info: { icon: MessageCircleQuestion, className: "bg-[#fff4dc] text-[#8a5a00]" },
  ready: { icon: CheckCircle2, className: "bg-[#e3f7ea] text-[#167a3d]" },
  rejected: { icon: XCircle, className: "bg-danger-soft text-danger" },
  cancelled: { icon: Ban, className: "bg-surface-2 text-muted" },
};

/** Status is always icon + text + colour, never colour alone (section 6). */
export function StatusChip({ status, label, className }: { status: RequestStatus; label: string; className?: string }) {
  const { icon: Icon, className: tone } = STATUS_STYLE[status];
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[13px] font-medium whitespace-nowrap", tone, className)}>
      <Icon aria-hidden className="size-4" strokeWidth={2} />
      {label}
    </span>
  );
}

/** K2 tracker: Принята → В работе → Готова, with the time of each step. */
export function Tracker({ request }: { request: RequestDetail }) {
  const terminal = request.status === "rejected" || request.status === "cancelled";
  const steps = request.track.map((step) => ({ ...step }));
  if (terminal) {
    const last = request.events[request.events.length - 1];
    steps.push({ status: request.status, label: request.status_label, at: last?.at ?? null });
  }
  const currentIndex = terminal
    ? steps.length - 1
    : request.status === "needs_info"
      ? 1
      : steps.findIndex((step) => step.status === request.status);

  return (
    <ol className="m-0 flex list-none flex-col p-0" aria-label="Ход заявки">
      {steps.map((step, index) => {
        if (terminal && index > 0 && index < steps.length - 1 && !step.at) return null;
        const done = !!step.at && index <= currentIndex;
        const current = index === currentIndex;
        const failed = current && terminal;
        return (
          <li key={step.status} className="relative flex gap-4 pb-6 last:pb-0" aria-current={current ? "step" : undefined}>
            {index < steps.length - 1 && (
              <span aria-hidden className={cn("absolute top-8 bottom-0 left-[15px] w-0.5", done && index < currentIndex ? "bg-primary" : "bg-line-strong")} />
            )}
            <span
              aria-hidden
              className={cn(
                "relative z-10 grid size-8 shrink-0 place-items-center rounded-full text-[13px] font-medium",
                failed ? "bg-danger text-white" : done ? "bg-primary text-on-primary" : "bg-surface-2 text-muted",
                current && !failed && "ring-4 ring-primary-tint",
              )}
            >
              {failed ? <AlertCircle className="size-4" /> : done ? <CheckCircle2 className="size-4" /> : index + 1}
            </span>
            <div className="min-w-0 pt-1">
              <p className={cn("m-0 text-[15px] font-medium", !done && !current && "text-muted")}>
                {step.label}
                {current && request.status === "needs_info" && <span className="ml-2 text-[13px] font-normal text-[#8a5a00]">· ждём ваш ответ</span>}
              </p>
              <p className="caption m-0">{step.at ? dateTimeLabel(step.at) : index === steps.length - 1 && !terminal ? "ещё не готова" : "—"}</p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

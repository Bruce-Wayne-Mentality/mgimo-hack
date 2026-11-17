import { AlertTriangle, CheckCircle2, CircleDashed, XCircle } from "lucide-react";
import { cn } from "@/lib/cn";
import type { Level } from "./api";

// Status is never colour alone: icon + word + colour (section 5, K1).
export const LEVEL_STYLE: Record<Level, { icon: typeof CheckCircle2; chip: string; bar: string; tile: string }> = {
  red: { icon: XCircle, chip: "bg-[#fdecec] text-[#b42318]", bar: "bg-[#e5484d]", tile: "bg-[#fff5f5]" },
  yellow: { icon: AlertTriangle, chip: "bg-[#fff4dc] text-[#8a5a00]", bar: "bg-[#f5a524]", tile: "bg-[#fffaf0]" },
  green: { icon: CheckCircle2, chip: "bg-[#e3f7ea] text-[#146c3a]", bar: "bg-[#22a35a]", tile: "bg-surface-2" },
  grey: { icon: CircleDashed, chip: "bg-surface-2 text-text-2", bar: "bg-line-strong", tile: "bg-surface-2" },
};

export function LevelBadge({ level, label, className }: { level: Level; label: string; className?: string }) {
  const style = LEVEL_STYLE[level];
  const Icon = style.icon;
  return (
    <span className={cn("inline-flex min-h-7 shrink-0 items-center gap-1.5 rounded-full px-2.5 text-[13px] font-medium", style.chip, className)}>
      <Icon aria-hidden className="size-4" />
      {label}
    </span>
  );
}

/** Score bar out of 100: earned points, the «должно быть к сегодня» marker and the admission threshold. */
export function ScoreBar({ points, expected, threshold, level, className }: { points: number; expected: number; threshold: number; level: Level; className?: string }) {
  const clamp = (value: number) => Math.max(0, Math.min(100, value));
  return (
    <div className={cn("relative pt-1", className)}>
      <div
        className="relative h-2.5 overflow-hidden rounded-full bg-surface-2"
        role="img"
        aria-label={`Набрано ${points} из 100 баллов; к сегодняшнему дню можно было набрать ${expected}; порог допуска ${threshold}`}
      >
        <div className={cn("h-full rounded-full", LEVEL_STYLE[level].bar)} style={{ width: `${clamp(points)}%` }} />
      </div>
      {expected > 0 && (
        <span aria-hidden title="Должно быть к сегодня" className="absolute top-0 h-[18px] w-0.5 -translate-x-1/2 rounded-full bg-text" style={{ left: `${clamp(expected)}%` }} />
      )}
      <span aria-hidden title="Порог допуска" className="absolute top-0.5 h-4 w-px -translate-x-1/2 border-l border-dashed border-text-2" style={{ left: `${clamp(threshold)}%` }} />
    </div>
  );
}

export function BarLegend({ expected, threshold }: { expected: number; threshold: number }) {
  return (
    <p className="caption m-0 mt-2 flex flex-wrap gap-x-4 gap-y-1">
      <span className="inline-flex items-center gap-1.5"><span aria-hidden className="h-3 w-0.5 rounded-full bg-text" />к сегодня можно было {expected}</span>
      <span className="inline-flex items-center gap-1.5"><span aria-hidden className="h-3 border-l border-dashed border-text-2" />допуск {threshold}</span>
    </p>
  );
}

export function MarkLabel({ mark }: { mark: number | null }) {
  if (mark === null) return <span className="text-text-2">зачтено</span>;
  return <span className="font-medium tabular-nums">{mark}</span>;
}

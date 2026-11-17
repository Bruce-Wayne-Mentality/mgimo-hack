export function BrandMark({ className = "size-10" }: { className?: string }) {
  // Own abstract mark (an open door), no resemblance to any university emblem.
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden>
      <rect width="32" height="32" rx="9" fill="var(--primary)" />
      <path d="M10 25V9.5L19 7v18" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinejoin="round" />
      <path d="M19 9h3.5v16H8" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="16" cy="17" r="1.3" fill="#fff" />
    </svg>
  );
}

export function Wordmark() {
  return (
    <span className="flex items-center gap-3">
      <BrandMark className="size-10" />
      <span className="leading-tight">
        <span className="block text-[17px] font-medium tracking-[-0.01em]">Цифровой деканат</span>
        <span className="caption block">концепт</span>
      </span>
    </span>
  );
}

/** Required on every screen (section 6, 10.7): this is not an official university service. */
export function ConceptNotice({ variant = "strip" }: { variant?: "strip" | "footer" }) {
  if (variant === "footer") {
    return <p className="caption m-0 text-center">Концепт для конкурса · не официальный сервис вуза · данные вымышлены</p>;
  }
  return (
    <div className="bg-primary-soft px-4 py-1.5 text-center text-xs text-primary-strong">
      Концепт для конкурса — не официальный сервис вуза
    </div>
  );
}

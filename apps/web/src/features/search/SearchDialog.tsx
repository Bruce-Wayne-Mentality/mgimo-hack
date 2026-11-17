import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Search, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";

type Result = { title: string; subtitle: string; link: string };
type Group = { key: string; title: string; items: Result[] };

function useDebounced(value: string, delay = 200): string {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

const HINTS = ["справка", "Б-118", "эконометрика", "столовая", "свободно сейчас", "стипендия"];

/** Global search across the cabinet (benchmark: HSE App X, InNoHassle Search, Polimi App). Ctrl+K / ⌘K. */
export function SearchDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const term = useDebounced(q.trim());
  const search = useQuery({
    queryKey: ["search", term],
    queryFn: () => api<{ groups: Group[] }>(`/api/search?q=${encodeURIComponent(term)}`),
    enabled: open && term.length > 0,
    staleTime: 30_000,
  });
  const flat = (search.data?.groups ?? []).flatMap((g) => g.items);

  useEffect(() => {
    if (open) {
      setQ("");
      setActive(0);
      setTimeout(() => input.current?.focus(), 10);
    }
  }, [open]);
  useEffect(() => setActive(0), [term]);

  if (!open) return null;
  const go = (link: string) => {
    onClose();
    navigate(link);
  };
  let index = -1;
  return (
    <div role="dialog" aria-modal="true" aria-label="Поиск по кабинету" className="fixed inset-0 z-[60] flex items-start justify-center bg-black/30 p-3 pt-[10vh]" onClick={onClose}>
      <div onClick={(event) => event.stopPropagation()} className="flex max-h-[75vh] w-full max-w-[620px] flex-col overflow-hidden rounded-[var(--radius-card)] bg-surface shadow-k-float">
        <div className="flex items-center gap-3 border-b border-line px-4">
          <Search aria-hidden className="size-5 text-muted" />
          <input
            ref={input}
            value={q}
            onChange={(event) => setQ(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape") onClose();
              if (event.key === "ArrowDown") { event.preventDefault(); setActive(Math.min(flat.length - 1, active + 1)); }
              if (event.key === "ArrowUp") { event.preventDefault(); setActive(Math.max(0, active - 1)); }
              if (event.key === "Enter" && flat[active]) go(flat[active].link);
            }}
            placeholder="Справка, аудитория, преподаватель, раздел…"
            aria-label="Что найти"
            className="min-h-14 flex-1 bg-transparent text-base focus:outline-none"
          />
          <button onClick={onClose} aria-label="Закрыть поиск" className="soft grid size-9 place-items-center rounded-full text-muted hover:bg-surface-2"><X aria-hidden className="size-4" /></button>
        </div>
        <div className="overflow-y-auto p-2" aria-live="polite">
          {!q.trim() && (
            <div className="p-3">
              <p className="caption m-0 mb-2">Например:</p>
              <div className="flex flex-wrap gap-1.5">
                {HINTS.map((hint) => (
                  <button key={hint} onClick={() => setQ(hint)} className="soft min-h-9 rounded-full bg-surface-2 px-3.5 text-sm text-text-2 hover:bg-primary-soft">{hint}</button>
                ))}
              </div>
            </div>
          )}
          {q.trim() && (search.isPending || term !== q.trim()) && <p className="caption m-0 p-3">Ищем…</p>}
          {term && search.data && search.data.groups.length === 0 && <p className="m-0 p-3 text-sm text-text-2">Ничего не нашлось. Попробуйте другое слово или спросите ассистента.</p>}
          {search.data?.groups.map((group) => (
            <section key={group.key} aria-label={group.title} className="mb-1">
              <h3 className="caption m-0 px-3 pt-2 pb-1 uppercase tracking-wide">{group.title}</h3>
              <ul className="m-0 list-none p-0">
                {group.items.map((item) => {
                  index += 1;
                  const mine = index;
                  return (
                    <li key={`${group.key}-${item.link}-${item.title}`}>
                      <button onMouseEnter={() => setActive(mine)} onClick={() => go(item.link)}
                        className={cn("soft flex w-full items-center gap-3 rounded-[var(--radius-tile)] px-3 py-2.5 text-left", active === mine ? "bg-primary-soft" : "hover:bg-surface-2")}>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[15px] font-medium">{item.title}</span>
                          <span className="caption block truncate">{item.subtitle}</span>
                        </span>
                        <ArrowRight aria-hidden className="size-4 shrink-0 text-muted" />
                      </button>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </div>
        <p className="caption m-0 hidden border-t border-line px-4 py-2 sm:block">↑↓ — выбрать, Enter — открыть, Esc — закрыть · Ctrl+K — открыть поиск откуда угодно</p>
      </div>
    </div>
  );
}

export function useSearchShortcut(setOpen: (open: boolean) => void) {
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen(true);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [setOpen]);
}

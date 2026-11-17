import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowUp, Bot, FileText, Headset, RotateCcw, Sparkles } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { Alert, Button, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { KbBadge, ReplySkeleton, SourceCards, type Source } from "./Sources";

type Action =
  | { kind: "link"; label: string; link: string }
  | { kind: "draft"; label: string; type: string; payload: Record<string, string | number> }
  | { kind: "handoff"; label: string; summary: string };

type Reply = { text: string; kind: string; sources: Source[]; actions: Action[]; engine?: string };
type Message = { id: string; role: "user" | "assistant"; text: string; reply?: Reply; handoff?: { number: string; link: string } };
type Info = { disclaimer: string; suggestions: string[]; engine: string; engine_label: string };

const STORE = "dekanat:assistant";

function load(): Message[] {
  try {
    return JSON.parse(sessionStorage.getItem(STORE) ?? "[]") as Message[];
  } catch {
    return [];
  }
}

export function AssistantPage() {
  const info = useQuery({ queryKey: ["assistant"], queryFn: () => api<Info>("/api/assistant"), staleTime: Infinity });
  const [messages, setMessages] = useState<Message[]>(load);
  const [text, setText] = useState("");
  const [last, setLast] = useState<{ message: string; about?: string; intent?: string } | null>(null);
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    try {
      sessionStorage.setItem(STORE, JSON.stringify(messages.slice(-30)));
    } catch {
      /* private mode */
    }
    bottom.current?.scrollIntoView({ block: "end" });
  }, [messages]);

  const ask = useMutation({
    mutationFn: (input: { message: string; about?: string; intent?: string }) => api<Reply>("/api/assistant/ask", { method: "POST", body: input }),
    onSuccess: (reply) => setMessages((list) => [...list, { id: crypto.randomUUID(), role: "assistant", text: reply.text, reply }]),
  });
  const handoff = useMutation({
    mutationFn: (summary: string) =>
      api<{ number: string; link: string }>("/api/assistant/handoff", {
        method: "POST",
        body: { summary, transcript: messages.slice(-6).map((m) => ({ role: m.role, text: m.text.slice(0, 1900) })) },
      }),
    onSuccess: (result) =>
      setMessages((list) => [...list, { id: crypto.randomUUID(), role: "assistant", text: `Передал вопрос сотруднику деканата: заявка ${result.number}. Ответ придёт в переписку заявки и в уведомления.`, handoff: result }]),
  });

  const send = (message: string, extra: { about?: string; intent?: string } = {}) => {
    const clean = message.trim();
    if (!clean || ask.isPending) return;
    setMessages((list) => [...list, { id: crypto.randomUUID(), role: "user", text: clean }]);
    setText("");
    setLast({ message: clean, ...extra });
    ask.mutate({ message: clean, ...extra });
  };

  // Deep links from cards: /assistant?about=Эконометрика&intent=consultation or ?q=…
  useEffect(() => {
    const about = params.get("about") ?? undefined;
    const intent = params.get("intent") ?? undefined;
    const q = params.get("q");
    if (about || q) {
      const message = q ?? (intent === "consultation" ? `Хочу на консультацию по дисциплине «${about}»` : intent === "attendance" ? `Пропуски по «${about}»: что делать?` : `Как у меня дела по «${about}» и что делать?`);
      setParams({}, { replace: true });
      send(message, { about, intent });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const act = (action: Action) => {
    if (action.kind === "draft") {
      const query = new URLSearchParams({ type: action.type });
      Object.entries(action.payload).forEach(([key, value]) => query.set(key, String(value)));
      try {
        localStorage.removeItem("dekanat:request-draft");
      } catch {
        /* ignore */
      }
      navigate(`/requests/new?${query}`);
    } else if (action.kind === "handoff") {
      handoff.mutate(action.summary);
    }
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    send(text);
  };

  return (
    <div className="flex min-h-[calc(100dvh-220px)] flex-col gap-4">
      <PageHeader eyebrow="Отвечает по правилам вуза и вашим данным" title="Ассистент" />
      <div role="note" className="flex items-start gap-3 rounded-[var(--radius-card)] bg-[#fff4dc] px-4 py-3 text-[14px] text-[#6b4600]">
        <Bot aria-hidden className="mt-0.5 size-5 shrink-0" />
        <span>
          <span className="font-medium">{info.data?.disclaimer ?? "Это ИИ. Он может ошибаться; важное проверьте у деканата."}</span>
          {info.data && <span className="block opacity-80">{info.data.engine_label}. Сам ассистент ничего не меняет — только предлагает, а вы подтверждаете.</span>}
        </span>
      </div>

      <div className="flex flex-1 flex-col gap-3" aria-live="polite">
        {messages.length === 0 && (
          <div className="rounded-[var(--radius-card)] bg-surface p-5 shadow-k-card">
            <p className="m-0 flex items-center gap-2 text-lg font-medium"><Sparkles aria-hidden className="size-5 text-primary" />Чем помочь?</p>
            <p className="m-0 mt-1 text-text-2">Спросите о правилах, оценках, расписании или заявках. Могу подготовить заявку или позвать сотрудника.</p>
          </div>
        )}
        {messages.map((message) => (
          <div key={message.id} className={cn("flex", message.role === "user" ? "justify-end" : "justify-start")}>
            <div className={cn("max-w-[88%] rounded-[20px] px-4 py-3 sm:max-w-[75%]", message.role === "user" ? "rounded-br-md bg-primary text-on-primary" : "rounded-bl-md bg-surface shadow-k-card")}>
              {message.reply && <KbBadge kind={message.reply.kind} />}
              <p className="m-0 text-[15px] break-words whitespace-pre-line">{message.text}</p>
              {message.reply && <SourceCards sources={message.reply.sources} />}
              {message.reply && message.reply.actions.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {message.reply.actions.map((action, index) =>
                    action.kind === "link" ? (
                      <Link key={index} to={action.link} className="soft inline-flex min-h-10 items-center rounded-[10px] bg-primary-soft px-3.5 text-sm font-medium text-primary-strong hover:bg-primary-tint">
                        {action.label}
                      </Link>
                    ) : (
                      <button
                        key={index}
                        onClick={() => act(action)}
                        disabled={handoff.isPending}
                        className={cn("soft inline-flex min-h-10 items-center gap-1.5 rounded-[10px] px-3.5 text-sm font-medium", action.kind === "draft" ? "bg-primary text-on-primary hover:bg-primary-hover" : "bg-surface-2 text-text hover:bg-primary-soft")}
                      >
                        {action.kind === "draft" ? <FileText aria-hidden className="size-4" /> : <Headset aria-hidden className="size-4" />}
                        {action.label}
                      </button>
                    ),
                  )}
                </div>
              )}
              {message.handoff && (
                <Link to={message.handoff.link} className="mt-2 inline-block text-sm font-medium text-primary underline">Открыть заявку {message.handoff.number}</Link>
              )}
            </div>
          </div>
        ))}
        {ask.isPending && <ReplySkeleton />}
        {ask.isError && (
          <Alert>
            <span className="block">Ответ не пришёл: {ask.error.message}. Проверьте соединение и повторите.</span>
            {last && (
              <button onClick={() => ask.mutate(last)} className="soft mt-2 inline-flex min-h-9 items-center gap-1.5 rounded-[10px] bg-surface px-3 text-sm font-medium text-text hover:bg-primary-soft">
                <RotateCcw aria-hidden className="size-4" /> Повторить
              </button>
            )}
          </Alert>
        )}
        {handoff.isError && <Alert>{handoff.error.message}</Alert>}
        <div ref={bottom} />
      </div>

      <div className="sticky bottom-[calc(92px+env(safe-area-inset-bottom))] flex flex-col gap-2 md:bottom-4">
        {info.data && (
          <div className="flex gap-1.5 overflow-x-auto pb-1 [scrollbar-width:none]">
            {info.data.suggestions.map((suggestion) => (
              <button key={suggestion} onClick={() => send(suggestion)} className="soft min-h-9 shrink-0 rounded-full bg-surface px-3.5 text-sm text-text-2 shadow-k-card hover:bg-primary-soft">
                {suggestion}
              </button>
            ))}
          </div>
        )}
        <form onSubmit={submit} className="flex items-end gap-2 rounded-[22px] bg-surface p-2 shadow-k-float">
          <label htmlFor="assistant-input" className="sr-only">Вопрос ассистенту</label>
          <textarea
            id="assistant-input"
            rows={1}
            maxLength={1000}
            value={text}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                send(text);
              }
            }}
            placeholder="Например: сколько нужно набрать по эконометрике?"
            className="max-h-32 min-h-11 flex-1 resize-none bg-transparent px-3 py-2.5 text-base focus:outline-none"
          />
          <Button type="submit" className="size-11 min-h-11 rounded-full p-0" disabled={!text.trim()} loading={ask.isPending} aria-label="Отправить">
            {!ask.isPending && <ArrowUp aria-hidden className="size-5" />}
          </Button>
        </form>
        <div className="flex justify-between">
          <button onClick={() => handoff.mutate(messages.filter((m) => m.role === "user").slice(-1)[0]?.text ?? "Нужна помощь сотрудника деканата")} className="soft inline-flex min-h-9 items-center gap-1.5 rounded-[10px] px-2 text-sm font-medium text-primary hover:bg-primary-soft">
            <Headset aria-hidden className="size-4" /> Позвать сотрудника
          </button>
          {messages.length > 0 && <button onClick={() => setMessages([])} className="soft min-h-9 rounded-[10px] px-2 text-sm text-muted hover:bg-surface">Очистить</button>}
        </div>
      </div>
    </div>
  );
}

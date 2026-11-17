import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pin, BellRing, Check, Send } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { Alert, Button, Card, CardTitle, EmptyState, ErrorState, IconChip, PageHeader, Skeleton, Switch } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { connectPush } from "@/lib/push";
import type { Notification, NotificationPage, NotificationSettings, TelegramStatus } from "@/lib/types";

function stamp(value: string): string {
  return new Intl.DateTimeFormat("ru", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Moscow" }).format(new Date(value));
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : "Не удалось выполнить действие.";
}

const FILTERS = [
  { key: "all", label: "Всё" },
  { key: "important", label: "Важное" },
  { key: "study", label: "Учёба" },
  { key: "deanery", label: "Деканат" },
] as const;
type Filter = (typeof FILTERS)[number]["key"];

function matches(item: Notification, filter: Filter): boolean {
  const kind = item.kind ?? "";
  if (filter === "important") return kind === "risk" || kind === "nudge" || Boolean(item.payload?.important);
  if (filter === "study") return ["grade", "risk", "reminder", "schedule", "lesson", "nudge"].some((k) => kind.startsWith(k));
  if (filter === "deanery") return ["request", "announcement", "complaint"].includes(kind);
  return true;
}

type Announcement = { id: string; title: string; body: string; author: string; audience_label: string; pinned: boolean; important: boolean; created_at: string };

function AnnouncementsList() {
  const list = useQuery({ queryKey: ["announcements"], queryFn: async () => (await api<{ items: Announcement[] }>("/api/announcements")).items });
  return (
    <Card aria-labelledby="ann-list-heading">
      <CardTitle id="ann-list-heading">Объявления деканата</CardTitle>
      <div className="flex flex-col gap-2.5">
        {list.isPending && <Skeleton className="h-24" />}
        {list.isError && <ErrorState message={list.error.message} onRetry={() => list.refetch()} />}
        {list.data?.length === 0 && <EmptyState>Актуальных объявлений нет.</EmptyState>}
        {list.data?.map((item) => (
          <article key={item.id} className={cn("rounded-[var(--radius-tile)] p-4", item.important ? "bg-[#fff4dc]" : "bg-surface-2")}>
            <h3 className="m-0 text-[15px] font-medium tracking-normal">{item.pinned && <Pin aria-label="Закреплено" className="mr-1 inline size-4 text-primary" />}{item.title}</h3>
            <p className="m-0 mt-1 text-sm whitespace-pre-line text-text-2">{item.body}</p>
            <p className="caption m-0 mt-1.5">{item.audience_label} · {item.author} · {stamp(item.created_at)}</p>
          </article>
        ))}
      </div>
    </Card>
  );
}

function Inbox() {
  const [filter, setFilter] = useState<Filter>("all");
  const client = useQueryClient();
  const inbox = useInfiniteQuery({
    queryKey: ["notifications", "list"],
    initialPageParam: null as number | null,
    queryFn: ({ pageParam }) =>
      api<NotificationPage>(`/api/me/notifications?${new URLSearchParams({ limit: "30", ...(pageParam ? { before: String(pageParam) } : {}) })}`),
    getNextPageParam: (page) => page.next_before ?? undefined,
    refetchInterval: 30_000,
  });
  const refresh = () => client.invalidateQueries({ queryKey: ["notifications"] });
  const read = useMutation({ mutationFn: (id: number) => api(`/api/me/notifications/${id}/read`, { method: "POST" }), onSettled: refresh });
  const readAll = useMutation({ mutationFn: () => api("/api/me/notifications/read-all", { method: "POST" }), onSettled: refresh });

  const all: Notification[] = inbox.data?.pages.flatMap((page) => page.items) ?? [];
  const items = all.filter((item) => matches(item, filter));
  const unread = inbox.data?.pages[0]?.unread_count ?? 0;

  return (
    <Card aria-labelledby="inbox-heading">
      <CardTitle
        id="inbox-heading"
        meta={
          <Button variant="ghost" className="min-h-9 px-2 text-sm" disabled={!unread} loading={readAll.isPending} onClick={() => readAll.mutate()}>
            Прочитать всё
          </Button>
        }
      >
        Все уведомления {unread > 0 && <span className="ml-1 inline-grid h-6 min-w-6 place-items-center rounded-full bg-primary px-1.5 align-middle text-[12px] font-medium text-on-primary">{unread}</span>}
      </CardTitle>
      {readAll.isError && <Alert className="mb-3">{message(readAll.error)}</Alert>}
      <div role="tablist" aria-label="Фильтр уведомлений" className="mb-3 flex gap-1.5 overflow-x-auto [scrollbar-width:none]">
        {FILTERS.map((option) => (
          <button key={option.key} role="tab" aria-selected={filter === option.key} onClick={() => setFilter(option.key)}
            className={cn("soft min-h-9 shrink-0 rounded-[10px] px-3.5 text-sm", filter === option.key ? "bg-primary text-on-primary" : "bg-surface-2 text-text-2 hover:bg-primary-soft")}>
            {option.label}
          </button>
        ))}
      </div>
      <div aria-live="polite" className="flex flex-col gap-2.5">
        {inbox.isPending && <Skeleton className="h-24" />}
        {inbox.isError && <ErrorState message={inbox.error.message} onRetry={() => inbox.refetch()} />}
        {inbox.isSuccess && items.length === 0 && <EmptyState>Новых уведомлений нет. Мы напишем, когда что-то изменится.</EmptyState>}
        {items.map((item) => (
          <article
            key={item.id}
            className={cn("flex items-start gap-3 rounded-[var(--radius-tile)] p-4", item.read_at ? "bg-surface-2" : "bg-primary-soft")}
          >
            <span aria-hidden className={cn("mt-2 size-2 shrink-0 rounded-full", item.read_at ? "bg-line-strong" : "bg-primary")} />
            <div className="min-w-0 flex-1">
              <h3 className="m-0 text-[15px] font-medium tracking-normal">
                {!item.read_at && <span className="sr-only">Новое: </span>}
                {item.title}
              </h3>
              <p className="m-0 mt-0.5 text-sm text-text-2">{item.body}</p>
              <time dateTime={item.created_at} className="caption mt-1 block">{stamp(item.created_at)}</time>
              {typeof item.payload?.link === "string" && item.payload.link.startsWith("/") && (
                <Link to={item.payload.link} onClick={() => !item.read_at && read.mutate(item.id)} className="mt-1.5 inline-block text-sm font-medium text-primary hover:underline">Открыть</Link>
              )}
            </div>
            {!item.read_at && (
              <Button variant="onBlue" className="min-h-9 shrink-0 px-2.5" onClick={() => read.mutate(item.id)} aria-label={`Отметить прочитанным: ${item.title}`}>
                <Check className="size-5" aria-hidden />
              </Button>
            )}
          </article>
        ))}
        {inbox.hasNextPage && (
          <Button variant="secondary" loading={inbox.isFetchingNextPage} onClick={() => inbox.fetchNextPage()}>
            Показать ещё
          </Button>
        )}
      </div>
    </Card>
  );
}

function Delivery() {
  const client = useQueryClient();
  const settings = useQuery({ queryKey: ["notifications", "settings"], queryFn: () => api<NotificationSettings>("/api/me/notification-settings") });
  const telegram = useQuery({ queryKey: ["notifications", "telegram"], queryFn: () => api<TelegramStatus>("/api/me/telegram"), refetchInterval: 15_000 });
  const [deepLink, setDeepLink] = useState<string | null>(null);
  const [browserNote, setBrowserNote] = useState<string | null>(null);

  const toggle = useMutation({
    mutationFn: (enabled: boolean) => api<NotificationSettings>("/api/me/notification-settings", { method: "PATCH", body: { enabled } }),
    onSuccess: (data) => client.setQueryData(["notifications", "settings"], data),
  });
  const browser = useMutation({
    mutationFn: async () => {
      await connectPush();
      return api<NotificationSettings>("/api/me/notification-settings", { method: "PATCH", body: { enabled: true } });
    },
    onSuccess: (data) => {
      client.setQueryData(["notifications", "settings"], data);
      setBrowserNote("Уведомления в этом браузере подключены.");
    },
  });
  const link = useMutation({
    mutationFn: () => api<{ deep_link: string }>("/api/me/telegram/link", { method: "POST" }),
    onSuccess: (data) => {
      const url = new URL(data.deep_link);
      if (url.protocol === "https:" && url.hostname === "t.me") setDeepLink(url.href);
    },
  });
  const unlink = useMutation({
    mutationFn: () => api("/api/me/telegram", { method: "DELETE" }),
    onSettled: () => client.invalidateQueries({ queryKey: ["notifications", "telegram"] }),
  });

  const error = [toggle, browser, link, unlink].find((mutation) => mutation.isError)?.error;
  const enabled = settings.data?.enabled ?? false;

  return (
    <Card aria-labelledby="delivery-heading" className="flex flex-col gap-3 [&>div:first-child]:mb-1">
      <CardTitle id="delivery-heading">Каналы</CardTitle>
      <label className="flex min-h-11 cursor-pointer items-center justify-between gap-4 rounded-[var(--radius-tile)] bg-surface-2 p-4">
        <span>
          <span className="block font-medium">Уведомления</span>
          <span className="caption block">
            {enabled ? "Включены: приходят в подключённые каналы." : "Выключены: события остаются только здесь."}
          </span>
        </span>
        <Switch
          checked={enabled}
          disabled={settings.isPending || toggle.isPending}
          onChange={(event) => toggle.mutate(event.target.checked)}
        />
      </label>
      <div className="rounded-[var(--radius-tile)] bg-surface-2 p-4">
        <div className="mb-3 flex items-center gap-3">
          <IconChip className="bg-surface">
            <BellRing className="size-5" strokeWidth={1.75} aria-hidden />
          </IconChip>
          <div>
            <h3 className="m-0 text-[15px] font-medium tracking-normal">В браузере</h3>
            <p className="caption m-0">За 10 минут до пары и при изменениях</p>
          </div>
        </div>
        <Button variant="secondary" className="w-full bg-surface" loading={browser.isPending} onClick={() => browser.mutate()}>
          Включить в браузере
        </Button>
        {browserNote && <p className="mt-2 mb-0 text-sm text-ok" role="status">{browserNote}</p>}
      </div>
      <div className="rounded-[var(--radius-tile)] bg-surface-2 p-4">
        <div className="mb-3 flex items-center gap-3">
          <IconChip className="bg-surface">
            <Send className="size-5" strokeWidth={1.75} aria-hidden />
          </IconChip>
          <div>
            <h3 className="m-0 text-[15px] font-medium tracking-normal">В Telegram</h3>
            <p className="caption m-0">
              {telegram.data?.linked
                ? `Аккаунт привязан${telegram.data.username ? `: @${telegram.data.username.replace(/^@/, "")}` : "."}`
                : "Аккаунт не привязан."}
            </p>
          </div>
        </div>
        {telegram.data?.linked ? (
          <Button variant="danger" className="w-full" loading={unlink.isPending} onClick={() => unlink.mutate()}>Отвязать</Button>
        ) : (
          <Button variant="secondary" className="w-full bg-surface" loading={link.isPending} onClick={() => link.mutate()}>
            Привязать Telegram
          </Button>
        )}
        {deepLink && !telegram.data?.linked && (
          <div className="mt-3 flex flex-col gap-2">
            <a href={deepLink} target="_blank" rel="noopener noreferrer" className="soft inline-flex min-h-12 items-center justify-center rounded-[var(--radius-control)] bg-primary px-4 font-medium text-on-primary hover:bg-primary-hover">
              Открыть Telegram ↗
            </a>
            <p className="caption m-0">Нажмите «Запустить» в боте. Ссылка действует 10 минут.</p>
          </div>
        )}
      </div>
      {error && <Alert>{error instanceof ApiError || error instanceof Error ? error.message : "Не удалось выполнить действие."}</Alert>}
    </Card>
  );
}

export function NotificationsPage() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "announcements" ? "announcements" : "inbox";
  return (
    <div className="flex flex-col gap-4">
      <PageHeader eyebrow="Оценки, заявки, расписание и объявления деканата" title="Уведомления" />
      <div role="tablist" aria-label="Разделы" className="flex gap-1.5">
        {[{ key: "inbox", label: "Лента" }, { key: "announcements", label: "Объявления" }].map((option) => (
          <button key={option.key} role="tab" aria-selected={tab === option.key} onClick={() => setParams(option.key === "inbox" ? {} : { tab: option.key }, { replace: true })}
            className={cn("soft min-h-10 rounded-[10px] px-4 text-sm", tab === option.key ? "bg-primary text-on-primary" : "bg-surface text-text-2 shadow-k-card hover:bg-primary-soft")}>
            {option.label}
          </button>
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px] lg:items-start">
        {tab === "inbox" ? <Inbox /> : <AnnouncementsList />}
        <Delivery />
      </div>
    </div>
  );
}

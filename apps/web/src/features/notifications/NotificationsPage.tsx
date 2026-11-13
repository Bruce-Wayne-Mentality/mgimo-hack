import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing, Check, Send } from "lucide-react";
import { useState } from "react";
import { Alert, Button, Card, EmptyState, ErrorState, Skeleton } from "@/components/ui";
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

function Inbox() {
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

  const items: Notification[] = inbox.data?.pages.flatMap((page) => page.items) ?? [];
  const unread = inbox.data?.pages[0]?.unread_count ?? 0;

  return (
    <Card aria-labelledby="inbox-heading">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 id="inbox-heading" className="m-0 text-xl font-semibold">Все уведомления</h2>
        <Button variant="ghost" disabled={!unread} loading={readAll.isPending} onClick={() => readAll.mutate()}>
          Прочитать всё
        </Button>
      </div>
      {readAll.isError && <Alert className="mb-3">{message(readAll.error)}</Alert>}
      <div aria-live="polite" className="flex flex-col gap-2">
        {inbox.isPending && <Skeleton className="h-24" />}
        {inbox.isError && <ErrorState message={inbox.error.message} onRetry={() => inbox.refetch()} />}
        {inbox.isSuccess && items.length === 0 && <EmptyState>Здесь появятся напоминания о парах и изменения расписания.</EmptyState>}
        {items.map((item) => (
          <article
            key={item.id}
            className={cn("flex gap-3 rounded-[var(--radius-control)] border border-border p-3", !item.read_at && "border-primary bg-primary-soft")}
          >
            <div className="min-w-0 flex-1">
              <h3 className="m-0 text-[15px] font-semibold">
                {!item.read_at && <span className="sr-only">Новое: </span>}
                {item.title}
              </h3>
              <p className="m-0 text-sm">{item.body}</p>
              <time dateTime={item.created_at} className="text-xs text-muted">{stamp(item.created_at)}</time>
            </div>
            {!item.read_at && (
              <Button variant="ghost" className="shrink-0 px-2" onClick={() => read.mutate(item.id)} aria-label={`Отметить прочитанным: ${item.title}`}>
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
    <Card aria-labelledby="delivery-heading" className="flex flex-col gap-4">
      <h2 id="delivery-heading" className="m-0 text-xl font-semibold">Настройки</h2>
      <label className="flex min-h-11 cursor-pointer items-center justify-between gap-4">
        <span>
          <span className="block font-medium">Уведомления</span>
          <span className="block text-sm text-muted">
            {enabled ? "Включены: приходят в подключённые каналы." : "Выключены: события остаются только здесь."}
          </span>
        </span>
        <input
          type="checkbox"
          role="switch"
          className="size-6 accent-[var(--primary)]"
          checked={enabled}
          disabled={settings.isPending || toggle.isPending}
          onChange={(event) => toggle.mutate(event.target.checked)}
        />
      </label>
      <div className="border-t border-border pt-4">
        <h3 className="m-0 mb-1 text-base font-semibold">В браузере</h3>
        <p className="mt-0 mb-3 text-sm text-muted">Напоминание за 10 минут до пары и изменения расписания.</p>
        <Button variant="secondary" loading={browser.isPending} onClick={() => browser.mutate()}>
          <BellRing className="size-5" aria-hidden />
          Включить в браузере
        </Button>
        {browserNote && <p className="mt-2 mb-0 text-sm text-ok" role="status">{browserNote}</p>}
      </div>
      <div className="border-t border-border pt-4">
        <h3 className="m-0 mb-1 text-base font-semibold">В Telegram</h3>
        <p className="mt-0 mb-3 text-sm text-muted">
          {telegram.data?.linked
            ? `Аккаунт привязан${telegram.data.username ? `: @${telegram.data.username.replace(/^@/, "")}` : "."}`
            : "Аккаунт не привязан."}
        </p>
        {telegram.data?.linked ? (
          <Button variant="danger" loading={unlink.isPending} onClick={() => unlink.mutate()}>Отвязать</Button>
        ) : (
          <Button variant="secondary" loading={link.isPending} onClick={() => link.mutate()}>
            <Send className="size-5" aria-hidden />
            Привязать Telegram
          </Button>
        )}
        {deepLink && !telegram.data?.linked && (
          <div className="mt-3 flex flex-col gap-2">
            <a href={deepLink} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center justify-center rounded-[var(--radius-control)] bg-primary px-4 font-semibold text-on-primary">
              Открыть Telegram ↗
            </a>
            <p className="m-0 text-sm text-muted">Нажмите «Запустить» в боте. Ссылка действует 10 минут.</p>
          </div>
        )}
      </div>
      {error && <Alert>{error instanceof ApiError || error instanceof Error ? error.message : "Не удалось выполнить действие."}</Alert>}
    </Card>
  );
}

export function NotificationsPage() {
  return (
    <div className="flex flex-col gap-4">
      <h1 className="m-0 text-[28px] font-semibold">Уведомления</h1>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px] lg:items-start">
        <Inbox />
        <Delivery />
      </div>
    </div>
  );
}

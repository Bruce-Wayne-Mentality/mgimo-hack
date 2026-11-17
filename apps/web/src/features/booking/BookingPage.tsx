import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, CheckCircle2, MapPin, Users, X } from "lucide-react";
import { useMemo, useState } from "react";
import { Alert, Button, Card, CardTitle, EmptyState, ErrorState, Input, PageHeader, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { useSession } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { addDays, moscowDate, timeLabel } from "../schedule/lessons";

type Slot = { starts_at: string; free: boolean; reason: "booking" | "lesson" | "past" | null };
type Resource = {
  id: string; code: string; title: string; kind: "classroom" | "coworking" | "consultation"; kind_label: string;
  building: string; floor: number; capacity: number; features: string[]; opens: string; closes: string; host: string | null;
  slots: Slot[]; free_count: number;
};
type Booking = {
  id: string; resource: Omit<Resource, "slots" | "free_count">; starts_at: string; ends_at: string; status: string; status_label: string;
  purpose: string | null; checked_in: boolean; cancel_reason: string | null; can_check_in: boolean; can_cancel: boolean; owner: string | null;
};
type Heat = { date: string; hours: number[]; rows: { resource: { id: string; title: string; kind_label: string }; cells: number[] }[] };

const KINDS = [
  { key: "", label: "Все" },
  { key: "coworking", label: "Коворкинги" },
  { key: "classroom", label: "Аудитории" },
  { key: "consultation", label: "Консультации" },
] as const;
const DURATIONS = [30, 60, 90, 120, 180];

function dayChip(day: string): { week: string; num: string } {
  const date = new Date(`${day}T12:00:00+03:00`);
  return {
    week: new Intl.DateTimeFormat("ru", { weekday: "short", timeZone: "Europe/Moscow" }).format(date),
    num: new Intl.DateTimeFormat("ru", { day: "numeric", timeZone: "Europe/Moscow" }).format(date),
  };
}

function fullDay(value: string): string {
  return new Intl.DateTimeFormat("ru", { weekday: "long", day: "numeric", month: "long", timeZone: "Europe/Moscow" }).format(new Date(value));
}

function MyBookings() {
  const client = useQueryClient();
  const list = useQuery({ queryKey: ["bookings"], queryFn: async () => (await api<{ items: Booking[] }>("/api/bookings")).items, refetchInterval: 30_000 });
  const act = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "cancel" | "check-in" }) => api<Booking>(`/api/bookings/${id}/${action}`, { method: "POST" }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["bookings"] });
      client.invalidateQueries({ queryKey: ["resources"] });
    },
  });
  const items = list.data ?? [];
  return (
    <Card aria-labelledby="mine-heading">
      <CardTitle id="mine-heading">Мои брони</CardTitle>
      {list.isPending && <Skeleton className="h-20" />}
      {list.isError && <ErrorState message={list.error.message} onRetry={() => list.refetch()} />}
      {list.isSuccess && items.length === 0 && <EmptyState>Броней пока нет. Выберите место и время слева.</EmptyState>}
      <ul className="m-0 flex list-none flex-col gap-2.5 p-0">
        {items.map((item) => (
          <li key={item.id} className={cn("rounded-[var(--radius-tile)] p-4", item.status === "active" ? "bg-primary-soft" : "bg-surface-2 opacity-70")}>
            <p className="m-0 font-medium">{item.resource.title}</p>
            <p className="caption m-0 mt-0.5 first-letter:uppercase">{fullDay(item.starts_at)}, {timeLabel(item.starts_at)}–{timeLabel(item.ends_at)} · {item.status_label}{item.checked_in ? " · вы на месте" : ""}</p>
            {item.purpose && <p className="m-0 mt-1 text-sm text-text-2">{item.purpose}</p>}
            {item.cancel_reason && item.status === "cancelled" && <p className="m-0 mt-1 text-sm text-text-2">{item.cancel_reason}</p>}
            {(item.can_check_in || item.can_cancel) && (
              <div className="mt-3 flex flex-wrap gap-2">
                {item.can_check_in && (
                  <Button className="min-h-10" loading={act.isPending} onClick={() => act.mutate({ id: item.id, action: "check-in" })}>
                    <CheckCircle2 aria-hidden className="size-4" /> Я на месте
                  </Button>
                )}
                {item.can_cancel && (
                  <Button variant="ghost" className="text-danger hover:bg-danger-soft" loading={act.isPending} onClick={() => act.mutate({ id: item.id, action: "cancel" })}>Отменить</Button>
                )}
              </div>
            )}
          </li>
        ))}
      </ul>
      {act.isError && <Alert className="mt-3">{act.error.message}</Alert>}
      <p className="caption m-0 mt-3">«Я на месте» доступно за 10 минут до начала и 15 минут после — без отметки бронь освобождается для других.</p>
    </Card>
  );
}

function HeatMap({ day }: { day: string }) {
  const heat = useQuery({ queryKey: ["heatmap", day], queryFn: () => api<Heat>(`/api/resources/heatmap?date=${day}`) });
  if (heat.isPending) return <Skeleton className="h-64" />;
  if (heat.isError) return <ErrorState message={heat.error.message} onRetry={() => heat.refetch()} />;
  const data = heat.data;
  return (
    <Card aria-labelledby="heat-heading" className="p-0 sm:p-0">
      <div className="p-5 pb-3 sm:p-6 sm:pb-3">
        <CardTitle id="heat-heading">Загрузка помещений</CardTitle>
        <p className="caption m-0">Доля часа, занятая бронями и парами. Это не датчики присутствия: карта показывает брони, а не людей.</p>
      </div>
      <div className="overflow-x-auto px-5 pb-5 sm:px-6">
        <table className="w-full min-w-[680px] border-separate border-spacing-1 text-[12px]">
          <thead>
            <tr>
              <th scope="col" className="text-left font-medium text-muted">Помещение</th>
              {data.hours.map((hour) => <th key={hour} scope="col" className="font-medium text-muted tabular-nums">{hour}</th>)}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row) => (
              <tr key={row.resource.id}>
                <th scope="row" className="max-w-40 truncate pr-2 text-left font-normal">{row.resource.title}</th>
                {row.cells.map((value, index) => (
                  <td key={index} title={`${data.hours[index]}:00 — ${Math.round(value * 100)}%`}
                    className="h-8 min-w-9 rounded-[6px] text-center tabular-nums"
                    style={{ background: `color-mix(in srgb, var(--primary) ${Math.round(value * 85)}%, var(--surface-2))`, color: value > 0.55 ? "white" : "var(--text-2)" }}>
                    {value > 0 ? `${Math.round(value * 100)}` : ""}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function StaffBookings({ day }: { day: string }) {
  const client = useQueryClient();
  const list = useQuery({ queryKey: ["staff-bookings", day], queryFn: async () => (await api<{ items: Booking[] }>(`/api/staff/bookings?date=${day}`)).items });
  const [reason, setReason] = useState("");
  const [target, setTarget] = useState<string | null>(null);
  const cancel = useMutation({
    mutationFn: (id: string) => api<Booking>(`/api/staff/bookings/${id}/cancel`, { method: "POST", body: { reason } }),
    onSuccess: () => {
      setTarget(null);
      setReason("");
      client.invalidateQueries({ queryKey: ["staff-bookings"] });
      client.invalidateQueries({ queryKey: ["heatmap"] });
    },
  });
  return (
    <Card aria-labelledby="staff-book-heading">
      <CardTitle id="staff-book-heading">Брони на день</CardTitle>
      {list.isPending && <Skeleton className="h-20" />}
      {list.data?.length === 0 && <EmptyState>На этот день броней нет.</EmptyState>}
      <ul className="m-0 flex list-none flex-col gap-2 p-0">
        {list.data?.map((item) => (
          <li key={item.id} className="rounded-[var(--radius-tile)] bg-surface-2 p-3.5">
            <p className="m-0 font-medium">{timeLabel(item.starts_at)}–{timeLabel(item.ends_at)} · {item.resource.title}</p>
            <p className="caption m-0">{item.owner ?? "—"} · {item.status_label}{item.purpose ? ` · ${item.purpose}` : ""}</p>
            {item.status === "active" && (target === item.id ? (
              <div className="mt-2 flex flex-col gap-2">
                <Input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Причина (студент получит уведомление)" />
                <div className="flex gap-2">
                  <Button variant="danger" disabled={reason.trim().length < 3} loading={cancel.isPending} onClick={() => cancel.mutate(item.id)}>Отменить бронь</Button>
                  <Button variant="ghost" onClick={() => setTarget(null)}>Назад</Button>
                </div>
              </div>
            ) : (
              <Button variant="ghost" className="mt-1 min-h-9 px-2 text-sm text-danger hover:bg-danger-soft" onClick={() => setTarget(item.id)}>Отменить с причиной</Button>
            ))}
          </li>
        ))}
      </ul>
      {cancel.isError && <Alert className="mt-3">{cancel.error.message}</Alert>}
    </Card>
  );
}

export function BookingPage() {
  const role = useSession().data?.user.role;
  const isStudent = role === "student";
  const today = moscowDate();
  const days = useMemo(() => Array.from({ length: 15 }, (_, index) => addDays(today, index)), [today]);
  const [day, setDay] = useState(today);
  const [kind, setKind] = useState<string>("");
  const [tab, setTab] = useState<"book" | "heat">(isStudent ? "book" : "heat");
  const [pick, setPick] = useState<{ resource: Resource; slot: Slot } | null>(null);
  const [minutes, setMinutes] = useState(60);
  const [purpose, setPurpose] = useState("");
  const client = useQueryClient();
  const resources = useQuery({
    queryKey: ["resources", day, kind],
    queryFn: () => api<{ items: Resource[] }>(`/api/resources?date=${day}${kind ? `&kind=${kind}` : ""}`),
    enabled: tab === "book",
  });
  const book = useMutation({
    mutationFn: () => api<Booking>("/api/bookings", { method: "POST", body: { resource_id: pick!.resource.id, starts_at: pick!.slot.starts_at, minutes, purpose: purpose.trim() || null } }),
    onSuccess: () => {
      setPick(null);
      setPurpose("");
      client.invalidateQueries({ queryKey: ["resources"] });
      client.invalidateQueries({ queryKey: ["bookings"] });
    },
  });

  // How long the picked start can last before the next taken slot or closing time.
  const maxMinutes = useMemo(() => {
    if (!pick) return 0;
    const index = pick.resource.slots.findIndex((slot) => slot.starts_at === pick.slot.starts_at);
    let free = 0;
    for (let i = index; i < pick.resource.slots.length && pick.resource.slots[i]!.free && free < 180; i += 1) free += 30;
    return free;
  }, [pick]);

  return (
    <div className="flex flex-col gap-4">
      <PageHeader eyebrow="Аудитории, коворкинги и консультации" title="Бронирование" />
      <div role="tablist" aria-label="Разделы бронирования" className="flex gap-1.5">
        {(isStudent ? [{ key: "book", label: "Забронировать" }, { key: "heat", label: "Загрузка" }] : [{ key: "heat", label: "Загрузка и брони" }]).map((option) => (
          <button key={option.key} role="tab" aria-selected={tab === option.key} onClick={() => setTab(option.key as "book" | "heat")}
            className={cn("soft min-h-10 rounded-[10px] px-4 text-sm", tab === option.key ? "bg-primary text-on-primary" : "bg-surface text-text-2 shadow-k-card hover:bg-primary-soft")}>
            {option.label}
          </button>
        ))}
      </div>
      <div role="group" aria-label="День" className="-mx-1 flex gap-1.5 overflow-x-auto px-1 pb-1 [scrollbar-width:none]">
        {days.map((value) => {
          const chip = dayChip(value);
          return (
            <button key={value} aria-pressed={day === value} onClick={() => { setDay(value); setPick(null); }}
              className={cn("soft flex min-h-14 w-12 shrink-0 flex-col items-center justify-center rounded-[14px] text-[12px]", day === value ? "bg-primary text-on-primary" : "bg-surface text-text-2 shadow-k-card hover:bg-primary-soft")}>
              <span className="uppercase">{chip.week}</span>
              <span className="text-[17px] font-medium">{chip.num}</span>
            </button>
          );
        })}
      </div>

      {tab === "heat" ? (
        <div className="grid grid-cols-[minmax(0,1fr)] gap-4">
          <HeatMap day={day} />
          {!isStudent && <StaffBookings day={day} />}
        </div>
      ) : (
        <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap gap-1.5" role="group" aria-label="Тип">
              {KINDS.map((option) => (
                <button key={option.key} aria-pressed={kind === option.key} onClick={() => setKind(option.key)}
                  className={cn("soft min-h-9 rounded-full px-3.5 text-sm", kind === option.key ? "bg-text text-surface" : "bg-surface text-text-2 shadow-k-card hover:bg-primary-soft")}>
                  {option.label}
                </button>
              ))}
            </div>
            {resources.isPending && <Skeleton className="h-48" />}
            {resources.isError && <ErrorState message={resources.error.message} onRetry={() => resources.refetch()} />}
            {resources.data?.items.map((resource) => (
              <Card key={resource.id} aria-label={resource.title} className="p-4 sm:p-5">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="m-0 text-[16px] font-medium">{resource.title}</p>
                    <p className="caption m-0 mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5">
                      <span className="inline-flex items-center gap-1"><MapPin aria-hidden className="size-3.5" />{resource.building}, {resource.floor} эт.</span>
                      <span className="inline-flex items-center gap-1"><Users aria-hidden className="size-3.5" />до {resource.capacity}</span>
                      {resource.features.length > 0 && <span>{resource.features.join(", ")}</span>}
                    </p>
                    {resource.host && <p className="m-0 mt-1 text-sm text-text-2">{resource.host}</p>}
                  </div>
                  <span className="shrink-0 rounded-full bg-surface-2 px-2.5 py-1 text-[12px] text-text-2">{resource.kind_label}</span>
                </div>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {resource.slots.filter((slot) => slot.reason !== "past").map((slot) => {
                    const chosen = pick?.slot.starts_at === slot.starts_at && pick.resource.id === resource.id;
                    return (
                      <button key={slot.starts_at} disabled={!slot.free} onClick={() => { setPick({ resource, slot }); setMinutes(60); book.reset(); }}
                        title={slot.reason === "lesson" ? "Пара" : slot.reason === "booking" ? "Занято" : "Свободно"}
                        className={cn("soft min-h-10 w-[62px] rounded-[10px] text-sm tabular-nums",
                          chosen ? "bg-primary text-on-primary" : slot.free ? "bg-primary-soft text-primary-strong hover:bg-primary-tint" : slot.reason === "lesson" ? "bg-[#fff4dc] text-[#b07a1a] line-through" : "bg-surface-2 text-muted line-through")}>
                        {timeLabel(slot.starts_at)}
                      </button>
                    );
                  })}
                  {resource.free_count === 0 && <p className="caption m-0">На этот день свободного времени нет.</p>}
                </div>
              </Card>
            ))}
            <p className="caption m-0 flex items-center gap-1.5"><Building2 aria-hidden className="size-4" />Жёлтым — время пар в аудитории. Не больше 3 активных броней, 4 часов в день и на 14 дней вперёд.</p>
          </div>
          <div className="flex flex-col gap-4 lg:sticky lg:top-6">
            {pick && (
              <Card aria-labelledby="pick-heading" className="fixed inset-x-3 bottom-[calc(88px+env(safe-area-inset-bottom))] z-40 max-h-[70dvh] overflow-y-auto shadow-k-float ring-2 ring-primary lg:static lg:max-h-none lg:shadow-k-card">
                <div className="flex items-start justify-between gap-2">
                  <CardTitle id="pick-heading">Подтверждение</CardTitle>
                  <button aria-label="Закрыть" onClick={() => setPick(null)} className="soft grid size-9 place-items-center rounded-full text-muted hover:bg-surface-2"><X aria-hidden className="size-4" /></button>
                </div>
                <p className="m-0 font-medium">{pick.resource.title}</p>
                <p className="caption m-0 first-letter:uppercase">{fullDay(pick.slot.starts_at)}, с {timeLabel(pick.slot.starts_at)}</p>
                <p className="mt-3 mb-1.5 text-sm text-text-2">Длительность</p>
                <div className="flex flex-wrap gap-1.5">
                  {DURATIONS.map((value) => (
                    <button key={value} disabled={value > maxMinutes} onClick={() => setMinutes(value)}
                      className={cn("soft min-h-10 rounded-[10px] px-3 text-sm", minutes === value ? "bg-primary text-on-primary" : "bg-surface-2 hover:bg-primary-soft disabled:opacity-40")}>
                      {value < 60 ? `${value} мин` : `${value / 60} ч`}
                    </button>
                  ))}
                </div>
                <Input className="mt-3" maxLength={200} value={purpose} onChange={(event) => setPurpose(event.target.value)} placeholder="Цель (необязательно)" aria-label="Цель брони" />
                {book.isError && <Alert className="mt-3">{book.error.message}</Alert>}
                <Button className="mt-3 w-full" loading={book.isPending} disabled={minutes > maxMinutes} onClick={() => book.mutate()}>
                  Забронировать до {timeLabel(new Date(new Date(pick.slot.starts_at).getTime() + minutes * 60000).toISOString())}
                </Button>
              </Card>
            )}
            {book.isSuccess && <Alert tone="info">Готово! Бронь в списке ниже и в календаре.</Alert>}
            <MyBookings />
          </div>
        </div>
      )}
    </div>
  );
}

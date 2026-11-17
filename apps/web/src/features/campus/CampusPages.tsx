import { useQuery } from "@tanstack/react-query";
import { Building2, Clock, Leaf, Mail, MapPin, Navigation, Search, UserRound, Users, UtensilsCrossed } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { Card, CardTitle, EmptyState, ErrorState, Input, PageHeader, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { addDays, moscowDate } from "../schedule/lessons";
import { FreeNowList, type Location } from "./FreeNow";

export { FreeNowCard } from "./FreeNow";

type Building = { letter: string; title: string; address: string; floors: number; note: string; rooms: Location[] };
type Teacher = { name: string; disciplines: { id: string | null; title: string }[]; groups: string[]; hours: { weekday_label: string; time: string; room: string }[]; email: string; booking_resource: string | null };
type Canteen = { id: string; title: string; place: string; hours: string; busy: string; lunch_price: number; open: boolean; sections: { title: string; items: { name: string; price: number; vegetarian: boolean }[] }[] };

function RoomFinder({ initial }: { initial: string }) {
  const [code, setCode] = useState(initial);
  const [query, setQuery] = useState(initial);
  const room = useQuery({
    queryKey: ["room", query],
    queryFn: () => api<Location>(`/api/campus/room?code=${encodeURIComponent(query)}`),
    enabled: query.trim().length >= 2,
    retry: false,
  });
  return (
    <Card aria-labelledby="finder-heading">
      <CardTitle id="finder-heading" meta={<Navigation aria-hidden className="size-5 text-primary" />}>Как найти аудиторию</CardTitle>
      <form onSubmit={(event) => { event.preventDefault(); setQuery(code.trim().toUpperCase()); }} className="flex gap-2">
        <Input value={code} onChange={(event) => setCode(event.target.value)} placeholder="Например, Б-118" aria-label="Номер аудитории" maxLength={16} />
        <button type="submit" className="soft grid min-h-13 w-13 shrink-0 place-items-center rounded-[var(--radius-control)] bg-primary text-on-primary" aria-label="Найти"><Search aria-hidden className="size-5" /></button>
      </form>
      {room.isError && query && <p className="m-0 mt-3 text-sm text-danger">{room.error.message}</p>}
      {room.data && (
        <div className="mt-4 rounded-[var(--radius-tile)] bg-primary-soft p-4">
          <p className="m-0 text-[22px] font-medium tracking-[-0.01em]">{room.data.room}</p>
          <p className="m-0 mt-1 text-[15px]">{room.data.building_title}, {room.data.floor_text}, {room.data.wing}</p>
          <p className="m-0 mt-1 text-sm text-text-2">{room.data.directions}</p>
          <p className="caption m-0 mt-2 flex items-center gap-1"><MapPin aria-hidden className="size-4" />{room.data.address}</p>
        </div>
      )}
    </Card>
  );
}

/** Корпуса и аудитории + «свободно сейчас» (benchmark: Imperial/UCL/EPFL/Stanford campus maps). */
export function CampusPage() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "free" ? "free" : "map";
  const rooms = useQuery({ queryKey: ["campus-rooms"], queryFn: () => api<{ buildings: Building[] }>("/api/campus/rooms"), staleTime: Infinity });
  return (
    <div className="flex flex-col gap-4">
      <PageHeader eyebrow="Корпуса, этажи и пустые аудитории" title="Кампус" />
      <div role="tablist" aria-label="Разделы" className="flex gap-1.5">
        {[{ key: "map", label: "Корпуса и аудитории" }, { key: "free", label: "Свободно сейчас" }].map((option) => (
          <button key={option.key} role="tab" aria-selected={tab === option.key} onClick={() => setParams(option.key === "map" ? {} : { tab: option.key }, { replace: true })}
            className={cn("soft min-h-10 rounded-[10px] px-4 text-sm", tab === option.key ? "bg-primary text-on-primary" : "bg-surface text-text-2 shadow-k-card hover:bg-primary-soft")}>
            {option.label}
          </button>
        ))}
      </div>
      {tab === "free" ? (
        <Card>
          <CardTitle>Можно позаниматься прямо сейчас</CardTitle>
          <p className="caption m-0 mb-3">Помещения без пар и броней ещё минимум 20 минут. Обновляется каждую минуту.</p>
          <FreeNowList />
        </Card>
      ) : (
        <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
          <RoomFinder initial={params.get("room") ?? ""} />
          <div className="flex flex-col gap-4">
            {rooms.isPending && <Skeleton className="h-48" />}
            {rooms.data?.buildings.map((building) => (
              <Card key={building.letter} aria-label={building.title}>
                <CardTitle meta={<span className="caption">{building.floors} этажа</span>}>
                  <span className="inline-flex items-center gap-2"><Building2 aria-hidden className="size-5 text-primary" />{building.title}</span>
                </CardTitle>
                <p className="m-0 text-sm text-text-2">{building.note}</p>
                <p className="caption m-0 mt-1">{building.address}</p>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {building.rooms.map((room) => (
                    <Link key={room.room} to={`/campus?room=${encodeURIComponent(room.room)}`} onClick={() => setParams({ room: room.room })}
                      className="soft min-h-9 rounded-[10px] bg-surface-2 px-3 py-1.5 text-sm hover:bg-primary-soft">
                      {room.room} <span className="text-muted">· {room.floor} эт.</span>
                    </Link>
                  ))}
                </div>
              </Card>
            ))}
            <p className="caption m-0">Корпуса и адреса вымышленные. Схема номеров: буква — корпус, первая цифра — этаж.</p>
          </div>
        </div>
      )}
    </div>
  );
}

/** Преподаватели и часы консультаций (benchmark: MIT directory, ITMO «расписание консультаций», HSE search). */
export function TeachersPage() {
  const [params] = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  const teachers = useQuery({ queryKey: ["teachers"], queryFn: async () => (await api<{ items: Teacher[] }>("/api/teachers")).items });
  const items = useMemo(() => {
    const term = q.trim().toLowerCase();
    return (teachers.data ?? []).filter((t) => !term || t.name.toLowerCase().includes(term) || t.disciplines.some((d) => d.title.toLowerCase().includes(term)));
  }, [teachers.data, q]);
  return (
    <div className="flex flex-col gap-4">
      <PageHeader eyebrow="Часы консультаций и контакты" title="Преподаватели" />
      <Input value={q} onChange={(event) => setQ(event.target.value)} placeholder="Фамилия или дисциплина" aria-label="Поиск преподавателя" className="max-w-[420px] bg-surface shadow-k-card" />
      {teachers.isPending && <Skeleton className="h-40" />}
      {teachers.isError && <ErrorState message={teachers.error.message} />}
      {teachers.data && items.length === 0 && <EmptyState>Никого не нашли.</EmptyState>}
      <div className="grid grid-cols-[minmax(0,1fr)] gap-3 md:grid-cols-2">
        {items.map((teacher) => (
          <Card key={teacher.name} className="flex flex-col gap-3 p-5">
            <div className="flex items-start gap-3">
              <span className="grid size-11 shrink-0 place-items-center rounded-full bg-primary-soft text-primary"><UserRound aria-hidden className="size-5" /></span>
              <div className="min-w-0">
                <p className="m-0 font-medium">{teacher.name}</p>
                <p className="caption m-0">{teacher.disciplines.map((d) => d.title).join(", ")}</p>
              </div>
            </div>
            <div className="rounded-[var(--radius-tile)] bg-surface-2 p-3">
              <p className="caption m-0 mb-1 flex items-center gap-1.5"><Clock aria-hidden className="size-4" />Консультации</p>
              <ul className="m-0 flex list-none flex-col gap-0.5 p-0 text-sm">
                {teacher.hours.map((h) => <li key={h.weekday_label + h.time}><b className="font-medium">{h.weekday_label}</b> {h.time} · {h.room}</li>)}
              </ul>
            </div>
            <div className="flex flex-wrap gap-2 text-sm">
              <a href={`mailto:${teacher.email}`} className="soft inline-flex min-h-10 items-center gap-1.5 rounded-[10px] bg-primary-soft px-3 font-medium text-primary-strong hover:bg-primary-tint"><Mail aria-hidden className="size-4" />Написать</a>
              {teacher.booking_resource && <Link to="/booking" className="soft inline-flex min-h-10 items-center rounded-[10px] px-3 font-medium text-primary hover:bg-primary-soft">Записаться на консультацию</Link>}
              {teacher.disciplines[0]?.id && <Link to={`/study/${teacher.disciplines[0].id}`} className="soft inline-flex min-h-10 items-center rounded-[10px] px-3 font-medium text-primary hover:bg-primary-soft">Мои баллы</Link>}
            </div>
            <p className="caption m-0 flex items-center gap-1"><Users aria-hidden className="size-3.5" />{teacher.groups.join(", ")}</p>
          </Card>
        ))}
      </div>
      <p className="caption m-0">Имена, почты и часы приёма вымышленные.</p>
    </div>
  );
}

/** Меню столовых (benchmark: TUM, RWTH, EPFL, MIT, Michigan, Stanford). */
export function CanteenPage() {
  const today = moscowDate();
  const [day, setDay] = useState(today);
  const [veg, setVeg] = useState(false);
  const menu = useQuery({ queryKey: ["canteen", day], queryFn: () => api<{ date: string; weekday: string; canteens: Canteen[]; note: string }>(`/api/canteen?date=${day}`) });
  const days = Array.from({ length: 6 }, (_, i) => addDays(today, i));
  return (
    <div className="flex flex-col gap-4">
      <PageHeader eyebrow="Меню на день, цены и часы пик" title="Столовые" />
      <div className="flex flex-wrap items-center gap-1.5">
        {days.map((value, index) => (
          <button key={value} aria-pressed={day === value} onClick={() => setDay(value)}
            className={cn("soft min-h-10 rounded-[10px] px-3.5 text-sm", day === value ? "bg-primary text-on-primary" : "bg-surface text-text-2 shadow-k-card hover:bg-primary-soft")}>
            {index === 0 ? "Сегодня" : index === 1 ? "Завтра" : new Intl.DateTimeFormat("ru", { weekday: "short", day: "numeric", timeZone: "Europe/Moscow" }).format(new Date(`${value}T12:00:00+03:00`))}
          </button>
        ))}
        <button aria-pressed={veg} onClick={() => setVeg(!veg)} className={cn("soft ml-auto inline-flex min-h-10 items-center gap-1.5 rounded-[10px] px-3.5 text-sm", veg ? "bg-[#e3f7ea] font-medium text-[#146c3a]" : "bg-surface text-text-2 shadow-k-card")}>
          <Leaf aria-hidden className="size-4" />Без мяса
        </button>
      </div>
      {menu.isPending && <Skeleton className="h-64" />}
      {menu.isError && <ErrorState message={menu.error.message} onRetry={() => menu.refetch()} />}
      <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-4 lg:grid-cols-2">
        {menu.data?.canteens.map((canteen) => (
          <Card key={canteen.id} aria-label={canteen.title}>
            <CardTitle meta={<UtensilsCrossed aria-hidden className="size-5 text-primary" />}>{canteen.title}</CardTitle>
            <p className="caption m-0">{canteen.place} · {canteen.hours} · больше всего людей {canteen.busy}</p>
            {!canteen.open ? <EmptyState>В этот день закрыто.</EmptyState> : (
              <>
                <p className="m-0 mt-3 rounded-[var(--radius-tile)] bg-primary-soft px-4 py-2.5 text-sm text-primary-strong">Комплексный обед (суп + горячее + гарнир) — <b>{canteen.lunch_price} ₽</b></p>
                {canteen.sections.map((section) => {
                  const items = section.items.filter((item) => !veg || item.vegetarian);
                  if (!items.length) return null;
                  return (
                    <div key={section.title} className="mt-3">
                      <p className="caption m-0 mb-1">{section.title}</p>
                      <ul className="m-0 flex list-none flex-col p-0">
                        {items.map((item) => (
                          <li key={item.name} className="flex justify-between gap-3 border-b border-line py-1.5 text-[15px] last:border-0">
                            <span>{item.name}{item.vegetarian && <Leaf aria-label="без мяса" className="ml-1 inline size-3.5 text-[#22a35a]" />}</span>
                            <span className="shrink-0 tabular-nums text-text-2">{item.price} ₽</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  );
                })}
              </>
            )}
          </Card>
        ))}
      </div>
      {menu.data && <p className="caption m-0">{menu.data.note}</p>}
    </div>
  );
}

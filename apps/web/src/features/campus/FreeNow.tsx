import { useQuery } from "@tanstack/react-query";
import { DoorOpen } from "lucide-react";
import { Link } from "react-router";
import { Card, CardTitle, EmptyState, ErrorState, MoreLink, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { timeLabel } from "../schedule/lessons";

export type Location = { room: string; building: string; building_title: string; address: string; floor: number; floor_text: string; wing: string; directions: string };
type FreeRoom = { id: string; title: string; kind: string; building: string; floor: number; capacity: number; free_until: string; minutes: number; next: string | null; location: Location | null };

export function duration(minutes: number): string {
  if (minutes < 60) return `${minutes} мин`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours} ч ${rest} мин` : `${hours} ч`;
}

export function useFreeNow() {
  return useQuery({ queryKey: ["free-now"], queryFn: () => api<{ at: string; items: FreeRoom[] }>("/api/campus/free-now"), refetchInterval: 60_000 });
}

/** «Свободно сейчас» (benchmark: Polimi free classrooms, TU Delft Spacefinder, InNoHassle). */
export function FreeNowList({ limit }: { limit?: number }) {
  const free = useFreeNow();
  if (free.isPending) return <Skeleton className="h-24" />;
  if (free.isError) return <ErrorState message={free.error.message} onRetry={() => free.refetch()} />;
  const items = limit ? free.data.items.slice(0, limit) : free.data.items;
  if (!items.length) return <EmptyState>Сейчас всё занято или корпуса закрыты. Загляните в бронирование на другое время.</EmptyState>;
  return (
    <ul className="m-0 flex list-none flex-col gap-2 p-0">
      {items.map((room) => (
        <li key={room.id}>
          <Link to="/booking" className="nudge soft flex items-center gap-3 rounded-[var(--radius-tile)] bg-surface-2 p-3.5 hover:bg-primary-soft">
            <span className="grid size-10 shrink-0 place-items-center rounded-[var(--radius-control)] bg-[#e3f7ea] text-[#146c3a]"><DoorOpen aria-hidden className="size-5" /></span>
            <span className="min-w-0 flex-1">
              <span className="block truncate font-medium">{room.title}</span>
              <span className="caption block truncate">{room.building}, {room.floor} этаж · до {room.capacity} чел.{room.location ? ` · ${room.location.wing}` : ""}</span>
              <span className="mt-0.5 block text-[13px] font-medium text-[#146c3a] sm:hidden">ещё {duration(room.minutes)}, до {timeLabel(room.free_until)}</span>
            </span>
            <span className="hidden shrink-0 text-right sm:block">
              <span className="block text-sm font-medium text-[#146c3a]">ещё {duration(room.minutes)}</span>
              <span className="caption block">до {timeLabel(room.free_until)}{room.next ? ` (${room.next})` : ""}</span>
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

export function FreeNowCard() {
  return (
    <Card aria-labelledby="free-heading">
      <CardTitle id="free-heading" meta={<MoreLink to="/campus?tab=free">Все</MoreLink>}>Свободно сейчас</CardTitle>
      <FreeNowList limit={3} />
    </Card>
  );
}

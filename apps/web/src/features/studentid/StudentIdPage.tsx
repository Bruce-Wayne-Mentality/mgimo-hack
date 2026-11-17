import { useQuery } from "@tanstack/react-query";
import { BadgeCheck, Clock, ShieldX, Smartphone } from "lucide-react";
import { useEffect, useState } from "react";
import { useParams } from "react-router";
import { BrandMark } from "@/components/Brand";
import { Card, ErrorState, PageHeader, Skeleton } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { PublicFrame } from "../documents/VerifyPage";

type Card = {
  full_name: string;
  record_book_no: string;
  card_no: string;
  group: string;
  course: number;
  faculty: string;
  program: string;
  status_label: string;
  valid_until: string;
  token: string;
  url: string;
  qr_svg: string;
  expires_at: number;
  server_time: number;
  lifetime: number;
};

function Ring({ left, total }: { left: number; total: number }) {
  const radius = 20;
  const length = 2 * Math.PI * radius;
  return (
    <svg viewBox="0 0 48 48" className="size-12 -rotate-90" aria-hidden>
      <circle cx="24" cy="24" r={radius} fill="none" stroke="var(--surface-2)" strokeWidth="4" />
      <circle cx="24" cy="24" r={radius} fill="none" stroke="var(--primary)" strokeWidth="4" strokeLinecap="round"
        strokeDasharray={length} strokeDashoffset={length * (1 - left / total)} style={{ transition: "stroke-dashoffset 1s linear" }} />
    </svg>
  );
}

export function StudentIdPage() {
  const card = useQuery({
    queryKey: ["student-id"],
    queryFn: async () => ({ ...(await api<Card>("/api/student-id")), received: Date.now() }),
    staleTime: 0,
    gcTime: 0,
  });
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const data = card.data;
  // Server-relative countdown: the phone clock may be off.
  const left = data ? Math.max(0, data.expires_at - data.server_time - Math.floor((now - data.received) / 1000)) : 0;
  useEffect(() => {
    // Ask for a fresh code 5 seconds before expiry (section 5, K3).
    if (data && left <= 5 && !card.isFetching) card.refetch();
  }, [left, data, card]);

  return (
    <div className="flex flex-col gap-4">
      <PageHeader eyebrow="Покажите охране на входе" title="Студенческий" />
      {card.isPending && <Skeleton className="h-[520px] max-w-[420px]" />}
      {card.isError && <ErrorState message={card.error.message} onRetry={() => card.refetch()} />}
      {data && (
        <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-4 lg:grid-cols-[420px_minmax(0,1fr)]">
          <section aria-label="Цифровой студенческий билет" className="overflow-hidden rounded-[28px] bg-surface shadow-k-float">
            <div className="flex items-center gap-3 bg-primary px-5 py-4 text-on-primary">
              <BrandMark className="size-10 bg-white text-primary" />
              <div className="min-w-0">
                <p className="m-0 text-[13px] opacity-80">Студенческий билет · концепт</p>
                <p className="m-0 truncate text-[17px] font-medium">{data.faculty}</p>
              </div>
            </div>
            <div className="flex flex-col items-center gap-4 p-5">
              {/* QR stays black on white in both themes so any scanner reads it. */}
              <div className="rounded-[20px] border-4 border-text bg-white p-3" style={{ colorScheme: "light" }}>
                <div className="size-[232px] [&_svg]:size-full" role="img" aria-label="QR-код студенческого, обновляется каждые 60 секунд"
                  dangerouslySetInnerHTML={{ __html: data.qr_svg }} />
              </div>
              <div className="flex items-center gap-3" aria-live="polite">
                <Ring left={left} total={data.lifetime} />
                <p className="m-0 text-sm text-text-2">Код обновится через <span className="font-medium text-text tabular-nums">{left} с</span><br />скриншот не сработает</p>
              </div>
              <div className="w-full rounded-[var(--radius-tile)] bg-surface-2 p-4">
                <p className="m-0 text-[20px] leading-tight font-medium tracking-[-0.01em]">{data.full_name}</p>
                <dl className="m-0 mt-3 grid grid-cols-2 gap-3 text-sm">
                  <div><dt className="caption">Группа</dt><dd className="m-0 font-medium">{data.group} · {data.course} курс</dd></div>
                  <div><dt className="caption">Билет</dt><dd className="m-0 font-medium">{data.card_no}</dd></div>
                  <div><dt className="caption">Статус</dt><dd className="m-0 font-medium text-[#146c3a]">{data.status_label}</dd></div>
                  <div><dt className="caption">Действителен до</dt><dd className="m-0 font-medium">{data.valid_until}</dd></div>
                </dl>
              </div>
            </div>
          </section>
          <Card>
            <h2 className="m-0 text-lg font-medium">Как это работает</h2>
            <ul className="mt-3 mb-0 flex list-none flex-col gap-3 p-0 text-[15px] text-text-2">
              <li className="flex gap-3"><Clock aria-hidden className="size-5 shrink-0 text-primary" />QR-код подписан сервером и живёт 60 секунд — пересланный скриншот быстро перестаёт работать.</li>
              <li className="flex gap-3"><BadgeCheck aria-hidden className="size-5 shrink-0 text-primary" />Охрана сканирует код камерой и видит только ФИО, группу и статус.</li>
              <li className="flex gap-3"><Smartphone aria-hidden className="size-5 shrink-0 text-primary" />Добавьте кабинет на экран «Домой» — студенческий будет открываться в одно касание.</li>
            </ul>
          </Card>
        </div>
      )}
    </div>
  );
}

type Check = { valid: boolean; expired: boolean; seconds_left: number; full_name: string | null; group: string | null; faculty: string | null; status_label: string };

export function IdCheckPage() {
  const { token = "" } = useParams();
  const check = useQuery({
    queryKey: ["id-check", token],
    queryFn: () => api<Check>(`/api/id-check/${encodeURIComponent(token)}`, { quiet401: true }),
    retry: false,
  });
  const ok = check.data?.valid;
  return (
    <PublicFrame title="Проверка студенческого">
      {check.isPending && <Skeleton className="h-48" />}
      {(check.isError || (check.data && !ok)) && (
        <Card className="flex gap-4 bg-danger-soft">
          <ShieldX aria-hidden className="size-10 shrink-0 text-danger" />
          <div>
            <p className="m-0 text-xl font-medium text-danger">
              {check.data?.expired ? "Код устарел" : check.error instanceof ApiError && check.error.status === 429 ? "Слишком много проверок" : "Не подтверждено"}
            </p>
            <p className="m-0 mt-1 text-text-2">
              {check.data?.expired ? "Возможно, это скриншот. Попросите студента открыть билет заново." : check.data ? `Статус: ${check.data.status_label}.` : "Код не распознан."}
            </p>
          </div>
        </Card>
      )}
      {check.data && ok && (
        <Card className={cn("flex gap-4 bg-[#e3f7ea]")}>
          <BadgeCheck aria-hidden className="size-10 shrink-0 text-[#146c3a]" />
          <div>
            <p className="m-0 text-xl font-medium text-[#146c3a]">Действующий студент</p>
            <p className="m-0 mt-2 text-[22px] leading-tight font-medium">{check.data.full_name}</p>
            <p className="m-0 mt-1 text-text-2">{check.data.group} · {check.data.faculty}</p>
            <p className="caption m-0 mt-2">Код действителен ещё {check.data.seconds_left} с</p>
          </div>
        </Card>
      )}
    </PublicFrame>
  );
}

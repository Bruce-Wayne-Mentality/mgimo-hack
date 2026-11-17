import { useQuery } from "@tanstack/react-query";
import { BadgeCheck, FileSearch, ShieldAlert, ShieldX } from "lucide-react";
import { useState, type ChangeEvent } from "react";
import { Link, useParams } from "react-router";
import { BrandMark, ConceptNotice } from "@/components/Brand";
import { Card, Skeleton } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { cn } from "@/lib/cn";

type Verified = {
  valid: boolean;
  status: "active" | "revoked";
  status_label: string;
  title: string;
  number: string;
  issued_at: string;
  holder: string;
  sha256: string;
  revoked_at: string | null;
};

async function sha256(file: File): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest)).map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function PublicFrame({ children, title }: { children: React.ReactNode; title: string }) {
  return (
    <div className="flex min-h-dvh flex-col bg-bg">
      <ConceptNotice />
      <main className="mx-auto flex w-full max-w-[560px] flex-1 flex-col gap-4 px-4 py-6">
        <Link to="/" className="flex items-center gap-2.5 self-start" aria-label="Цифровой деканат">
          <BrandMark className="size-9" />
          <span className="text-[16px] font-medium">Цифровой деканат</span>
        </Link>
        <h1 className="m-0 text-[28px] font-normal tracking-[-0.03em]">{title}</h1>
        {children}
      </main>
    </div>
  );
}

export function VerifyPage() {
  const { token = "" } = useParams();
  const check = useQuery({
    queryKey: ["verify", token],
    queryFn: () => api<Verified>(`/api/verify/${encodeURIComponent(token)}`, { quiet401: true }),
    retry: false,
  });
  const [fileCheck, setFileCheck] = useState<null | "same" | "different">(null);

  const onFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file || !check.data) return;
    setFileCheck((await sha256(file)) === check.data.sha256 ? "same" : "different");
  };

  return (
    <PublicFrame title="Проверка документа">
      {check.isPending && <Skeleton className="h-48" />}
      {check.isError && (
        <Card className="flex gap-4">
          <ShieldX aria-hidden className="size-8 shrink-0 text-danger" />
          <div>
            <p className="m-0 text-lg font-medium">{check.error instanceof ApiError && check.error.status === 429 ? "Слишком много проверок" : "Не найдено"}</p>
            <p className="m-0 mt-1 text-text-2">Документа с такой ссылкой нет или ссылка повреждена. Подделанная подпись выглядит так же.</p>
          </div>
        </Card>
      )}
      {check.data && (
        <>
          <Card className={cn("flex gap-4", check.data.status === "active" ? "bg-[#e3f7ea]" : "bg-[#fff4dc]")}>
            {check.data.status === "active" ? <BadgeCheck aria-hidden className="size-9 shrink-0 text-[#146c3a]" /> : <ShieldAlert aria-hidden className="size-9 shrink-0 text-[#8a5a00]" />}
            <div>
              <p className="m-0 text-lg font-medium">{check.data.status === "active" ? "Подлинный документ" : "Документ отозван"}</p>
              <p className="m-0 mt-1 text-text-2">Подпись проверена сервером кабинета. Статус: {check.data.status_label.toLowerCase()}.</p>
            </div>
          </Card>
          <Card>
            <dl className="m-0 grid gap-3 sm:grid-cols-2">
              {[
                ["Документ", check.data.title],
                ["Номер", check.data.number],
                ["Дата выдачи", new Intl.DateTimeFormat("ru", { dateStyle: "long", timeZone: "Europe/Moscow" }).format(new Date(check.data.issued_at))],
                ["Владелец", check.data.holder],
              ].map(([label, value]) => (
                <div key={label} className="rounded-[var(--radius-tile)] bg-surface-2 px-4 py-2.5">
                  <dt className="caption">{label}</dt>
                  <dd className="m-0 font-medium">{value}</dd>
                </div>
              ))}
            </dl>
            <p className="caption m-0 mt-3">Показываем минимум данных: только инициалы владельца.</p>
          </Card>
          <Card>
            <label className="flex cursor-pointer items-center gap-3">
              <FileSearch aria-hidden className="size-6 text-primary" />
              <span className="flex-1">
                <span className="block font-medium">Сверить файл</span>
                <span className="caption block">Выберите PDF — отпечаток SHA-256 посчитается прямо в браузере, файл никуда не отправляется.</span>
              </span>
              <input type="file" accept="application/pdf" onChange={onFile} className="sr-only" />
              <span className="soft rounded-[10px] bg-primary-soft px-3 py-2 text-sm font-medium text-primary-strong">Выбрать</span>
            </label>
            {fileCheck && (
              <p role="status" className={cn("m-0 mt-3 rounded-[var(--radius-tile)] px-4 py-3 text-sm", fileCheck === "same" ? "bg-[#e3f7ea] text-[#146c3a]" : "bg-danger-soft text-danger")}>
                {fileCheck === "same" ? "Файл совпадает с выданным: ни один байт не изменён." : "Файл отличается от выданного — его изменили или это другой документ."}
              </p>
            )}
          </Card>
        </>
      )}
      <p className="caption m-0">Концепт для конкурса. Демо-подпись HMAC не является квалифицированной электронной подписью и не имеет юридической силы.</p>
    </PublicFrame>
  );
}

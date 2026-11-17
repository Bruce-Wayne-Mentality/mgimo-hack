import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, ExternalLink, FileCheck2, ShieldOff } from "lucide-react";
import { useState } from "react";
import { Alert, Button, Card, CardTitle, Input, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { dateTimeLabel } from "../requests/api";

export type DocumentMeta = {
  id: string;
  title: string;
  number: string;
  issued_at: string;
  verify_url: string;
  sha256: string;
  size: number;
  revoked: boolean;
  revoke_reason: string | null;
};

export function DocumentCard({ requestId, staff = false }: { requestId: string; staff?: boolean }) {
  const client = useQueryClient();
  const meta = useQuery({
    queryKey: ["document", requestId],
    queryFn: () => api<DocumentMeta>(`/api/requests/${requestId}/document`),
  });
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState(false);
  const revoke = useMutation({
    mutationFn: () => api<DocumentMeta>(`/api/staff/requests/${requestId}/document/revoke`, { method: "POST", body: { reason } }),
    onSuccess: (data) => client.setQueryData(["document", requestId], data),
  });

  if (meta.isPending) return <Skeleton className="h-40" />;
  if (meta.isError) return <Alert>{meta.error.message}</Alert>;
  const doc = meta.data;
  const path = new URL(doc.verify_url).pathname;
  return (
    <Card aria-labelledby="doc-heading">
      <CardTitle id="doc-heading" meta={<FileCheck2 aria-hidden className="size-5 text-primary" />}>Документ</CardTitle>
      <div className="flex flex-col gap-3">
        <div className="rounded-[var(--radius-tile)] bg-surface-2 p-4">
          <p className="m-0 font-medium">{doc.title}</p>
          <p className="caption m-0 mt-0.5">№ {doc.number} · выдан {dateTimeLabel(doc.issued_at)} · PDF {Math.round(doc.size / 1024)} КБ</p>
          {doc.revoked && <p className="m-0 mt-2 text-sm text-danger">Отозван: {doc.revoke_reason}</p>}
        </div>
        <div className="flex flex-wrap gap-2">
          <a
            href={`/api/requests/${requestId}/document.pdf`}
            target="_blank"
            rel="noopener"
            className="soft inline-flex min-h-12 items-center gap-2 rounded-[var(--radius-control)] bg-primary px-5 text-[15px] font-medium text-on-primary hover:bg-primary-hover"
          >
            <Download aria-hidden className="size-4" /> Открыть PDF
          </a>
          <a href={path} target="_blank" rel="noopener" className="soft inline-flex min-h-12 items-center gap-2 rounded-[var(--radius-control)] bg-primary-soft px-4 text-[15px] font-medium text-primary-strong hover:bg-primary-tint">
            <ExternalLink aria-hidden className="size-4" /> Страница проверки
          </a>
        </div>
        <p className="caption m-0">
          Внутри — QR-код со ссылкой на публичную проверку подлинности и демо-подпись HMAC (не УКЭП). Кто угодно может убедиться, что документ выдан кабинетом и не изменён.
        </p>
        {staff && !doc.revoked && (
          confirm ? (
            <div className="flex flex-col gap-2 rounded-[var(--radius-tile)] bg-danger-soft p-4">
              <label htmlFor="revoke-reason" className="text-sm text-danger">Причина отзыва (увидит проверяющий)</label>
              <Input id="revoke-reason" value={reason} onChange={(event) => setReason(event.target.value)} className="bg-surface" />
              <div className="flex gap-2">
                <Button variant="danger" className="bg-surface" disabled={reason.trim().length < 3} loading={revoke.isPending} onClick={() => revoke.mutate()}>Отозвать</Button>
                <Button variant="ghost" onClick={() => setConfirm(false)}>Отмена</Button>
              </div>
              {revoke.isError && <Alert>{revoke.error.message}</Alert>}
            </div>
          ) : (
            <Button variant="ghost" className="self-start text-danger hover:bg-danger-soft" onClick={() => setConfirm(true)}>
              <ShieldOff aria-hidden className="size-4" /> Отозвать документ
            </Button>
          )
        )}
      </div>
    </Card>
  );
}

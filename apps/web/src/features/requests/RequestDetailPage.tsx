import { CheckCircle2, MessageCircleQuestion, Send } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router";
import { Alert, Button, Card, CardTitle, ErrorState, PageHeader, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { OPEN, dateLabel, dateTimeLabel, useRequest, useRequestAction, type RequestDetail } from "./api";
import { StatusChip, Tracker } from "./parts";

export function Conversation({ request, onSend, sending, error, canWrite, staff = false }: {
  request: RequestDetail;
  onSend: (body: string, internal: boolean) => Promise<unknown>;
  sending: boolean;
  error: string | null;
  canWrite: boolean;
  staff?: boolean;
}) {
  const [body, setBody] = useState("");
  const [internal, setInternal] = useState(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!body.trim()) return;
    await onSend(body.trim(), internal);
    setBody("");
  };
  return (
    <Card aria-labelledby="conversation-heading">
      <CardTitle id="conversation-heading">Переписка</CardTitle>
      <div className="flex flex-col gap-2.5">
        {request.comments.length === 0 && <p className="caption m-0">Сообщений пока нет.</p>}
        {request.comments.map((comment) => (
          <div
            key={comment.id}
            className={cn(
              "max-w-[85%] rounded-[var(--radius-tile)] px-4 py-3",
              comment.mine ? "self-end bg-primary text-on-primary" : "self-start bg-surface-2",
              comment.internal && "border border-dashed border-[#d9a400] bg-[#fff8e8] text-text",
            )}
          >
            <p className={cn("m-0 text-[12px]", comment.mine && !comment.internal ? "opacity-80" : "text-muted")}>
              {comment.internal ? "Внутренняя заметка · " : ""}{comment.author} · {dateTimeLabel(comment.at)}
            </p>
            <p className="m-0 mt-0.5 text-[15px] break-words whitespace-pre-wrap">{comment.body}</p>
          </div>
        ))}
      </div>
      {canWrite && (
        <form onSubmit={submit} className="mt-4 flex flex-col gap-2">
          <label htmlFor="comment" className="sr-only">Сообщение</label>
          <textarea
            id="comment"
            rows={3}
            maxLength={2000}
            value={body}
            onChange={(event) => setBody(event.target.value)}
            placeholder={staff ? "Сообщение студенту" : request.status === "needs_info" ? "Ответьте сотруднику — заявка вернётся в работу" : "Сообщение сотруднику деканата"}
            className="soft w-full rounded-[var(--radius-control)] border border-transparent bg-surface-2 px-4 py-3 text-base hover:bg-bg focus:border-primary focus:bg-surface focus:shadow-[var(--k-focus-ring)] focus:outline-none"
          />
          {error && <Alert>{error}</Alert>}
          <div className="flex flex-wrap items-center justify-between gap-2">
            {staff ? (
              <label className="flex min-h-11 cursor-pointer items-center gap-2 text-sm text-text-2">
                <input type="checkbox" checked={internal} onChange={(event) => setInternal(event.target.checked)} className="size-4 accent-[var(--primary)]" />
                Внутренняя заметка (студент не увидит)
              </label>
            ) : <span />}
            <Button type="submit" loading={sending} disabled={!body.trim()}>
              <Send className="size-4" aria-hidden /> Отправить
            </Button>
          </div>
        </form>
      )}
    </Card>
  );
}

export function RequestFacts({ request }: { request: RequestDetail }) {
  return (
    <Card aria-labelledby="facts-heading">
      <CardTitle id="facts-heading">Данные заявки</CardTitle>
      <dl className="m-0 grid gap-2 sm:grid-cols-2">
        {request.fields.map((field) => (
          <div key={field.name} className="rounded-[var(--radius-tile)] bg-surface-2 px-4 py-2.5">
            <dt className="caption">{field.label}</dt>
            <dd className="m-0 font-medium break-words">{field.value}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

export function RequestDetailPage() {
  const { id = "" } = useParams();
  const request = useRequest(id);
  const cancel = useRequestAction<void>(id, false, () => api<RequestDetail>(`/api/requests/${id}/cancel`, { method: "POST" }));
  const comment = useRequestAction<{ body: string }>(id, false, (input) =>
    api<RequestDetail>(`/api/requests/${id}/comments`, { method: "POST", body: input }),
  );
  const [confirming, setConfirming] = useState(false);

  if (request.isPending) return <Skeleton className="h-96" />;
  if (request.isError) {
    return (
      <div className="flex flex-col gap-4">
        <PageHeader eyebrow={<Link to="/requests" className="text-primary hover:underline">← Все заявки</Link>} title="Заявка" />
        <ErrorState message={request.error.message} onRetry={() => request.refetch()} />
      </div>
    );
  }
  const data = request.data;
  const open = OPEN.includes(data.status);
  const lastNote = [...data.events].reverse().find((event) => event.to === "needs_info" || event.to === "rejected")?.note;

  return (
    <div className="flex flex-col gap-4">
      <PageHeader eyebrow={<Link to="/requests" className="text-primary hover:underline">← Все заявки</Link>} title={data.type.title}>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <StatusChip status={data.status} label={data.status_label} />
          <span className="caption">{data.number} · подана {dateLabel(data.created_at)}</span>
        </div>
      </PageHeader>

      {data.status === "needs_info" && (
        <div role="alert" className="flex gap-3 rounded-[var(--radius-card)] bg-[#fff4dc] p-5 text-[#6b4600]">
          <MessageCircleQuestion className="size-6 shrink-0" aria-hidden />
          <div>
            <p className="m-0 font-medium">Нужен ваш ответ</p>
            {lastNote && <p className="m-0 mt-1 text-[15px]">{lastNote}</p>}
            <a href="#comment" className="mt-2 inline-block text-[15px] font-medium underline">Ответить</a>
          </div>
        </div>
      )}
      {data.status === "ready" && (
        <div role="status" className="flex gap-3 rounded-[var(--radius-card)] bg-[#e3f7ea] p-5 text-[#145c31]">
          <CheckCircle2 className="size-6 shrink-0" aria-hidden />
          <div>
            <p className="m-0 font-medium">Готово</p>
            {data.result_note && <p className="m-0 mt-1 text-[15px]">{data.result_note}</p>}
            <p className="m-0 mt-1 text-[13px] opacity-80">PDF с QR-кодом проверки появится здесь в следующем обновлении.</p>
          </div>
        </div>
      )}
      {data.status === "rejected" && lastNote && <Alert>Причина отказа: {lastNote}</Alert>}

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)]">
        <Card aria-labelledby="track-heading">
          <CardTitle id="track-heading">Ход заявки</CardTitle>
          <Tracker request={data} />
          {open && (
            <p className="caption mt-5 mb-0 rounded-[var(--radius-tile)] bg-surface-2 px-4 py-3">
              {new Date(data.due_at).getTime() < Date.now()
                ? `Заявка рассматривается дольше обычного (ориентир был ${dateTimeLabel(data.due_at)}). Деканат видит её в приоритете.`
                : `Обычно готово до ${dateTimeLabel(data.due_at)} — это ориентир по сроку типа заявки, не точное обещание.`}
            </p>
          )}
          {data.can_cancel && (
            <div className="mt-4">
              {confirming ? (
                <div className="flex flex-col gap-2 rounded-[var(--radius-tile)] bg-danger-soft p-4">
                  <p className="m-0 text-sm text-danger">Отменить заявку? Её нельзя будет вернуть.</p>
                  <div className="flex gap-2">
                    <Button variant="danger" className="bg-surface" loading={cancel.isPending} onClick={() => cancel.mutate()}>Да, отменить</Button>
                    <Button variant="ghost" onClick={() => setConfirming(false)}>Нет</Button>
                  </div>
                </div>
              ) : (
                <Button variant="ghost" className="text-danger hover:bg-danger-soft" onClick={() => setConfirming(true)}>Отменить заявку</Button>
              )}
              {cancel.isError && <Alert className="mt-2">{cancel.error.message}</Alert>}
            </div>
          )}
        </Card>
        <div className="flex flex-col gap-4">
          <RequestFacts request={data} />
          <Conversation
            request={data}
            canWrite={data.can_reply}
            sending={comment.isPending}
            error={comment.isError ? comment.error.message : null}
            onSend={(body) => comment.mutateAsync({ body })}
          />
        </div>
      </div>
    </div>
  );
}

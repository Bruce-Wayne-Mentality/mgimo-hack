import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { Alert, Button, Card, CardTitle, ErrorState, Input, PageHeader, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { Level, Risk } from "../study/api";
import { LEVEL_STYLE, LevelBadge } from "../study/parts";

type Group = { id: string; code: string; course: number; faculty: string; students: number; disciplines: { id: string; title: string; control_label: string }[] };
type Row = { student_id: string; full_name: string; record_book_no: string; scores: Record<string, number>; risk: Risk };
type Book = {
  discipline: { id: string; title: string; teacher: string; control_label: string };
  group: { code: string; course: number };
  checkpoints: { id: string; title: string; weight: number; max_score: number; due_on: string | null; critical: boolean }[];
  rows: Row[];
  counts: Record<Level, number>;
};

export function GradebookGroupsPage() {
  const groups = useQuery({ queryKey: ["gradebook"], queryFn: async () => (await api<{ items: Group[] }>("/api/staff/gradebook")).items });
  return (
    <div className="flex flex-col gap-4">
      <PageHeader eyebrow="Внесение баллов → пересчёт светофора → уведомление студенту" title="Журнал оценок" />
      {groups.isPending && <Skeleton className="h-40" />}
      {groups.isError && <ErrorState message={groups.error.message} onRetry={() => groups.refetch()} />}
      <div className="grid gap-4 lg:grid-cols-2">
        {groups.data?.map((group) => (
          <Card key={group.id} aria-label={group.code}>
            <CardTitle meta={<span className="caption">{group.course} курс · {group.students} студ.</span>}>{group.code}</CardTitle>
            <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
              {group.disciplines.map((discipline) => (
                <li key={discipline.id}>
                  <Link to={`/staff/grades/${discipline.id}`} className="nudge soft flex min-h-12 items-center justify-between gap-3 rounded-[var(--radius-tile)] bg-surface-2 px-4 hover:bg-primary-soft">
                    <span className="min-w-0"><span className="block truncate">{discipline.title}</span><span className="caption">{discipline.control_label}</span></span>
                    <ChevronRight aria-hidden className="size-5 shrink-0 text-muted" />
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
        ))}
      </div>
    </div>
  );
}

type Edit = { row: Row; checkpoint: Book["checkpoints"][number] };

export function GradebookPage() {
  const { id = "" } = useParams();
  const client = useQueryClient();
  const book = useQuery({ queryKey: ["gradebook", id], queryFn: () => api<Book>(`/api/staff/gradebook/${id}`) });
  const [edit, setEdit] = useState<Edit | null>(null);
  const [score, setScore] = useState("");
  const [reason, setReason] = useState("");
  const save = useMutation({
    mutationFn: (input: { student_id: string; checkpoint_id: string; score: number | null; reason: string | null }) =>
      api<Row>(`/api/staff/gradebook/${id}/grades`, { method: "PUT", body: input }),
    onSuccess: (row) => {
      client.setQueryData<Book>(["gradebook", id], (current) =>
        current ? { ...current, rows: current.rows.map((item) => (item.student_id === row.student_id ? row : item)) } : current,
      );
      setEdit(null);
    },
  });
  const open = (row: Row, checkpoint: Book["checkpoints"][number]) => {
    setEdit({ row, checkpoint });
    setScore(row.scores[checkpoint.id]?.toString() ?? "");
    setReason("");
    save.reset();
  };
  const data = book.data;
  const existing = edit ? edit.row.scores[edit.checkpoint.id] : undefined;
  const changing = existing !== undefined && score !== "" && Number(score) !== existing;

  return (
    <div className="flex flex-col gap-4">
      <PageHeader eyebrow={<Link to="/staff/grades" className="text-primary hover:underline">← Журнал оценок</Link>} title={data?.discipline.title ?? "Журнал"}>
        {data && <p className="caption m-0">{data.group.code} · {data.discipline.control_label} · {data.discipline.teacher}</p>}
      </PageHeader>
      {book.isPending && <Skeleton className="h-96" />}
      {book.isError && <ErrorState message={book.error.message} onRetry={() => book.refetch()} />}
      {data && (
        <>
          <div className="flex flex-wrap gap-2">
            {(["red", "yellow", "green", "grey"] as Level[]).filter((level) => data.counts[level]).map((level) => (
              <LevelBadge key={level} level={level} label={`${data.counts[level]} · ${{ red: "вне графика", yellow: "под риском", green: "в графике", grey: "нет данных" }[level]}`} />
            ))}
          </div>
          <Card className="overflow-hidden p-0 sm:p-0">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] border-collapse text-sm">
                <thead>
                  <tr className="text-left">
                    <th scope="col" className="sticky left-0 bg-surface px-4 py-3 font-medium text-text-2">Студент</th>
                    {data.checkpoints.map((cp) => (
                      <th key={cp.id} scope="col" className="px-2 py-3 text-center font-medium text-text-2">
                        <span className="block max-w-24 truncate" title={cp.title}>{cp.title}</span>
                        <span className="caption">из {cp.max_score} · {cp.weight}%</span>
                      </th>
                    ))}
                    <th scope="col" className="px-3 py-3 text-left font-medium text-text-2">Светофор</th>
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((row) => (
                    <tr key={row.student_id} className="border-t border-line">
                      <th scope="row" className="sticky left-0 bg-surface px-4 py-2 text-left font-normal">
                        <span className="block max-w-48 truncate">{row.full_name}</span>
                      </th>
                      {data.checkpoints.map((cp) => {
                        const value = row.scores[cp.id];
                        return (
                          <td key={cp.id} className="px-1 py-1 text-center">
                            <button
                              onClick={() => open(row, cp)}
                              aria-label={`${row.full_name}, ${cp.title}: ${value ?? "нет балла"}. Изменить`}
                              className={cn("soft min-h-9 w-14 rounded-[8px] tabular-nums hover:bg-primary-soft", value === undefined ? "text-muted" : "bg-surface-2 font-medium")}
                            >
                              {value ?? "—"}
                            </button>
                          </td>
                        );
                      })}
                      <td className="px-3 py-2">
                        <span className="inline-flex items-center gap-2">
                          <span aria-hidden className={cn("size-2.5 rounded-full", LEVEL_STYLE[row.risk.level].bar)} />
                          <span className="whitespace-nowrap">{row.risk.points} · {row.risk.label.toLowerCase()}</span>
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
      {edit && (
        <div role="dialog" aria-modal="true" aria-labelledby="grade-dialog" className="fixed inset-0 z-50 grid place-items-end bg-black/30 p-3 sm:place-items-center" onClick={() => setEdit(null)}>
          <form
            onClick={(event) => event.stopPropagation()}
            onSubmit={(event) => {
              event.preventDefault();
              save.mutate({ student_id: edit.row.student_id, checkpoint_id: edit.checkpoint.id, score: score === "" ? null : Number(score), reason: reason.trim() || null });
            }}
            className="flex w-full max-w-[420px] flex-col gap-3 rounded-[var(--radius-card)] bg-surface p-5 shadow-k-float"
          >
            <h2 id="grade-dialog" className="m-0 text-lg font-medium">{edit.checkpoint.title}</h2>
            <p className="caption m-0">{edit.row.full_name} · максимум {edit.checkpoint.max_score}</p>
            <Input type="number" inputMode="decimal" step="0.5" min={0} max={edit.checkpoint.max_score} value={score} autoFocus onChange={(event) => setScore(event.target.value)} aria-label="Балл" />
            {changing && <Input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Причина исправления (обязательно)" aria-label="Причина исправления" />}
            <p className="caption m-0">Студент получит уведомление; изменение попадёт в историю и журнал действий.</p>
            {save.isError && <Alert>{save.error.message}</Alert>}
            <div className="flex gap-2">
              <Button type="submit" loading={save.isPending} disabled={changing && !reason.trim()}>Сохранить</Button>
              <Button type="button" variant="ghost" onClick={() => setEdit(null)}>Отмена</Button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}

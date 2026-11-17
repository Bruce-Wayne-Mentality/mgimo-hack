import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

export type FieldKind = "text" | "textarea" | "int" | "select" | "date";

export type FormField = {
  name: string;
  label: string;
  kind: FieldKind;
  required?: boolean;
  options?: { value: string; label: string }[];
  max_length?: number;
  min?: number;
  max?: number;
  hint?: string;
};

export type RequestType = {
  code: string;
  title: string;
  description: string;
  result: string;
  sla_days: number;
  auto_issue: boolean;
  fields: FormField[];
};

export type RequestStatus = "submitted" | "in_review" | "needs_info" | "ready" | "rejected" | "cancelled";

export type RequestSummary = {
  id: string;
  number: string;
  type: { code: string; title: string };
  status: RequestStatus;
  status_label: string;
  created_at: string;
  updated_at: string;
  due_at: string;
  closed_at: string | null;
};

export type RequestDetail = Omit<RequestSummary, "type"> & {
  type: RequestType;
  fields: { name: string; label: string; value: string }[];
  events: { from: RequestStatus | null; to: RequestStatus; label: string; at: string; note: string | null; by_system: boolean }[];
  track: { status: RequestStatus; label: string; at: string | null }[];
  comments: { id: string; body: string; at: string; internal: boolean; mine: boolean; author: string; from_staff: boolean }[];
  result_note: string | null;
  can_cancel: boolean;
  can_reply: boolean;
  student?: { full_name: string; group: string; course: number; faculty: string; record_book_no: string; status: string };
  actions?: { to: RequestStatus; label: string; note_required: boolean }[];
  closed?: boolean;
};

export type StaffQueueItem = RequestSummary & { student: { full_name: string; group: string }; overdue: boolean };

export const OPEN: RequestStatus[] = ["submitted", "in_review", "needs_info"];

export function useRequestTypes() {
  return useQuery({
    queryKey: ["request-types"],
    queryFn: async () => (await api<{ items: RequestType[] }>("/api/request-types")).items,
    staleTime: 5 * 60_000,
  });
}

export function useMyRequests() {
  return useQuery({
    queryKey: ["requests", "list"],
    queryFn: async () => (await api<{ items: RequestSummary[] }>("/api/requests")).items,
    refetchInterval: 30_000,
  });
}

export function useRequest(id: string | undefined, staff = false) {
  return useQuery({
    queryKey: ["requests", staff ? "staff" : "own", id],
    queryFn: () => api<RequestDetail>(`${staff ? "/api/staff/requests" : "/api/requests"}/${id}`),
    enabled: !!id,
    refetchInterval: 20_000,
  });
}

/** Mutations that return a fresh RequestDetail and refresh lists and the bell. */
export function useRequestAction<T>(id: string, staff: boolean, call: (input: T) => Promise<RequestDetail>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: call,
    onSuccess: (data) => {
      client.setQueryData(["requests", staff ? "staff" : "own", id], data);
      client.invalidateQueries({ queryKey: ["requests", "list"] });
      client.invalidateQueries({ queryKey: ["staff-queue"] });
      client.invalidateQueries({ queryKey: ["notifications"] });
    },
  });
}

export function useStaffQueue(filter: { status?: string; type?: string; overdue?: boolean }) {
  return useQuery({
    queryKey: ["staff-queue", filter],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (filter.status) params.set("status", filter.status);
      if (filter.type) params.set("type", filter.type);
      if (filter.overdue) params.set("overdue", "true");
      return (await api<{ items: StaffQueueItem[] }>(`/api/staff/requests?${params}`)).items;
    },
    refetchInterval: 30_000,
  });
}

export function slaLabel(days: number): string {
  if (days === 0) return "сразу";
  const word = days === 1 ? "рабочий день" : days < 5 ? "рабочих дня" : "рабочих дней";
  return `до ${days} ${word}`;
}

export function dateTimeLabel(value: string): string {
  return new Intl.DateTimeFormat("ru", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Moscow" }).format(new Date(value));
}

export function dateLabel(value: string): string {
  return new Intl.DateTimeFormat("ru", { day: "numeric", month: "long", timeZone: "Europe/Moscow" }).format(new Date(value));
}

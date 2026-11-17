import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export type ComplaintStatus = "MODERATION" | "NEW" | "IN_PROGRESS" | "NEED_INFO" | "ANSWERED" | "ESCALATED" | "CLOSED" | "WITHDRAWN" | "RETURNED";

export type ComplaintBase = {
  id: string;
  number: string;
  type: string;
  type_label: string;
  category: string;
  category_label: string;
  category_source: string;
  link_label: string | null;
  title: string;
  title_source: string;
  privacy: "named" | "confidential" | "anonymous";
  privacy_label: string;
  status: ComplaintStatus;
  status_label: string;
  department: string;
  priority: number;
  desired_outcome: string | null;
  desired_label: string | null;
  created_at: string;
  updated_at: string;
  take_due_at: string;
  answer_due_at: string;
  closed_at: string | null;
  overdue: boolean;
  escalated: boolean;
  resolved_by_student: boolean | null;
  waiting_for_me?: boolean;
};

export type ComplaintMessage = { id: string; from_role: string; author: string | null; kind: string; body: string | null; at: string };
export type ComplaintEvent = { to: ComplaintStatus; label: string; at: string; by: string };

export type ComplaintDetail = ComplaintBase & {
  text: string | null;
  messages: ComplaintMessage[];
  events: ComplaintEvent[];
  return_comment: string | null;
  can_withdraw: boolean;
  can_message: boolean;
  can_feedback: boolean;
  can_escalate: boolean;
};

export type StaffComplaint = ComplaintBase & {
  author: string;
  flags: string[];
  summary: string | null;
  moderation_reason: string | null;
};

export type StaffDetail = ComplaintDetail & {
  author: string;
  role: "curator" | "executor";
  summary: string | null;
  ai: Record<string, unknown>;
  flags: string[];
  moderation_reason: string | null;
  moderation_reason_label: string | null;
  stage2_state: string;
  assignee: string | null;
  moderation: { stage: number; verdict: string; scores: Record<string, unknown>; flags: string[]; models: Record<string, string>; latency_ms: number; at: string }[];
  actions: { action: string; label: string; text?: boolean }[];
  assignees: { id: string; name: string }[];
};

export type SubmitResult =
  | { verdict: "ACCEPT" | "ESCALATE"; complaint: ComplaintDetail; help?: string }
  | { verdict: "REJECT_OBSCENE"; session_id: string; attempts: number; spans: { start: number; end: number }[]; message: string }
  | { verdict: "ASK_DETAILS"; session_id: string; attempts: number; missing: { code: string; question: string }[]; message: string; can_manual_review: boolean };

export const TYPES = [
  { value: "unfair", label: "Несправедливость" },
  { value: "problem", label: "Проблема" },
  { value: "suggestion", label: "Предложение" },
  { value: "thanks", label: "Благодарность" },
] as const;

export const CATEGORIES = [
  { value: "grades", label: "Оценки и аттестация" },
  { value: "schedule", label: "Расписание" },
  { value: "teacher_conduct", label: "Поведение преподавателя" },
  { value: "dean_office", label: "Деканат" },
  { value: "documents", label: "Документы" },
  { value: "scholarship_payment", label: "Стипендия и оплата" },
  { value: "dormitory", label: "Общежитие" },
  { value: "infrastructure", label: "Инфраструктура" },
  { value: "other", label: "Другое" },
] as const;

export const DESIRED = [
  { value: "review", label: "Пересмотр решения" },
  { value: "explain", label: "Объяснение" },
  { value: "fix", label: "Исправить проблему" },
  { value: "record", label: "Просто зафиксировать" },
] as const;

export const PRIVACY = [
  { value: "named", label: "От своего имени", text: "ФИО и группу видят куратор и исполнитель — так жалобу решают быстрее." },
  { value: "confidential", label: "Конфиденциально", text: "Имя видит только куратор кнопки; исполнитель видит «Студент #7F3A»." },
  { value: "anonymous", label: "Анонимно", text: "Имя не видит никто из рассматривающих. По анонимным обращениям нельзя уточнить детали лично." },
] as const;

export const STATUS_TONE: Record<ComplaintStatus, string> = {
  MODERATION: "bg-[#fff4dc] text-[#8a5a00]",
  NEW: "bg-primary-soft text-primary-strong",
  IN_PROGRESS: "bg-primary-soft text-primary-strong",
  NEED_INFO: "bg-[#fff4dc] text-[#8a5a00]",
  ANSWERED: "bg-[#e3f7ea] text-[#146c3a]",
  ESCALATED: "bg-[#efe9ff] text-[#5b3cc4]",
  CLOSED: "bg-surface-2 text-text-2",
  WITHDRAWN: "bg-surface-2 text-text-2",
  RETURNED: "bg-[#fdecec] text-[#b42318]",
};

export function useMyComplaints(enabled = true) {
  return useQuery({
    queryKey: ["complaints"],
    queryFn: async () => (await api<{ items: ComplaintBase[] }>("/api/complaints")).items,
    enabled,
    refetchInterval: 30_000,
  });
}

// A light, offline hint while typing (the server decides). Short list of roots only.
const HINT = /(х[уy][йеёияю]|п[иi]зд|(^|\s)[её]б[аул]|бля|муда[кч]|пид[оа]р|гандон|залуп|шлюх)/i;
export function hasObscenityHint(text: string): boolean {
  return HINT.test(text.toLowerCase());
}

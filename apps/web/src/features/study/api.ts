import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export type Level = "red" | "yellow" | "green" | "grey";

export type Risk = {
  level: Level;
  label: string;
  points: number;
  due_weight: number;
  pace: number | null;
  reachable: number;
  reasons: { code: string; text: string }[];
  missed: string[];
  attendance: number | null;
};

export type StudyAction = { kind: string; label: string; link: string };

export type DisciplineSummary = {
  id: string;
  code: string;
  title: string;
  teacher: string;
  control_form: string;
  control_label: string;
  credits: number;
  threshold: number;
  risk: Risk;
  expected_by_today: number;
  next_checkpoint: { title: string; due_on: string; weight: number; days_left: number } | null;
  final_at: string | null;
  final_room: string | null;
  actions: StudyAction[];
};

export type Checkpoint = {
  id: string;
  title: string;
  weight: number;
  max_score: number;
  due_on: string | null;
  critical: boolean;
  is_final: boolean;
  score: number | null;
  points: number | null;
  state: "graded" | "missed" | "waiting" | "upcoming";
};

export type DisciplineDetail = DisciplineSummary & {
  checkpoints: Checkpoint[];
  attendance: { attended: number; total: number } | null;
  history: { checkpoint: string; old: number | null; new: number | null; by: string; at: string; reason: string | null }[];
  trend: { level: Level; at: string; points: number }[];
  remaining_weight: number;
  need_for_admission: number | null;
  need_for_excellent: number | null;
};

export type StudyOverview = {
  semester: string | null;
  today: string;
  summary: { total: number; on_track: number; with_data: number; counts: Record<Level, number>; headline: string };
  disciplines: DisciplineSummary[];
  gpa: number | null;
  dynamics: { no: number; label: string; average: number | null; items: { title: string; control_label: string; credits: number; mark: number | null }[] }[];
  session: { discipline_id: string; title: string; control_label: string; at: string; room: string | null; admission: string; level: Level }[];
  rules: string[];
};

export type WhatIf = { total: number; risk: Risk; passes: boolean; mark: string };

export type Nudge = {
  id: string;
  rule: string;
  rule_label: string;
  title: string;
  text: string;
  action: { label?: string; link?: string };
  state: string;
  created_at: string;
};

export function useStudy(enabled = true) {
  return useQuery({ queryKey: ["study"], queryFn: () => api<StudyOverview>("/api/study"), enabled, staleTime: 30_000 });
}

export function useDiscipline(id: string | undefined) {
  return useQuery({
    queryKey: ["study", "discipline", id],
    queryFn: () => api<DisciplineDetail>(`/api/study/disciplines/${id}`),
    enabled: !!id,
  });
}

export function useNudges(enabled = true) {
  return useQuery({
    queryKey: ["nudges"],
    queryFn: async () => (await api<{ items: Nudge[] }>("/api/nudges")).items,
    enabled,
    staleTime: 60_000,
  });
}

export function shortDate(value: string): string {
  return new Intl.DateTimeFormat("ru", { day: "numeric", month: "short", timeZone: "Europe/Moscow" }).format(new Date(value));
}

export function daysLeftLabel(days: number): string {
  if (days === 0) return "сегодня";
  if (days === 1) return "завтра";
  const mod10 = days % 10;
  const mod100 = days % 100;
  const word = mod10 === 1 && mod100 !== 11 ? "день" : mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14) ? "дня" : "дней";
  return `через ${days} ${word}`;
}

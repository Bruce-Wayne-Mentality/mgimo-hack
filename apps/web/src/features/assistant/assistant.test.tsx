import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GapCard, type Gap } from "../staff/KbGapsPage";
import { AssistantPage } from "./AssistantPage";
import { KbBadge, SourceCards, type Source } from "./Sources";

const SCHOLARSHIP: Source = {
  id: "04", doc_id: "04", title: "Положение о стипендиальном обеспечении обучающихся", section_path: "Раздел 2 › Таблица 1",
  page: 1, chunk_id: "c-1", excerpt: "Вид стипендии: ГАС; Условие: только «отлично»; Размер в месяц: 5400 руб.",
};

function wrap(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  );
}

let replies: Record<string, unknown>;
const calls: { url: string; body?: unknown }[] = [];

beforeEach(() => {
  calls.length = 0;
  sessionStorage.clear();
  Element.prototype.scrollIntoView = vi.fn(); // jsdom has no layout
  replies = {
    "GET /api/assistant": { disclaimer: "Это ИИ.", suggestions: [], engine: "rules", engine_label: "Демо" },
  };
  vi.stubGlobal("fetch", vi.fn(async (input: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${input.split("?")[0]}`;
    calls.push({ url: input, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const body = replies[key];
    if (body instanceof Error) throw body;
    return new Response(JSON.stringify(body ?? {}), { status: body === undefined ? 404 : 200, headers: { "Content-Type": "application/json" } });
  }));
});

afterEach(() => vi.unstubAllGlobals());

describe("source cards", () => {
  it("shows document, clause and page; a tap opens the exact quote", async () => {
    render(wrap(<SourceCards sources={[SCHOLARSHIP]} />));
    expect(screen.getByText("Положение о стипендиальном обеспечении обучающихся")).toBeInTheDocument();
    expect(screen.getByText("Раздел 2 › Таблица 1 · стр. 1")).toBeInTheDocument();
    expect(screen.queryByText(/5400 руб\./)).not.toBeInTheDocument();
    const card = screen.getByRole("button", { expanded: false });
    await userEvent.click(card);
    expect(screen.getByText(/Размер в месяц: 5400 руб\./)).toBeInTheDocument();
    expect(card).toHaveAttribute("aria-expanded", "true");
  });

  it("keeps the old one-line source for the built-in rules", () => {
    render(wrap(<SourceCards sources={[{ id: "scholarship", title: "Стипендия" }]} />));
    expect(screen.getByText(/Источник: Стипендия/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("marks quotes and refusals", () => {
    const { rerender } = render(wrap(<KbBadge kind="kb_extract" />));
    expect(screen.getByText("Точная цитата из правил")).toBeInTheDocument();
    rerender(wrap(<KbBadge kind="kb_refusal" />));
    expect(screen.getByText("В правилах этого нет")).toBeInTheDocument();
    rerender(wrap(<KbBadge kind="me" />));
    expect(screen.queryByText(/правил/)).not.toBeInTheDocument();
  });
});

describe("assistant states", () => {
  it("kb_extract: the quote with its source card", async () => {
    replies["POST /api/assistant/ask"] = {
      text: "Точная цитата из правил:\nВид стипендии: ГАС; Размер в месяц: 5400 руб.", kind: "kb_extract",
      sources: [SCHOLARSHIP], actions: [], engine: "rag",
    };
    render(wrap(<AssistantPage />));
    await userEvent.type(screen.getByLabelText("Вопрос ассистенту"), "Какая стипендия у отличника?{Enter}");
    expect(await screen.findByText("Точная цитата из правил")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Источники ответа" })).toBeInTheDocument();
  });

  it("kb_refusal: a calm refusal and «Спросить деканат» with the question", async () => {
    replies["POST /api/assistant/ask"] = {
      text: "В правилах ответа нет. Можно задать вопрос деканату — сотрудник ответит в «Заявках».", kind: "kb_refusal", sources: [],
      actions: [{ kind: "handoff", label: "Спросить деканат", summary: "Сколько стоит парковка?" }], engine: "rag",
    };
    replies["POST /api/assistant/handoff"] = { id: "r1", number: "ДК-2026-000123", link: "/requests/r1" };
    render(wrap(<AssistantPage />));
    await userEvent.type(screen.getByLabelText("Вопрос ассистенту"), "Сколько стоит парковка?{Enter}");
    expect(await screen.findByText("В правилах этого нет")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Спросить деканат" }));
    await waitFor(() => expect(calls.some((c) => c.url === "/api/assistant/handoff")).toBe(true));
    const handoff = calls.find((c) => c.url === "/api/assistant/handoff");
    expect((handoff?.body as { summary: string }).summary).toBe("Сколько стоит парковка?");
  });

  it("network error: a clear message and a retry", async () => {
    replies["POST /api/assistant/ask"] = new TypeError("Failed to fetch");
    render(wrap(<AssistantPage />));
    await userEvent.type(screen.getByLabelText("Вопрос ассистенту"), "Какая стипендия?{Enter}");
    expect(await screen.findByText(/Ответ не пришёл/)).toBeInTheDocument();
    replies["POST /api/assistant/ask"] = { text: "Ответ", kind: "rule", sources: [], actions: [] };
    await userEvent.click(screen.getByRole("button", { name: "Повторить" }));
    expect(await screen.findByText("Ответ")).toBeInTheDocument();
  });
});

describe("staff gaps", () => {
  const gap: Gap = {
    id: "g1", question: "Сколько стоит парковка?", status: "open", top_score: 3.8, nearest: null,
    answer_text: null, answered_by: null, created_at: "2026-11-17T10:00:00Z", answered_at: null,
  };

  it("publishes an answer", async () => {
    replies["POST /api/staff/kb/gaps/g1/answer"] = { id: "g1", status: "answered", published: true };
    render(wrap(<GapCard gap={gap} />));
    const publish = screen.getByRole("button", { name: /Опубликовать/ });
    expect(publish).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Ответ"), "Парковка для студентов бесплатная.");
    await userEvent.click(publish);
    await waitFor(() => expect(calls.some((c) => c.url === "/api/staff/kb/gaps/g1/answer")).toBe(true));
    expect(calls.find((c) => c.url === "/api/staff/kb/gaps/g1/answer")?.body).toEqual({ answer_text: "Парковка для студентов бесплатная.", publish: true });
  });
});

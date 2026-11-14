import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { routes } from "@/app/routes";
import type { RequestDetail, RequestType } from "./api";

const ANNA = { id: "1", login: "student.anna", role: "student", role_label: "Студент", display_name: "Анна Сергеевна Миронова" };
const MIL: RequestType = {
  code: "CERT_MIL", title: "Справка для военкомата", description: "Для отсрочки.", result: "PDF после одобрения", sla_days: 2, auto_issue: false,
  fields: [
    { name: "purpose", label: "Цель", kind: "select", required: true, options: [{ value: "deferment", label: "Отсрочка" }, { value: "registration", label: "Учёт" }] },
    { name: "office", label: "Военкомат", kind: "text", required: true, max_length: 200 },
  ],
};

function detail(overrides: Partial<RequestDetail> = {}): RequestDetail {
  return {
    id: "r1", number: "ДК-2026-000007", type: MIL, status: "submitted", status_label: "Принята",
    created_at: "2026-11-18T08:00:00Z", updated_at: "2026-11-18T08:00:00Z", due_at: "2026-11-20T15:00:00Z", closed_at: null,
    fields: [{ name: "purpose", label: "Цель", value: "Отсрочка" }],
    events: [{ from: null, to: "submitted", label: "Принята", at: "2026-11-18T08:00:00Z", note: null, by_system: false }],
    track: [
      { status: "submitted", label: "Принята", at: "2026-11-18T08:00:00Z" },
      { status: "in_review", label: "В работе", at: null },
      { status: "ready", label: "Готова", at: null },
    ],
    comments: [], result_note: null, can_cancel: true, can_reply: true,
    ...overrides,
  };
}

let calls: { method: string; path: string; headers: Record<string, string>; body: unknown }[];
let replies: Record<string, (body: unknown) => { status: number; body?: unknown }>;

beforeEach(() => {
  calls = [];
  localStorage.clear();
  replies = {
    "GET /api/auth/me": () => ({ status: 200, body: { user: ANNA, csrf_token: "csrf" } }),
    "GET /api/request-types": () => ({ status: 200, body: { items: [MIL] } }),
    "GET /api/me/profile": () => ({ status: 200, body: { kind: "student", full_name: "Анна Сергеевна Миронова", group: "ЭК-25-1", course: 2, record_book_no: "DEMO-250114" } }),
    "GET /api/me/notifications": () => ({ status: 200, body: { items: [], unread_count: 0, next_before: null } }),
    "GET /api/requests/r1": () => ({ status: 200, body: detail() }),
  };
  vi.stubGlobal("fetch", vi.fn(async (input: string, init?: RequestInit) => {
    const url = new URL(input, "https://dekanat.test");
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ method, path: url.pathname, headers: (init?.headers ?? {}) as Record<string, string>, body });
    const reply = replies[`${method} ${url.pathname}`]?.(body) ?? { status: 404, body: { error: { code: "not_found", message: "Нет" } } };
    return new Response(reply.body === undefined ? null : JSON.stringify(reply.body), { status: reply.status, headers: { "Content-Type": "application/json" } });
  }));
});

afterEach(() => vi.unstubAllGlobals());

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><RouterProvider router={router} /></QueryClientProvider>);
  return router;
}

describe("new request in three steps", () => {
  it("validates, reviews and sends once with an idempotency key", async () => {
    let created = 0;
    replies["POST /api/requests"] = () => {
      created += 1;
      return { status: 201, body: detail() };
    };
    const router = renderAt("/requests/new");
    await userEvent.click(await screen.findByRole("button", { name: /Справка для военкомата/ }));

    await userEvent.click(screen.getByRole("button", { name: "Дальше" }));
    expect(screen.getAllByText("Заполните поле.")).toHaveLength(2);

    await userEvent.click(screen.getByRole("radio", { name: "Отсрочка" }));
    await userEvent.type(screen.getByLabelText("Военкомат"), "Военкомат №1");
    expect(JSON.parse(localStorage.getItem("dekanat:request-draft")!).values.office).toBe("Военкомат №1");
    await userEvent.click(screen.getByRole("button", { name: "Дальше" }));

    expect(await screen.findByText("Проверьте заявку")).toBeInTheDocument();
    expect(screen.getByText("Военкомат №1")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Отправить заявку" }));

    await waitFor(() => expect(router.state.location.pathname).toBe("/requests/r1"));
    const post = calls.find((call) => call.method === "POST" && call.path === "/api/requests")!;
    expect(post.body).toEqual({ type_code: "CERT_MIL", payload: { purpose: "deferment", office: "Военкомат №1" } });
    expect(post.headers["Idempotency-Key"]).toMatch(/^[0-9a-f-]{36}$/);
    expect(post.headers["X-CSRF-Token"]).toBe("csrf");
    expect(created).toBe(1);
    expect(localStorage.getItem("dekanat:request-draft")).toBeNull();
  });
});

describe("request tracker", () => {
  it("shows the waiting step and asks for an answer in needs_info", async () => {
    replies["GET /api/requests/r1"] = () => ({
      status: 200,
      body: detail({
        status: "needs_info", status_label: "Нужны данные",
        events: [
          { from: null, to: "submitted", label: "Принята", at: "2026-11-18T08:00:00Z", note: null, by_system: false },
          { from: "submitted", to: "in_review", label: "В работе", at: "2026-11-18T09:00:00Z", note: null, by_system: false },
          { from: "in_review", to: "needs_info", label: "Нужны данные", at: "2026-11-18T10:00:00Z", note: "Уточните адрес военкомата", by_system: false },
        ],
        track: [
          { status: "submitted", label: "Принята", at: "2026-11-18T08:00:00Z" },
          { status: "in_review", label: "В работе", at: "2026-11-18T09:00:00Z" },
          { status: "ready", label: "Готова", at: null },
        ],
      }),
    });
    renderAt("/requests/r1");
    const banner = await screen.findByRole("alert");
    expect(within(banner).getByText("Нужен ваш ответ")).toBeInTheDocument();
    expect(within(banner).getByText("Уточните адрес военкомата")).toBeInTheDocument();
    const tracker = screen.getByRole("list", { name: "Ход заявки" });
    expect(within(tracker).getByText(/ждём ваш ответ/)).toBeInTheDocument();
  });

  it("asks for confirmation before cancelling", async () => {
    replies["POST /api/requests/r1/cancel"] = () => ({ status: 200, body: detail({ status: "cancelled", status_label: "Отменена", can_cancel: false, can_reply: false }) });
    renderAt("/requests/r1");
    await userEvent.click(await screen.findByRole("button", { name: "Отменить заявку" }));
    expect(calls.some((call) => call.path.endsWith("/cancel"))).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "Да, отменить" }));
    await waitFor(() => expect(calls.some((call) => call.method === "POST" && call.path === "/api/requests/r1/cancel")).toBe(true));
    expect((await screen.findAllByText("Отменена")).length).toBeGreaterThan(0);
  });
});

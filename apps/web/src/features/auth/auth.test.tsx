import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createQueryClient } from "@/app/App";
import { routes } from "@/app/routes";
import { safeNext } from "@/lib/auth";

type Reply = { status: number; body?: unknown; headers?: Record<string, string> };
const ANNA = { id: "1", login: "student.anna", role: "student", role_label: "Студент", display_name: "Анна Сергеевна Миронова" };

function json({ status, body, headers = {} }: Reply): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

let handlers: Record<string, (init?: RequestInit) => Reply>;
const calls: { url: string; init?: RequestInit }[] = [];

beforeEach(() => {
  calls.length = 0;
  handlers = {
    "GET /api/auth/me": () => ({ status: 401, body: { error: { code: "unauthorized", message: "Войдите" } } }),
    "GET /api/auth/demo-accounts": () => ({
      status: 200,
      body: { accounts: [{ login: "student.anna", password: "Demo-Anna-2026", description: "Студент А · 2 курс" }] },
    }),
    "GET /api/me/schedule": () => ({ status: 200, body: { start: "", finish: "", timezone: "Europe/Moscow", lessons: [] } }),
    "GET /api/me/notifications": () => ({ status: 200, body: { items: [], unread_count: 0, next_before: null } }),
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const url = new URL(input, "https://dekanat.test");
      calls.push({ url: url.pathname + url.search, init });
      const handler = handlers[`${init?.method ?? "GET"} ${url.pathname}`];
      return json(handler ? handler(init) : { status: 404, body: { error: { code: "not_found", message: "Нет" } } });
    }),
  );
});

afterEach(() => vi.unstubAllGlobals());

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <QueryClientProvider client={createQueryClient()}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

describe("access gate", () => {
  it("sends a visitor without a session from any screen to the login page", async () => {
    const router = renderAt("/schedule?week=2");
    expect(await screen.findByRole("heading", { name: "Вход" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/login");
    expect(router.state.location.search).toBe(`?next=${encodeURIComponent("/schedule?week=2")}`);
    expect(screen.queryByText("Расписание")).not.toBeInTheDocument();
  });

  it("opens the app for a signed-in student", async () => {
    handlers["GET /api/auth/me"] = () => ({ status: 200, body: { user: ANNA, csrf_token: "csrf-1" } });
    renderAt("/");
    expect(await screen.findByRole("heading", { name: /Анна$/ })).toBeInTheDocument();
    expect(screen.getAllByRole("navigation", { name: "Основное меню" }).length).toBeGreaterThan(0);
  });

  it("keeps staff out of student-only screens", async () => {
    handlers["GET /api/auth/me"] = () => ({
      status: 200,
      body: { user: { ...ANNA, role: "staff", role_label: "Сотрудник деканата", display_name: "Ольга Демченко" }, csrf_token: "c" },
    });
    const router = renderAt("/schedule");
    await waitFor(() => expect(router.state.location.pathname).toBe("/"));
  });
});

describe("login screen", () => {
  it("validates empty fields without calling the server", async () => {
    renderAt("/login");
    await userEvent.click(await screen.findByRole("button", { name: "Войти" }));
    expect(await screen.findByText("Введите логин.")).toBeInTheDocument();
    expect(screen.getByText("Введите пароль.")).toBeInTheDocument();
    expect(calls.some((call) => call.url === "/api/auth/login")).toBe(false);
  });

  it("shows the server message for wrong credentials and the lock-out", async () => {
    handlers["POST /api/auth/login"] = () => ({ status: 401, body: { error: { code: "invalid_credentials", message: "Неверный логин или пароль." } } });
    renderAt("/login");
    await userEvent.type(await screen.findByLabelText("Логин"), "student.anna");
    await userEvent.type(screen.getByLabelText("Пароль"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: "Войти" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Неверный логин или пароль.");

    handlers["POST /api/auth/login"] = () => ({
      status: 429,
      body: { error: { code: "too_many_attempts", message: "Слишком много неудачных попыток. Повторите вход через 15 мин." } },
      headers: { "Retry-After": "900" },
    });
    await userEvent.click(screen.getByRole("button", { name: "Войти" }));
    expect(await screen.findByText(/через 15 мин/)).toBeInTheDocument();
  });

  it("fills a demo account, signs in and returns to the requested screen", async () => {
    handlers["POST /api/auth/login"] = (init) => {
      expect(JSON.parse(String(init?.body))).toEqual({ login: "student.anna", password: "Demo-Anna-2026", remember: true });
      return { status: 200, body: { user: ANNA, csrf_token: "csrf-1" } };
    };
    const router = renderAt("/login?next=%2Fprofile");
    await userEvent.click(await screen.findByRole("button", { name: /Студент А/ }));
    expect(screen.getByLabelText("Логин")).toHaveValue("student.anna");
    await userEvent.click(screen.getByLabelText(/Запомнить меня/));
    await userEvent.click(screen.getByRole("button", { name: "Войти" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/profile"));
  });

  it("toggles password visibility", async () => {
    renderAt("/login");
    const password = await screen.findByLabelText("Пароль");
    expect(password).toHaveAttribute("type", "password");
    await userEvent.click(screen.getByRole("button", { name: "Показать пароль" }));
    expect(password).toHaveAttribute("type", "text");
  });

  it("always shows the concept notice", async () => {
    renderAt("/login");
    expect(await screen.findByText("Концепт для конкурса, не официальный сервис вуза")).toBeInTheDocument();
  });
});

describe("CSRF and redirects", () => {
  it("sends the CSRF token on changing requests", async () => {
    handlers["GET /api/auth/me"] = () => ({ status: 200, body: { user: ANNA, csrf_token: "csrf-xyz" } });
    handlers["POST /api/auth/logout"] = () => ({ status: 204 });
    renderAt("/profile");
    await userEvent.click(await screen.findByRole("button", { name: "Выйти" }));
    await waitFor(() => expect(calls.some((call) => call.url === "/api/auth/logout")).toBe(true));
    const logout = calls.find((call) => call.url === "/api/auth/logout")!;
    expect((logout.init?.headers as Record<string, string>)["X-CSRF-Token"]).toBe("csrf-xyz");
    expect(await screen.findByRole("heading", { name: "Вход" })).toBeInTheDocument();
  });

  it("accepts only local next paths", () => {
    expect(safeNext("/schedule?week=2")).toBe("/schedule?week=2");
    for (const hostile of [null, "", "https://evil.example", "//evil.example", "/\\evil.example", "/login"]) {
      expect(safeNext(hostile)).toBe("/");
    }
  });
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { calendarWeek, addDays, moscowDate } from "./lessons";
import { SchedulePage } from "./SchedulePage";

const requested: { start: string; finish: string }[] = [];

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-11-13T12:00:00+03:00"));
  requested.length = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: string) => {
    const url = new URL(input, "https://dekanat.test");
    const range = { start: url.searchParams.get("start")!, finish: url.searchParams.get("finish")! };
    requested.push(range);
    return new Response(JSON.stringify({ ...range, timezone: "Europe/Moscow", lessons: [] }), {
      headers: { "Content-Type": "application/json" },
    });
  }));
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function renderSchedule() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(<QueryClientProvider client={client}><SchedulePage /></QueryClientProvider>);
}

function dates() {
  return {
    start: (screen.getByLabelText("С даты") as HTMLInputElement).value,
    finish: (screen.getByLabelText("По дату") as HTMLInputElement).value,
  };
}

describe("Moscow teaching week", () => {
  it("opens the complete Monday–Sunday range even on Friday", async () => {
    renderSchedule();
    expect(dates()).toEqual({ start: "2026-11-09", finish: "2026-11-15" });
    await waitFor(() => expect(requested).toContainEqual(dates()));
  });

  it("selects adjacent full weeks and returns to the current one", async () => {
    renderSchedule();
    fireEvent.click(screen.getByRole("button", { name: "Следующая неделя" }));
    expect(dates()).toEqual({ start: "2026-11-16", finish: "2026-11-22" });
    await waitFor(() => expect(requested).toContainEqual(dates()));
    fireEvent.click(screen.getByRole("button", { name: "Предыдущая неделя" }));
    fireEvent.click(screen.getByRole("button", { name: "Предыдущая неделя" }));
    expect(dates()).toEqual({ start: "2026-11-02", finish: "2026-11-08" });
    fireEvent.click(screen.getByRole("button", { name: "Эта неделя" }));
    expect(dates()).toEqual({ start: "2026-11-09", finish: "2026-11-15" });
  });

  it("preserves an explicit one-day query until the student selects a week", async () => {
    renderSchedule();
    fireEvent.change(screen.getByLabelText("С даты"), { target: { value: "2026-11-13" } });
    fireEvent.change(screen.getByLabelText("По дату"), { target: { value: "2026-11-13" } });
    fireEvent.click(screen.getByRole("button", { name: "Показать" }));
    await waitFor(() => expect(requested).toContainEqual({ start: "2026-11-13", finish: "2026-11-13" }));
    expect(dates()).toEqual({ start: "2026-11-13", finish: "2026-11-13" });
    fireEvent.click(screen.getByRole("button", { name: "Эта неделя" }));
    expect(dates()).toEqual({ start: "2026-11-09", finish: "2026-11-15" });
  });

  it("uses Moscow Monday when the instant is still Sunday in Los Angeles", async () => {
    const instant = new Date("2026-11-15T22:30:00Z");
    expect(new Intl.DateTimeFormat("en", { timeZone: "America/Los_Angeles", weekday: "long" }).format(instant)).toBe("Sunday");
    vi.setSystemTime(instant);
    expect(moscowDate()).toBe("2026-11-16");
    renderSchedule();
    expect(dates()).toEqual({ start: "2026-11-16", finish: "2026-11-22" });
    await waitFor(() => expect(requested).toContainEqual(dates()));
  });

  it("keeps inclusive week boundaries across the year change", () => {
    expect(calendarWeek("2027-01-01")).toEqual({ start: "2026-12-28", finish: "2027-01-03" });
    expect(calendarWeek(addDays("2026-12-28", 7))).toEqual({ start: "2027-01-04", finish: "2027-01-10" });
    expect(addDays("2027-01-01", -1)).toBe("2026-12-31");
  });
});

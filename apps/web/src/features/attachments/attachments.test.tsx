import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AttachButton, AttachmentList, PendingFiles, sizeLabel, useAttachments, type AttachmentInfo } from "./Attachments";

type Reply = { status: number; body: unknown };
let reply: Reply;
const sent: { url: string; headers: Record<string, string> }[] = [];

class FakeXHR {
  status = 0;
  responseText = "";
  upload: { onprogress: ((event: { lengthComputable: boolean; loaded: number; total: number }) => void) | null } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  withCredentials = false;
  private url = "";
  private headers: Record<string, string> = {};
  open(_method: string, url: string) { this.url = url; }
  setRequestHeader(name: string, value: string) { this.headers[name] = value; }
  getResponseHeader() { return null; }
  send(file: File) {
    sent.push({ url: this.url, headers: this.headers });
    this.upload.onprogress?.({ lengthComputable: true, loaded: file.size / 2, total: file.size });
    setTimeout(() => {
      this.status = reply.status;
      this.responseText = JSON.stringify(reply.body);
      this.onload?.();
    }, 0);
  }
}

function Harness() {
  const state = useAttachments("/api/requests/r1/attachments", (info) => info.url ?? "");
  return (
    <div>
      <AttachButton state={state} />
      <PendingFiles state={state} />
      <output data-testid="ids">{state.ids.join(",")}</output>
    </div>
  );
}

function file(name: string, size = 2048, type = "application/pdf") {
  return new File([new Uint8Array(size)], name, { type });
}

beforeEach(() => {
  sent.length = 0;
  reply = { status: 201, body: { id: "a1", name: "справка.pdf", kind: "pdf", size: 2048, url: "/api/requests/r1/attachments/a1" } };
  vi.stubGlobal("XMLHttpRequest", FakeXHR);
});
afterEach(() => vi.unstubAllGlobals());

describe("attachments", () => {
  it("shows the empty state, uploads a picked file and keeps its id", async () => {
    render(<Harness />);
    expect(screen.getByText(/до 5 файлов: PDF, DOCX, JPEG или PNG/)).toBeInTheDocument();
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, file("справка.pdf"));
    expect(await screen.findByText("справка.pdf")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("ids").textContent).toBe("a1"));
    expect(screen.getByText(/2 КБ · готов/)).toBeInTheDocument();
    expect(sent[0]?.url).toBe("/api/requests/r1/attachments");
    expect(sent[0]?.headers["X-File-Name"]).toBe(encodeURIComponent("справка.pdf"));
  });

  it("refuses wrong types and oversized files before uploading", async () => {
    render(<Harness />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    input.removeAttribute("accept"); // the browser filter is only a hint; the code checks again
    await userEvent.upload(input, [file("программа.exe", 100, "application/octet-stream"), file("большой.pdf", 11 * 1024 * 1024)]);
    expect(await screen.findByText("Можно прикрепить PDF, DOCX, JPEG или PNG.")).toBeInTheDocument();
    expect(screen.getByText("Файл больше 10 МБ.")).toBeInTheDocument();
    expect(sent).toHaveLength(0);
    expect(screen.getByTestId("ids").textContent).toBe("");
  });

  it("shows why a red button file was not accepted and does not send it", async () => {
    reply = { status: 200, body: { id: null, name: "x.docx", kind: "docx", size: 900, url: null, check: "blocked", check_message: "В файле есть оскорбления. Уберите его." } };
    render(<Harness />);
    await userEvent.upload(document.querySelector('input[type="file"]') as HTMLInputElement, file("x.docx", 900));
    expect(await screen.findByText("В файле есть оскорбления. Уберите его.")).toBeInTheDocument();
    expect(screen.getByTestId("ids").textContent).toBe("");
    await userEvent.click(screen.getByRole("button", { name: "Убрать x.docx" }));
    expect(screen.queryByText("x.docx")).not.toBeInTheDocument();
  });

  it("shows the server error text", async () => {
    reply = { status: 422, body: { error: { code: "unsupported_type", message: "Такой тип файла не поддерживается." } } };
    render(<Harness />);
    await userEvent.upload(document.querySelector('input[type="file"]') as HTMLInputElement, file("fake.pdf"));
    expect(await screen.findByText("Такой тип файла не поддерживается.")).toBeInTheDocument();
  });

  it("lists sent files with a type icon and a download link", () => {
    const files: AttachmentInfo[] = [
      { id: "1", name: "ведомость.pdf", kind: "pdf", size: 3000, url: "/f/1" },
      { id: "2", name: "скрин.png", kind: "png", size: 2_500_000, url: "/f/2", check: "unverified", check_label: "Не проверен автоматически" },
    ];
    render(<AttachmentList files={files} showCheck />);
    expect(screen.getByRole("link", { name: /ведомость\.pdf/ })).toHaveAttribute("href", "/f/1");
    expect(screen.getByLabelText("PDF")).toBeInTheDocument();
    expect(screen.getByLabelText("Изображение")).toBeInTheDocument();
    expect(screen.getByText(/2,4 МБ · Не проверен автоматически/)).toBeInTheDocument();
    expect(sizeLabel(512)).toBe("512 Б");
  });
});

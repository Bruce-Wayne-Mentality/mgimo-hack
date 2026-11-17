import { FileImage, FileText, FileType, Paperclip, ShieldAlert, ShieldQuestion, X } from "lucide-react";
import { useCallback, useRef, useState, type DragEvent, type ReactNode } from "react";
import { ApiError, api, apiErrorFrom, getCsrfToken } from "@/lib/api";
import { cn } from "@/lib/cn";

export type AttachmentKind = "pdf" | "docx" | "jpeg" | "png";
export type AttachmentInfo = {
  id: string | null;
  name: string;
  kind: AttachmentKind;
  size: number;
  url: string | null;
  check?: "ok" | "blocked" | "unverified" | "skipped";
  check_label?: string;
  check_message?: string;
};

/** Mirrors the server defaults (ATTACHMENT_MAX_FILES, ATTACHMENT_MAX_MB); the server decides in the end. */
export const MAX_FILES = 5;
export const MAX_MB = 10;
const ACCEPT = ".pdf,.docx,.jpg,.jpeg,.png,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,image/jpeg,image/png";
const ALLOWED = /\.(pdf|docx|jpe?g|png)$/i;

export function sizeLabel(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`;
  return `${(bytes / 1024 / 1024).toFixed(1).replace(".", ",")} МБ`;
}

export function FileIcon({ kind, className }: { kind: string; className?: string }) {
  const Icon = kind === "pdf" ? FileText : kind === "docx" ? FileType : FileImage;
  const tone = kind === "pdf" ? "text-[#b42318]" : kind === "docx" ? "text-[#2f6ae6]" : "text-[#146c3a]";
  return <Icon aria-label={kind === "pdf" ? "PDF" : kind === "docx" ? "Word" : "Изображение"} className={cn("size-5 shrink-0", tone, className)} />;
}

/** Raw-body upload through XHR: unlike fetch it reports upload progress. */
export function uploadFile(url: string, file: File, onProgress: (share: number) => void): Promise<AttachmentInfo> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.withCredentials = true;
    xhr.setRequestHeader("Accept", "application/json");
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.setRequestHeader("X-File-Name", encodeURIComponent(file.name));
    const token = getCsrfToken();
    if (token) xhr.setRequestHeader("X-CSRF-Token", token);
    xhr.upload.onprogress = (event) => event.lengthComputable && onProgress(event.loaded / event.total);
    xhr.onerror = () => reject(new ApiError(0, "network", "Нет связи с сервером. Проверьте интернет и повторите."));
    xhr.onload = () => {
      let data: unknown = null;
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        /* not json */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data as AttachmentInfo);
      else reject(apiErrorFrom(xhr.status, data, xhr.getResponseHeader("Retry-After")));
    };
    xhr.send(file);
  });
}

type Item = { key: string; name: string; size: number; progress: number; state: "uploading" | "ready" | "blocked" | "error"; info?: AttachmentInfo; error?: string };

/** Files picked for one message: upload right away, keep the ids of those that can be sent. */
export function useAttachments(uploadUrl: string, deleteUrl: (info: AttachmentInfo) => string) {
  const [items, setItems] = useState<Item[]>([]);
  const patch = (key: string, change: Partial<Item>) => setItems((list) => list.map((item) => (item.key === key ? { ...item, ...change } : item)));

  const add = useCallback((files: FileList | File[]) => {
    const picked = Array.from(files);
    setItems((list) => {
      const room = MAX_FILES - list.filter((i) => i.state !== "error" && i.state !== "blocked").length;
      const next = [...list];
      picked.forEach((file, index) => {
        const key = `${Date.now()}-${index}-${file.name}`;
        let error: string | undefined;
        if (index >= room) error = `Не больше ${MAX_FILES} файлов в одном сообщении.`;
        else if (!ALLOWED.test(file.name)) error = "Можно прикрепить PDF, DOCX, JPEG или PNG.";
        else if (file.size > MAX_MB * 1024 * 1024) error = `Файл больше ${MAX_MB} МБ.`;
        else if (file.size === 0) error = "Файл пустой.";
        next.push({ key, name: file.name, size: file.size, progress: 0, state: error ? "error" : "uploading", error });
        if (!error) {
          uploadFile(uploadUrl, file, (share) => patch(key, { progress: share }))
            .then((info) => patch(key, { info, progress: 1, name: info.name, state: info.check === "blocked" || !info.id ? "blocked" : "ready" }))
            .catch((reason: unknown) => patch(key, { state: "error", error: reason instanceof Error ? reason.message : "Файл не загрузился." }));
        }
      });
      return next;
    });
  }, [uploadUrl]);

  const remove = useCallback((key: string) => {
    setItems((list) => {
      const item = list.find((i) => i.key === key);
      if (item?.info?.id && item.state === "ready") void api(deleteUrl(item.info), { method: "DELETE" }).catch(() => undefined);
      return list.filter((i) => i.key !== key);
    });
  }, [deleteUrl]);

  const ids = items.filter((i) => i.state === "ready" && i.info?.id).map((i) => i.info!.id as string);
  const busy = items.some((i) => i.state === "uploading");
  return { items, add, remove, ids, busy, reset: () => setItems([]) };
}

export type AttachmentsState = ReturnType<typeof useAttachments>;

/** The paperclip: opens the file picker. */
export function AttachButton({ state, disabled }: { state: AttachmentsState; disabled?: boolean }) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <>
      <input
        ref={input}
        type="file"
        multiple
        accept={ACCEPT}
        className="sr-only"
        tabIndex={-1}
        aria-hidden
        onChange={(event) => {
          if (event.target.files?.length) state.add(event.target.files);
          event.target.value = "";
        }}
      />
      <button
        type="button"
        disabled={disabled}
        onClick={() => input.current?.click()}
        aria-label="Прикрепить файл"
        title={`PDF, DOCX, JPEG или PNG — до ${MAX_FILES} файлов, до ${MAX_MB} МБ каждый`}
        className="soft grid size-11 shrink-0 place-items-center rounded-full text-text-2 hover:bg-primary-soft hover:text-primary disabled:opacity-50"
      >
        <Paperclip aria-hidden className="size-5" />
      </button>
    </>
  );
}

/** A form area that accepts files dropped onto it. */
export function DropZone({ state, children, className }: { state: AttachmentsState; children: ReactNode; className?: string }) {
  const [over, setOver] = useState(false);
  const enter = (event: DragEvent) => {
    if (Array.from(event.dataTransfer.types).includes("Files")) {
      event.preventDefault();
      setOver(true);
    }
  };
  return (
    <div
      className={cn("relative", className)}
      onDragOver={enter}
      onDragEnter={enter}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOver(false);
      }}
      onDrop={(event) => {
        if (!event.dataTransfer.files.length) return;
        event.preventDefault();
        setOver(false);
        state.add(event.dataTransfer.files);
      }}
    >
      {children}
      {over && (
        <div className="pointer-events-none absolute inset-0 grid place-items-center rounded-[var(--radius-control)] border-2 border-dashed border-primary bg-primary-soft/90 text-sm font-medium text-primary-strong">
          Отпустите, чтобы прикрепить
        </div>
      )}
    </div>
  );
}

/** Picked files under the input: name, size, progress, the check result, «убрать». */
export function PendingFiles({ state, hint }: { state: AttachmentsState; hint?: string }) {
  if (!state.items.length) {
    return <p className="caption m-0">{hint ?? `Можно прикрепить до ${MAX_FILES} файлов: PDF, DOCX, JPEG или PNG, до ${MAX_MB} МБ каждый — скрепкой или перетаскиванием.`}</p>;
  }
  return (
    <ul className="m-0 flex list-none flex-col gap-1.5 p-0" aria-label="Прикреплённые файлы">
      {state.items.map((item) => {
        const warn = item.state === "blocked" || item.state === "error";
        const unverified = item.info?.check === "unverified";
        return (
          <li key={item.key} className={cn("rounded-[12px] px-3 py-2", warn ? "bg-[#fdecec]" : "bg-surface-2")}>
            <div className="flex min-w-0 items-center gap-2.5">
              <FileIcon kind={item.info?.kind ?? (/\.pdf$/i.test(item.name) ? "pdf" : /\.docx$/i.test(item.name) ? "docx" : "png")} />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">{item.name}</span>
                <span className="caption block">
                  {sizeLabel(item.size)}
                  {item.state === "uploading" && ` · загрузка ${Math.round(item.progress * 100)}%`}
                  {item.state === "ready" && (unverified ? " · не проверен автоматически" : " · готов")}
                </span>
              </span>
              <button type="button" onClick={() => state.remove(item.key)} aria-label={`Убрать ${item.name}`}
                className="soft grid size-9 shrink-0 place-items-center rounded-full text-muted hover:bg-surface">
                <X aria-hidden className="size-4" />
              </button>
            </div>
            {item.state === "uploading" && (
              <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-surface" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(item.progress * 100)} aria-label={`Загрузка ${item.name}`}>
                <div className="h-full rounded-full bg-primary transition-[width]" style={{ width: `${Math.max(4, item.progress * 100)}%` }} />
              </div>
            )}
            {(warn || unverified) && (
              <p className={cn("m-0 mt-1 flex items-start gap-1.5 text-[13px]", warn ? "text-[#b42318]" : "text-[#8a5a00]")}>
                {warn ? <ShieldAlert aria-hidden className="mt-0.5 size-4 shrink-0" /> : <ShieldQuestion aria-hidden className="mt-0.5 size-4 shrink-0" />}
                <span>{item.error ?? item.info?.check_message}</span>
              </p>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/** Files of a sent message: an icon of the type, the name and size; opens as a download. */
export function AttachmentList({ files, inverse = false, showCheck = false }: { files?: AttachmentInfo[]; inverse?: boolean; showCheck?: boolean }) {
  if (!files?.length) return null;
  return (
    <ul className="m-0 mt-2 flex list-none flex-col gap-1.5 p-0">
      {files.map((file) => (
        <li key={file.id ?? file.name}>
          <a
            href={file.url ?? undefined}
            download={file.name}
            className={cn("soft flex min-w-0 items-center gap-2.5 rounded-[10px] px-3 py-2", inverse ? "bg-white/15 hover:bg-white/25" : "bg-surface hover:bg-primary-soft")}
          >
            <FileIcon kind={file.kind} className={inverse ? "text-on-primary" : undefined} />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium">{file.name}</span>
              <span className={cn("block text-[12px]", inverse ? "opacity-80" : "text-muted")}>
                {sizeLabel(file.size)}
                {showCheck && file.check && file.check !== "ok" && file.check_label ? ` · ${file.check_label}` : ""}
              </span>
            </span>
          </a>
        </li>
      ))}
    </ul>
  );
}

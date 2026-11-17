import { Camera, ScanLine } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { Alert, Button, Card, Field, Input, PageHeader } from "@/components/ui";

type Detector = { detect: (source: HTMLVideoElement) => Promise<{ rawValue: string }[]> };
type DetectorClass = new (options: { formats: string[] }) => Detector;

function pathFrom(value: string): string | null {
  try {
    const url = new URL(value.trim(), window.location.origin);
    const match = url.pathname.match(/^\/(id|verify)\/[A-Za-z0-9._-]+$/);
    return match ? url.pathname : null;
  } catch {
    return null;
  }
}

/** Staff «Проверять» mode: native BarcodeDetector when the browser has it, or a pasted link. */
export function ScanPage() {
  const navigate = useNavigate();
  const video = useRef<HTMLVideoElement>(null);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [link, setLink] = useState("");
  const supported = typeof window !== "undefined" && "BarcodeDetector" in window;

  useEffect(() => {
    if (!scanning) return;
    let stream: MediaStream | null = null;
    let stop = false;
    const Detector = (window as unknown as { BarcodeDetector: DetectorClass }).BarcodeDetector;
    const detector = new Detector({ formats: ["qr_code"] });
    (async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
        if (!video.current) return;
        video.current.srcObject = stream;
        await video.current.play();
        while (!stop) {
          const codes = await detector.detect(video.current).catch(() => []);
          const path = codes.map((code) => pathFrom(code.rawValue)).find(Boolean);
          if (path) {
            navigate(path);
            return;
          }
          await new Promise((resolve) => setTimeout(resolve, 250));
        }
      } catch {
        setError("Нет доступа к камере. Разрешите камеру в браузере или вставьте ссылку ниже.");
        setScanning(false);
      }
    })();
    return () => {
      stop = true;
      stream?.getTracks().forEach((track) => track.stop());
    };
  }, [scanning, navigate]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const path = pathFrom(link);
    if (path) navigate(path);
    else setError("Это не ссылка студенческого или документа.");
  };

  return (
    <div className="flex max-w-[560px] flex-col gap-4">
      <PageHeader eyebrow="Режим охраны и деканата" title="Проверить QR" />
      <Card>
        {supported ? (
          scanning ? (
            <div className="flex flex-col gap-3">
              <div className="relative overflow-hidden rounded-[var(--radius-tile)] bg-black">
                <video ref={video} playsInline muted className="aspect-square w-full object-cover" />
                <ScanLine aria-hidden className="absolute inset-0 m-auto size-40 text-white/70" />
              </div>
              <Button variant="secondary" onClick={() => setScanning(false)}>Остановить</Button>
            </div>
          ) : (
            <Button onClick={() => { setError(null); setScanning(true); }}>
              <Camera aria-hidden className="size-5" /> Сканировать камерой
            </Button>
          )
        ) : (
          <p className="m-0 text-text-2">Этот браузер не умеет распознавать QR сам. Отсканируйте код камерой телефона — откроется страница проверки — или вставьте ссылку.</p>
        )}
      </Card>
      <Card>
        <form onSubmit={submit} className="flex flex-col gap-3">
          <Field id="link" label="Ссылка из QR-кода">
            <Input id="link" value={link} onChange={(event) => setLink(event.target.value)} placeholder="https://…/id/…" inputMode="url" />
          </Field>
          <Button type="submit" variant="secondary">Проверить</Button>
        </form>
      </Card>
      {error && <Alert>{error}</Alert>}
    </div>
  );
}

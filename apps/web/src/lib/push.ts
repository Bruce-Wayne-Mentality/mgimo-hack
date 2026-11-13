import { api } from "./api";

function decodeKey(key: string): Uint8Array<ArrayBuffer> {
  const padded = (key + "=".repeat((4 - (key.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  const bytes = new Uint8Array(new ArrayBuffer(atob(padded).length));
  atob(padded).split("").forEach((char, index) => (bytes[index] = char.charCodeAt(0)));
  return bytes;
}

export function pushSupported(): boolean {
  return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

/** Ask permission, subscribe this browser and store the subscription for the signed-in account. */
export async function connectPush(): Promise<void> {
  if (!pushSupported()) throw new Error("Этот браузер не поддерживает push-уведомления.");
  if (!window.isSecureContext) throw new Error("Браузерные уведомления доступны только по HTTPS.");
  const permission = await Notification.requestPermission();
  if (permission !== "granted") {
    throw new Error("Разрешите уведомления в настройках браузера. События по-прежнему будут в колокольчике.");
  }
  const registration = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
  await navigator.serviceWorker.ready;
  const { public_key: publicKey } = await api<{ public_key: string }>("/api/push/public-key");
  const subscription =
    (await registration.pushManager.getSubscription()) ??
    (await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: decodeKey(publicKey) }));
  await api("/api/me/push-subscriptions", { method: "POST", body: subscription.toJSON() });
}

/** On sign-out: stop this browser from receiving the previous account's notifications. */
export async function disconnectPush(): Promise<void> {
  try {
    if (!pushSupported()) return;
    const registration = await navigator.serviceWorker.getRegistration("/");
    const subscription = await registration?.pushManager.getSubscription();
    if (!subscription) return;
    await api("/api/me/push-subscriptions", { method: "DELETE", body: { endpoint: subscription.endpoint } }).catch(() => undefined);
    await subscription.unsubscribe();
  } catch {
    // Signing out must not fail because of the browser's push state.
  }
}

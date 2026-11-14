"use strict";

const accounts = {alice: "demo-alice-token", bob: "demo-bob-token"};
const $ = (id) => document.getElementById(id);
let generation = 0;
let scheduleRequest = 0;
let session;
let nextBefore = null;

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function showError(id, message = "") {
  $(id).textContent = message;
  $(id).hidden = !message;
}

function isCurrent(account) { return account === session && account.version === generation; }

async function api(path, options = {}, account = session) {
  if (!isCurrent(account)) throw new DOMException("Аккаунт изменён", "AbortError");
  const response = await fetch(path, {
    ...options,
    headers: {"Content-Type": "application/json", Authorization: `Bearer ${account.token}`, ...(options.headers || {})},
    signal: account.controller.signal,
    cache: "no-store",
  });
  if (!isCurrent(account)) throw new DOMException("Аккаунт изменён", "AbortError");
  const data = response.status === 204 ? null : await response.json();
  if (!isCurrent(account)) throw new DOMException("Аккаунт изменён", "AbortError");
  if (!response.ok) {
    const error = new Error(typeof data.detail === "string" ? data.detail : "Не удалось выполнить запрос. Попробуйте ещё раз.");
    error.status = response.status;
    throw error;
  }
  return data;
}

function handleError(id, error) {
  if (error.name !== "AbortError") showError(id, error.message || "Нет связи с приложением.");
}

function localDate(value = new Date()) {
  const parts = new Intl.DateTimeFormat("en-CA", {timeZone: "Europe/Moscow", year: "numeric", month: "2-digit", day: "2-digit"}).formatToParts(value);
  const fields = Object.fromEntries(parts.map(({type, value}) => [type, value]));
  return `${fields.year}-${fields.month}-${fields.day}`;
}

function shiftCalendarDate(day, count) {
  const [year, month, date] = day.split("-").map(Number);
  const shifted = new Date(Date.UTC(year, month - 1, date));
  shifted.setUTCDate(shifted.getUTCDate() + count);
  return shifted.toISOString().slice(0, 10);
}

function calendarWeek(day = localDate()) {
  const [year, month, date] = day.split("-").map(Number);
  const weekday = new Date(Date.UTC(year, month - 1, date)).getUTCDay();
  const start = shiftCalendarDate(day, -((weekday + 6) % 7));
  return {start, finish: shiftCalendarDate(start, 6)};
}

function selectWeek(day = localDate()) {
  const {start, finish} = calendarWeek(day);
  $("start-date").value = start;
  $("finish-date").value = finish;
  loadSchedule();
}

function dateLabel(day) {
  return new Intl.DateTimeFormat("ru", {day: "numeric", month: "long", weekday: "long", timeZone: "Europe/Moscow"}).format(new Date(`${day}T12:00:00+03:00`));
}

function timeLabel(value) {
  return new Intl.DateTimeFormat("ru", {hour: "2-digit", minute: "2-digit", timeZone: "Europe/Moscow"}).format(new Date(value));
}

async function loadSchedule(account = session, quiet = false) {
  const request = ++scheduleRequest;
  const start = $("start-date").value;
  const finish = $("finish-date").value;
  if (!start || !finish) return;
  if (!quiet) showError("schedule-error");
  try {
    const query = new URLSearchParams({start, finish});
    const data = await api(`/api/me/schedule?${query}`, {}, account);
    if (!isCurrent(account) || request !== scheduleRequest) return;
    $("schedule-list").replaceChildren();
    const days = new Map();
    for (const lesson of data.lessons) {
      if (!days.has(lesson.date)) days.set(lesson.date, []);
      days.get(lesson.date).push(lesson);
    }
    if (!days.size) $("schedule-list").append(node("p", "empty-state", "На эти даты пар нет. Можно выбрать другую неделю или период."));
    for (const [day, lessons] of days) {
      const section = node("section", "schedule-day");
      section.append(node("h3", "day-heading", dateLabel(day)));
      for (const lesson of lessons) {
        const item = node("article", "lesson");
        const time = node("div", "lesson-time", timeLabel(lesson.starts_at));
        time.append(node("small", "", timeLabel(lesson.ends_at)));
        const details = node("div", "lesson-details");
        details.append(node("p", "lesson-kind", lesson.kind || "Занятие"), node("h4", "lesson-title", lesson.title));
        if (lesson.teachers.length) details.append(node("p", "lesson-meta", lesson.teachers.join(", ")));
        const place = [lesson.room ? `ауд. ${lesson.room}` : "", lesson.building].filter(Boolean).join(" · ");
        if (place) details.append(node("p", "lesson-meta", place));
        item.append(time, details);
        section.append(item);
      }
      $("schedule-list").append(section);
    }
  } catch (error) {
    if (!quiet && request === scheduleRequest) handleError("schedule-error", error);
  }
}

function renderSettings(data) {
  $("notifications-enabled").checked = data.enabled;
  $("settings-status").textContent = data.enabled
    ? "Включены. Подключите удобный способ доставки ниже."
    : "Выключены. Все события сохраняются в колокольчике.";
}

async function loadTelegram(account = session) {
  const data = await api("/api/me/telegram", {}, account);
  if (!isCurrent(account)) return;
  $("telegram-status").textContent = data.linked
    ? `Аккаунт привязан${data.username ? `: @${data.username.replace(/^@/, "")}` : "."}`
    : "Аккаунт не привязан.";
  $("link-telegram").hidden = data.linked;
  $("unlink-telegram").hidden = !data.linked;
  if (data.linked) $("telegram-link-box").hidden = true;
}

function appendNotifications(items, account) {
  for (const notification of items) {
    const item = node("article", `notification${notification.read_at ? "" : " is-unread"}`);
    const content = node("div");
    content.append(node("h3", "", notification.title), node("p", "", notification.body));
    const timestamp = node("time", "", new Intl.DateTimeFormat("ru", {day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Moscow"}).format(new Date(notification.created_at)));
    timestamp.dateTime = notification.created_at;
    content.append(timestamp);
    item.append(content);
    if (!notification.read_at) {
      const read = node("button", "text-button", "Прочитано");
      read.addEventListener("click", async () => {
        read.disabled = true;
        try {
          await api(`/api/me/notifications/${notification.id}/read`, {method: "POST"}, account);
          await loadNotifications(account);
        } catch (error) { handleError("inbox-error", error); }
        finally { read.disabled = false; }
      });
      item.append(read);
    }
    $("notification-list").append(item);
  }
}

async function loadNotifications(account = session, more = false, quiet = false) {
  try {
    const query = new URLSearchParams({limit: "50"});
    if (more && nextBefore !== null) query.set("before", nextBefore);
    const data = await api(`/api/me/notifications?${query}`, {}, account);
    if (!isCurrent(account)) return;
    if (!more) $("notification-list").replaceChildren();
    appendNotifications(data.items, account);
    if (!$("notification-list").children.length) $("notification-list").append(node("p", "empty-state", "Здесь появятся напоминания и изменения расписания."));
    $("unread-count").textContent = data.unread_count > 99 ? "99+" : data.unread_count;
    $("unread-count").hidden = !data.unread_count;
    $("read-all").disabled = !data.unread_count;
    nextBefore = data.next_before;
    $("load-more").hidden = nextBefore === null || nextBefore === undefined;
    if (!quiet) showError("inbox-error");
  } catch (error) { if (!quiet) handleError("inbox-error", error); }
}

function decodeKey(key) {
  const padded = (key + "=".repeat((4 - key.length % 4) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  return Uint8Array.from(atob(padded), (character) => character.charCodeAt(0));
}

$("notifications-enabled").addEventListener("change", async (event) => {
  const account = session;
  const enabled = event.target.checked;
  event.target.disabled = true;
  showError("settings-error");
  try { renderSettings(await api("/api/me/notification-settings", {method: "PATCH", body: JSON.stringify({enabled})}, account)); }
  catch (error) { if (isCurrent(account)) event.target.checked = !enabled; handleError("settings-error", error); }
  finally { if (isCurrent(account)) event.target.disabled = false; }
});

$("enable-browser").addEventListener("click", async () => {
  const account = session;
  const button = $("enable-browser");
  button.disabled = true;
  $("browser-status").textContent = "";
  showError("settings-error");
  try {
    if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) throw new Error("Этот браузер не поддерживает push-уведомления.");
    if (!window.isSecureContext) throw new Error("Браузерные уведомления доступны по HTTPS или на localhost.");
    const permission = await Notification.requestPermission();
    if (!isCurrent(account)) return;
    if (permission !== "granted") throw new Error("Разрешите уведомления в настройках браузера. События по-прежнему будут в колокольчике.");
    const registration = await navigator.serviceWorker.register("/sw.js", {scope: "/"});
    await navigator.serviceWorker.ready;
    const {public_key: publicKey} = await api("/api/push/public-key", {}, account);
    let subscription = await registration.pushManager.getSubscription();
    if (!subscription) subscription = await registration.pushManager.subscribe({userVisibleOnly: true, applicationServerKey: decodeKey(publicKey)});
    if (!isCurrent(account)) return;
    await api("/api/me/push-subscriptions", {method: "POST", body: JSON.stringify(subscription.toJSON())}, account);
    renderSettings(await api("/api/me/notification-settings", {method: "PATCH", body: JSON.stringify({enabled: true})}, account));
    $("browser-status").textContent = "Уведомления в этом браузере подключены для выбранного аккаунта.";
  } catch (error) { handleError("settings-error", error); }
  finally { if (isCurrent(account)) button.disabled = false; }
});

$("link-telegram").addEventListener("click", async () => {
  const account = session;
  const button = $("link-telegram");
  button.disabled = true;
  showError("settings-error");
  try {
    const data = await api("/api/me/telegram/link", {method: "POST"}, account);
    const url = new URL(data.deep_link);
    if (url.protocol !== "https:" || url.hostname !== "t.me") throw new Error("Не удалось получить ссылку Telegram.");
    $("telegram-link").href = url.href;
    $("telegram-link-box").hidden = false;
  } catch (error) { handleError("settings-error", error); }
  finally { if (isCurrent(account)) button.disabled = false; }
});

$("unlink-telegram").addEventListener("click", async () => {
  const account = session;
  try {
    await api("/api/me/telegram", {method: "DELETE"}, account);
    await loadTelegram(account);
    showError("settings-error");
  } catch (error) { handleError("settings-error", error); }
});

$("bell-button").addEventListener("click", () => {
  const hidden = !$("notification-panel").hidden;
  $("notification-panel").hidden = hidden;
  $("bell-button").setAttribute("aria-expanded", String(!hidden));
  if (!hidden) loadNotifications();
});

$("read-all").addEventListener("click", async () => {
  const account = session;
  try { await api("/api/me/notifications/read-all", {method: "POST"}, account); await loadNotifications(account); }
  catch (error) { handleError("inbox-error", error); }
});
$("load-more").addEventListener("click", () => loadNotifications(session, true));
$("date-form").addEventListener("submit", (event) => { event.preventDefault(); loadSchedule(); });
$("previous-week").addEventListener("click", () => selectWeek(shiftCalendarDate($("start-date").value || localDate(), -7)));
$("current-week").addEventListener("click", () => selectWeek());
$("next-week").addEventListener("click", () => selectWeek(shiftCalendarDate($("start-date").value || localDate(), 7)));
$("refresh").addEventListener("click", () => { loadSchedule(); loadNotifications(); });

async function switchAccount() {
  if (session) session.controller.abort();
  session = {version: ++generation, token: accounts[$("account").value], controller: new AbortController()};
  const account = session;
  nextBefore = null;
  $("greeting").textContent = "Моё расписание";
  $("account-email").textContent = "Загружаем личный кабинет…";
  $("schedule-list").replaceChildren(node("p", "empty-state", "Загружаем пары…"));
  $("notification-list").replaceChildren(node("p", "empty-state", "Загружаем уведомления…"));
  $("unread-count").hidden = true;
  $("notifications-enabled").checked = false;
  $("notifications-enabled").disabled = true;
  $("settings-status").textContent = "Загружаем настройки…";
  $("read-all").disabled = true;
  $("load-more").hidden = true;
  $("enable-browser").disabled = false;
  $("link-telegram").disabled = false;
  $("link-telegram").hidden = false;
  $("unlink-telegram").hidden = true;
  $("telegram-link-box").hidden = true;
  $("telegram-link").removeAttribute("href");
  $("telegram-status").textContent = "Загружаем статус…";
  $("browser-status").textContent = "Подключение браузера относится к выбранному аккаунту. Для смены нажмите кнопку выше.";
  for (const id of ["settings-error", "schedule-error", "inbox-error"]) showError(id);
  try {
    const [student, settings] = await Promise.all([api("/api/me", {}, account), api("/api/me/notification-settings", {}, account)]);
    if (!isCurrent(account)) return;
    $("greeting").textContent = `Здравствуйте, ${student.name}`;
    $("account-email").textContent = student.email;
    renderSettings(settings);
    $("notifications-enabled").disabled = false;
  } catch (error) { handleError("settings-error", error); }
  await Promise.allSettled([loadSchedule(account), loadNotifications(account), loadTelegram(account)]);
}

const initialWeek = calendarWeek();
$("start-date").value = initialWeek.start;
$("finish-date").value = initialWeek.finish;
$("account").addEventListener("change", switchAccount);
switchAccount();
setInterval(() => {
  if (document.visibilityState === "visible") {
    loadNotifications(session, false, true);
    loadTelegram(session).catch(() => {});
  }
}, 15000);
setInterval(() => { if (document.visibilityState === "visible") loadSchedule(session, true); }, 60000);

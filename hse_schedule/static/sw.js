"use strict";

self.addEventListener("push", (event) => {
  let payload = {};
  try { payload = event.data ? event.data.json() : {}; } catch (_) { /* Use safe defaults. */ }
  event.waitUntil(self.registration.showNotification(
    typeof payload.title === "string" ? payload.title : "Учебный офис",
    {
      body: typeof payload.body === "string" ? payload.body : "В вашем расписании есть новости.",
      tag: typeof payload.tag === "string" ? payload.tag : `notification-${payload.id || "update"}`,
      data: {url: "/"},
    }
  ));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({type: "window", includeUncontrolled: true});
    for (const client of windows) {
      if (new URL(client.url).origin === self.location.origin && "focus" in client) return client.focus();
    }
    return self.clients.openWindow(new URL("/", self.location.origin).href);
  })());
});

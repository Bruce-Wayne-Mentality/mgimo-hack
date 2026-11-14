import type { RouteObject } from "react-router";
import { LoginPage } from "@/features/auth/LoginPage";
import { RequireAuth } from "@/features/auth/RequireAuth";
import { HomePage } from "@/features/home/HomePage";
import { NotificationsPage } from "@/features/notifications/NotificationsPage";
import { ComingSoon, MorePage, NotFoundPage } from "@/features/placeholder/pages";
import { ProfilePage } from "@/features/profile/ProfilePage";
import { NewRequestPage } from "@/features/requests/NewRequestPage";
import { RequestDetailPage } from "@/features/requests/RequestDetailPage";
import { RequestsPage } from "@/features/requests/RequestsPage";
import { StaffRequestPage, StaffRequestsPage } from "@/features/staff/StaffRequestsPage";
import { SchedulePage } from "@/features/schedule/SchedulePage";
import { AppShell } from "./AppShell";

// /login is the only public screen; everything else sits behind RequireAuth
// (the server also redirects page requests without a session to /login).
export const routes: RouteObject[] = [
  { path: "/login", element: <LoginPage /> },
  {
    element: <RequireAuth />,
    children: [
      {
        element: <AppShell />,
        children: [
          { index: true, element: <HomePage /> },
          { path: "profile", element: <ProfilePage /> },
          { path: "more", element: <MorePage /> },
          {
            element: <RequireAuth roles={["student"]} />,
            children: [
              { path: "schedule", element: <SchedulePage /> },
              { path: "notifications", element: <NotificationsPage /> },
              { path: "study", element: <ComingSoon title="Учёба" text="Дисциплины, баллы и светофор успеваемости появятся в модулях C3 и K1." /> },
              { path: "requests", element: <RequestsPage /> },
              { path: "requests/new", element: <NewRequestPage /> },
              { path: "requests/:id", element: <RequestDetailPage /> },
            ],
          },
          {
            element: <RequireAuth roles={["staff", "admin"]} />,
            children: [
              { path: "staff/requests", element: <StaffRequestsPage /> },
              { path: "staff/requests/:id", element: <StaffRequestPage /> },
            ],
          },
          { path: "*", element: <NotFoundPage /> },
        ],
      },
    ],
  },
];

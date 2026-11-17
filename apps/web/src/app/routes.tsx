import type { RouteObject } from "react-router";
import { AboutPage } from "@/features/about/AboutPage";
import { AssistantPage } from "@/features/assistant/AssistantPage";
import { LoginPage } from "@/features/auth/LoginPage";
import { RequireAuth } from "@/features/auth/RequireAuth";
import { CalendarPage } from "@/features/calendar/CalendarPage";
import {
  AdminComplaintPage,
  AdminComplaintsPage,
  ComplaintPage,
  ComplaintsPage,
  NewComplaintPage,
  TrackPage,
} from "@/features/complaints/ComplaintPages";
import { VerifyPage } from "@/features/documents/VerifyPage";
import { HomePage } from "@/features/home/HomePage";
import { NotificationsPage } from "@/features/notifications/NotificationsPage";
import { MorePage, NotFoundPage } from "@/features/placeholder/pages";
import { ProfilePage } from "@/features/profile/ProfilePage";
import { NewRequestPage } from "@/features/requests/NewRequestPage";
import { RequestDetailPage } from "@/features/requests/RequestDetailPage";
import { RequestsPage } from "@/features/requests/RequestsPage";
import { SchedulePage } from "@/features/schedule/SchedulePage";
import { SituationPage, SituationsPage } from "@/features/situations/SituationPages";
import { GradebookGroupsPage, GradebookPage } from "@/features/staff/GradebookPages";
import { AuditPage, StaffAnnouncementsPage } from "@/features/staff/StaffPages";
import { StaffRequestPage, StaffRequestsPage } from "@/features/staff/StaffRequestsPage";
import { DisciplinePage } from "@/features/study/DisciplinePage";
import { StudyPage } from "@/features/study/StudyPage";
import { ScanPage } from "@/features/studentid/ScanPage";
import { IdCheckPage, StudentIdPage } from "@/features/studentid/StudentIdPage";
import { AppShell } from "./AppShell";

// Public screens: login, document check (K2), student card check (K3),
// anonymous complaint tracking (K7) and «О проекте». Everything else sits
// behind RequireAuth (the server also redirects page requests without a session).
export const routes: RouteObject[] = [
  { path: "/login", element: <LoginPage /> },
  { path: "/verify/:token", element: <VerifyPage /> },
  { path: "/id/:token", element: <IdCheckPage /> },
  { path: "/track", element: <TrackPage /> },
  { path: "/about", element: <AboutPage /> },
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
              { path: "calendar", element: <CalendarPage /> },
              { path: "notifications", element: <NotificationsPage /> },
              { path: "study", element: <StudyPage /> },
              { path: "study/:id", element: <DisciplinePage /> },
              { path: "requests", element: <RequestsPage /> },
              { path: "requests/new", element: <NewRequestPage /> },
              { path: "requests/:id", element: <RequestDetailPage /> },
              { path: "assistant", element: <AssistantPage /> },
              { path: "student-id", element: <StudentIdPage /> },
              { path: "situations", element: <SituationsPage /> },
              { path: "situations/:slug", element: <SituationPage /> },
              { path: "complaints", element: <ComplaintsPage /> },
              { path: "complaints/new", element: <NewComplaintPage /> },
              { path: "complaints/:id", element: <ComplaintPage /> },
            ],
          },
          {
            element: <RequireAuth roles={["staff", "admin"]} />,
            children: [
              { path: "staff/requests", element: <StaffRequestsPage /> },
              { path: "staff/requests/:id", element: <StaffRequestPage /> },
              { path: "staff/grades", element: <GradebookGroupsPage /> },
              { path: "staff/grades/:id", element: <GradebookPage /> },
              { path: "staff/announcements", element: <StaffAnnouncementsPage /> },
              { path: "staff/check", element: <ScanPage /> },
            ],
          },
          {
            element: <RequireAuth roles={["admin"]} />,
            children: [
              { path: "admin/complaints", element: <AdminComplaintsPage /> },
              { path: "admin/complaints/:id", element: <AdminComplaintPage /> },
              { path: "admin/audit", element: <AuditPage /> },
            ],
          },
          { path: "*", element: <NotFoundPage /> },
        ],
      },
    ],
  },
];

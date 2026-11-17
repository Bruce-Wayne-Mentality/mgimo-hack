import { lazy } from "react";
import type { RouteObject } from "react-router";
import { LoginPage } from "@/features/auth/LoginPage";
import { RequireAuth } from "@/features/auth/RequireAuth";
import { HomePage } from "@/features/home/HomePage";
import { MorePage, NotFoundPage } from "@/features/placeholder/pages";
import { AppShell } from "./AppShell";
import { Lazy } from "./Lazy";

// Screens load on demand: the first visit downloads only login, shell and home.
const AboutPage = lazy(() => import("@/features/about/AboutPage").then((module) => ({ default: module.AboutPage })));
const AssistantPage = lazy(() => import("@/features/assistant/AssistantPage").then((module) => ({ default: module.AssistantPage })));
const BookingPage = lazy(() => import("@/features/booking/BookingPage").then((module) => ({ default: module.BookingPage })));
const CalendarPage = lazy(() => import("@/features/calendar/CalendarPage").then((module) => ({ default: module.CalendarPage })));
const ComplaintPage = lazy(() => import("@/features/complaints/ComplaintPages").then((module) => ({ default: module.ComplaintPage })));
const ComplaintsPage = lazy(() => import("@/features/complaints/ComplaintPages").then((module) => ({ default: module.ComplaintsPage })));
const NewComplaintPage = lazy(() => import("@/features/complaints/ComplaintPages").then((module) => ({ default: module.NewComplaintPage })));
const StaffComplaintsPage = lazy(() => import("@/features/complaints/StaffComplaintPages").then((module) => ({ default: module.StaffComplaintsPage })));
const StaffComplaintPage = lazy(() => import("@/features/complaints/StaffComplaintPages").then((module) => ({ default: module.StaffComplaintPage })));
const ModerationPage = lazy(() => import("@/features/complaints/StaffComplaintPages").then((module) => ({ default: module.ModerationPage })));
const VerifyPage = lazy(() => import("@/features/documents/VerifyPage").then((module) => ({ default: module.VerifyPage })));
const NotificationsPage = lazy(() => import("@/features/notifications/NotificationsPage").then((module) => ({ default: module.NotificationsPage })));
const ProfilePage = lazy(() => import("@/features/profile/ProfilePage").then((module) => ({ default: module.ProfilePage })));
const NewRequestPage = lazy(() => import("@/features/requests/NewRequestPage").then((module) => ({ default: module.NewRequestPage })));
const RequestDetailPage = lazy(() => import("@/features/requests/RequestDetailPage").then((module) => ({ default: module.RequestDetailPage })));
const RequestsPage = lazy(() => import("@/features/requests/RequestsPage").then((module) => ({ default: module.RequestsPage })));
const SchedulePage = lazy(() => import("@/features/schedule/SchedulePage").then((module) => ({ default: module.SchedulePage })));
const SituationPage = lazy(() => import("@/features/situations/SituationPages").then((module) => ({ default: module.SituationPage })));
const SituationsPage = lazy(() => import("@/features/situations/SituationPages").then((module) => ({ default: module.SituationsPage })));
const GradebookGroupsPage = lazy(() => import("@/features/staff/GradebookPages").then((module) => ({ default: module.GradebookGroupsPage })));
const GradebookPage = lazy(() => import("@/features/staff/GradebookPages").then((module) => ({ default: module.GradebookPage })));
const ScheduleEditorPage = lazy(() => import("@/features/staff/ScheduleEditorPage").then((module) => ({ default: module.ScheduleEditorPage })));
const AuditPage = lazy(() => import("@/features/staff/StaffPages").then((module) => ({ default: module.AuditPage })));
const StaffAnnouncementsPage = lazy(() => import("@/features/staff/StaffPages").then((module) => ({ default: module.StaffAnnouncementsPage })));
const StaffRequestPage = lazy(() => import("@/features/staff/StaffRequestsPage").then((module) => ({ default: module.StaffRequestPage })));
const StaffRequestsPage = lazy(() => import("@/features/staff/StaffRequestsPage").then((module) => ({ default: module.StaffRequestsPage })));
const DisciplinePage = lazy(() => import("@/features/study/DisciplinePage").then((module) => ({ default: module.DisciplinePage })));
const StudyPage = lazy(() => import("@/features/study/StudyPage").then((module) => ({ default: module.StudyPage })));
const ScanPage = lazy(() => import("@/features/studentid/ScanPage").then((module) => ({ default: module.ScanPage })));
const IdCheckPage = lazy(() => import("@/features/studentid/StudentIdPage").then((module) => ({ default: module.IdCheckPage })));
const StudentIdPage = lazy(() => import("@/features/studentid/StudentIdPage").then((module) => ({ default: module.StudentIdPage })));

// Public screens: login, document check (K2), student card check (K3) and «О проекте». Everything else sits
// behind RequireAuth (the server also redirects page requests without a session).
export const routes: RouteObject[] = [
  { path: "/login", element: <LoginPage /> },
  { path: "/verify/:token", element: <Lazy><VerifyPage /></Lazy> },
  { path: "/id/:token", element: <Lazy><IdCheckPage /></Lazy> },
  { path: "/about", element: <Lazy><AboutPage /></Lazy> },
  {
    element: <RequireAuth />,
    children: [
      {
        element: <AppShell />,
        children: [
          { index: true, element: <HomePage /> },
          { path: "profile", element: <Lazy><ProfilePage /></Lazy> },
          { path: "more", element: <MorePage /> },
          { path: "booking", element: <Lazy><BookingPage /></Lazy> },
          {
            element: <RequireAuth roles={["student"]} />,
            children: [
              { path: "schedule", element: <Lazy><SchedulePage /></Lazy> },
              { path: "calendar", element: <Lazy><CalendarPage /></Lazy> },
              { path: "notifications", element: <Lazy><NotificationsPage /></Lazy> },
              { path: "study", element: <Lazy><StudyPage /></Lazy> },
              { path: "study/:id", element: <Lazy><DisciplinePage /></Lazy> },
              { path: "requests", element: <Lazy><RequestsPage /></Lazy> },
              { path: "requests/new", element: <Lazy><NewRequestPage /></Lazy> },
              { path: "requests/:id", element: <Lazy><RequestDetailPage /></Lazy> },
              { path: "assistant", element: <Lazy><AssistantPage /></Lazy> },
              { path: "student-id", element: <Lazy><StudentIdPage /></Lazy> },
              { path: "situations", element: <Lazy><SituationsPage /></Lazy> },
              { path: "situations/:slug", element: <Lazy><SituationPage /></Lazy> },
              { path: "complaints", element: <Lazy><ComplaintsPage /></Lazy> },
              { path: "complaints/new", element: <Lazy><NewComplaintPage /></Lazy> },
              { path: "complaints/:id", element: <Lazy><ComplaintPage /></Lazy> },
            ],
          },
          {
            element: <RequireAuth roles={["staff", "admin"]} />,
            children: [
              { path: "staff/requests", element: <Lazy><StaffRequestsPage /></Lazy> },
              { path: "staff/requests/:id", element: <Lazy><StaffRequestPage /></Lazy> },
              { path: "staff/grades", element: <Lazy><GradebookGroupsPage /></Lazy> },
              { path: "staff/grades/:id", element: <Lazy><GradebookPage /></Lazy> },
              { path: "staff/announcements", element: <Lazy><StaffAnnouncementsPage /></Lazy> },
              { path: "staff/check", element: <Lazy><ScanPage /></Lazy> },
              { path: "staff/schedule", element: <Lazy><ScheduleEditorPage /></Lazy> },
              { path: "staff/complaints", element: <Lazy><StaffComplaintsPage /></Lazy> },
              { path: "staff/complaints/:id", element: <Lazy><StaffComplaintPage /></Lazy> },
              { path: "staff/moderation", element: <Lazy><ModerationPage /></Lazy> },
            ],
          },
          {
            element: <RequireAuth roles={["admin"]} />,
            children: [
              { path: "admin/audit", element: <Lazy><AuditPage /></Lazy> },
            ],
          },
          { path: "*", element: <NotFoundPage /> },
        ],
      },
    ],
  },
];

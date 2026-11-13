export type Role = "student" | "staff" | "admin";

export type User = {
  id: string;
  login: string;
  role: Role;
  role_label: string;
  display_name: string;
};

export type SessionInfo = { user: User; csrf_token: string };

export type DemoAccount = { login: string; password: string; description: string };

export type StudentProfile = {
  kind: "student";
  full_name: string;
  faculty: string;
  program: { code: string; title: string };
  course: number;
  group: string;
  study_form: string;
  status: string;
  record_book_no: string;
  contacts: { email: string; phone: string | null };
};

export type StaffProfile = {
  kind: "staff" | "admin";
  full_name: string;
  position?: string;
  faculty?: string | null;
  role: string;
};

export type Profile = StudentProfile | StaffProfile;

export type Lesson = {
  id: string;
  source_lesson_id: string;
  title: string;
  kind: string | null;
  date: string;
  starts_at: string;
  ends_at: string;
  teachers: string[];
  room: string | null;
  building: string | null;
};

export type Schedule = { start: string; finish: string; timezone: string; lessons: Lesson[] };

export type Notification = {
  id: number;
  title: string;
  body: string;
  created_at: string;
  read_at: string | null;
};

export type NotificationPage = { items: Notification[]; unread_count: number; next_before: number | null };

export type NotificationSettings = { enabled: boolean };

export type TelegramStatus = { linked: boolean; username: string | null };

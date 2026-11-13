import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router";
import { ApiError, api, setCsrfToken } from "./api";
import { disconnectPush } from "./push";
import type { SessionInfo } from "./types";

export const SESSION_KEY = ["auth", "session"] as const;

/** Current session or null; a 401 means "not signed in", not an error. */
export async function fetchSession(): Promise<SessionInfo | null> {
  try {
    const session = await api<SessionInfo>("/api/auth/me", { quiet401: true });
    setCsrfToken(session.csrf_token);
    return session;
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      setCsrfToken(null);
      return null;
    }
    throw error;
  }
}

export function useSession() {
  return useQuery({ queryKey: SESSION_KEY, queryFn: fetchSession, staleTime: 60_000, retry: 1 });
}

export type LoginInput = { login: string; password: string; remember: boolean };

export function useLogin() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: LoginInput) => api<SessionInfo>("/api/auth/login", { method: "POST", body: input, quiet401: true }),
    onSuccess: (session) => {
      setCsrfToken(session.csrf_token);
      client.removeQueries({ predicate: (query) => query.queryKey[0] !== SESSION_KEY[0] });
      client.setQueryData(SESSION_KEY, session);
    },
  });
}

export function useLogout() {
  const client = useQueryClient();
  const navigate = useNavigate();
  return useMutation({
    mutationFn: async (everywhere: boolean) => {
      await disconnectPush();
      await api<null>(everywhere ? "/api/auth/logout-all" : "/api/auth/logout", { method: "POST" });
    },
    onSettled: () => {
      setCsrfToken(null);
      client.clear();
      client.setQueryData(SESSION_KEY, null);
      navigate("/login", { replace: true });
    },
  });
}

/** Only same-site relative paths, mirroring the server's safe_next(). */
export function safeNext(value: string | null): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.includes("\\")) return "/";
  if (value === "/login" || value.startsWith("/login?")) return "/";
  return value;
}

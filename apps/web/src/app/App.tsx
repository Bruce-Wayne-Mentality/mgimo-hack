import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { createBrowserRouter, RouterProvider } from "react-router";
import { ApiError, setUnauthorizedHandler } from "@/lib/api";
import { SESSION_KEY } from "@/lib/auth";
import { routes } from "./routes";

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: (count, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 2,
        refetchOnWindowFocus: true,
      },
    },
  });
}

/** Any 401 from the API means the session ended: drop it so the guard sends the user to /login. */
export function useSessionExpiry(client: QueryClient): void {
  useEffect(() => {
    setUnauthorizedHandler(() => {
      if (client.getQueryData(SESSION_KEY)) {
        client.clear();
        client.setQueryData(SESSION_KEY, null);
      }
    });
    return () => setUnauthorizedHandler(null);
  }, [client]);
}

export function App() {
  const [client] = useState(createQueryClient);
  const [router] = useState(() => createBrowserRouter(routes));
  useSessionExpiry(client);
  return (
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}

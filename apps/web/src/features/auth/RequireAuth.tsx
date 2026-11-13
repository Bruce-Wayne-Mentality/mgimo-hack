import { Navigate, Outlet, useLocation } from "react-router";
import { ErrorState, Skeleton } from "@/components/ui";
import { useSession } from "@/lib/auth";
import type { Role } from "@/lib/types";

/** Route guard: nothing below renders until the session is confirmed. */
export function RequireAuth({ roles }: { roles?: Role[] }) {
  const session = useSession();
  const location = useLocation();

  if (session.isPending) {
    return (
      <div className="mx-auto flex max-w-3xl flex-col gap-4 p-4" aria-busy="true" aria-label="Загрузка">
        <Skeleton className="h-10 w-48" />
        <Skeleton className="h-32" />
        <Skeleton className="h-32" />
      </div>
    );
  }
  if (session.isError) {
    return (
      <div className="mx-auto max-w-md p-4">
        <ErrorState message="Не удалось проверить вход. Проверьте связь." onRetry={() => session.refetch()} />
      </div>
    );
  }
  if (!session.data) {
    const target = location.pathname + location.search;
    const next = target === "/" ? "" : `?next=${encodeURIComponent(target)}`;
    return <Navigate to={`/login${next}`} replace />;
  }
  if (roles && !roles.includes(session.data.user.role)) return <Navigate to="/" replace />;
  return <Outlet />;
}

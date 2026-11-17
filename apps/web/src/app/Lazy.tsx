import { Suspense, type ReactNode } from "react";
import { Skeleton } from "@/components/ui";

/** Placeholder while a screen's code chunk downloads. */
export function Lazy({ children }: { children: ReactNode }) {
  return (
    <Suspense
      fallback={
        <div className="flex flex-col gap-4" aria-busy="true" aria-label="Загрузка">
          <Skeleton className="h-10 w-48" />
          <Skeleton className="h-40" />
        </div>
      }
    >
      {children}
    </Suspense>
  );
}

"use client";

import { usePathname } from "next/navigation";
import { ThemeProvider as NextThemesProvider } from "next-themes";

import { WorkspaceStyleProvider } from "@/core/appearance/provider";

export function ThemeProvider({
  children,
  ...props
}: React.ComponentProps<typeof NextThemesProvider>) {
  const pathname = usePathname();
  return (
    <NextThemesProvider
      {...props}
      forcedTheme={pathname === "/" ? "dark" : undefined}
    >
      <WorkspaceStyleProvider>{children}</WorkspaceStyleProvider>
    </NextThemesProvider>
  );
}

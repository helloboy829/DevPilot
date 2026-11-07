"use client";

import { usePathname } from "next/navigation";
import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import {
  normalizeWorkspaceStyle,
  WORKSPACE_STYLE_STORAGE_KEY,
  type WorkspaceStyle,
} from "./styles";

const StyleContext = createContext<{
  style: WorkspaceStyle;
  setStyle: (style: WorkspaceStyle) => void;
} | null>(null);

export function WorkspaceStyleProvider({ children }: { children: ReactNode }) {
  const [style, updateStyle] = useState<WorkspaceStyle>("console");
  const pathname = usePathname();
  useEffect(() => {
    try {
      updateStyle(
        normalizeWorkspaceStyle(
          localStorage.getItem(WORKSPACE_STYLE_STORAGE_KEY),
        ),
      );
    } catch {
      /* Browser policy may prohibit storage. */
    }
    const onStorage = (event: StorageEvent) => {
      if (event.key === WORKSPACE_STYLE_STORAGE_KEY || event.key === null)
        updateStyle(normalizeWorkspaceStyle(event.newValue));
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);
  useEffect(() => {
    if (pathname === "/workspace" || pathname.startsWith("/workspace/"))
      document.documentElement.dataset.workspaceStyle = style;
    else delete document.documentElement.dataset.workspaceStyle;
    return () => {
      delete document.documentElement.dataset.workspaceStyle;
    };
  }, [pathname, style]);
  const setStyle = (value: WorkspaceStyle) => {
    const next = normalizeWorkspaceStyle(value);
    updateStyle(next);
    try {
      localStorage.setItem(WORKSPACE_STYLE_STORAGE_KEY, next);
    } catch {
      /* Keep the in-memory selection usable. */
    }
  };
  return (
    <StyleContext.Provider value={{ style, setStyle }}>
      {children}
    </StyleContext.Provider>
  );
}

export function useWorkspaceStyle() {
  const value = useContext(StyleContext);
  if (!value) throw new Error("WorkspaceStyleProvider is required");
  return value;
}

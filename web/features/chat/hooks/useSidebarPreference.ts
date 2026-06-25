import { useEffect, useLayoutEffect, useState } from "react";

export const SIDEBAR_COLLAPSED_STORAGE_KEY = "nanobot:web:sidebar-collapsed";

export type SidebarPreference = {
  isCollapsed: boolean;
  isInitialized: boolean;
  collapse: () => void;
  expand: () => void;
};

const useIsomorphicLayoutEffect =
  typeof window === "undefined" ? useEffect : useLayoutEffect;

export function useSidebarPreference(): SidebarPreference {
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [isInitialized, setIsInitialized] = useState(false);

  useIsomorphicLayoutEffect(() => {
    try {
      setIsCollapsed(
        window.localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE_KEY) === "true"
      );
    } catch {
      setIsCollapsed(false);
    } finally {
      setIsInitialized(true);
    }
  }, []);

  function updatePreference(collapsed: boolean) {
    setIsCollapsed(collapsed);

    try {
      window.localStorage.setItem(
        SIDEBAR_COLLAPSED_STORAGE_KEY,
        String(collapsed)
      );
    } catch {
      // Keep the in-memory preference when browser storage is unavailable.
    }
  }

  return {
    isCollapsed,
    isInitialized,
    collapse: () => updatePreference(true),
    expand: () => updatePreference(false)
  };
}

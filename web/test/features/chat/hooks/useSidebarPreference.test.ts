import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  SIDEBAR_COLLAPSED_STORAGE_KEY,
  useSidebarPreference
} from "@/features/chat/hooks/useSidebarPreference";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useSidebarPreference", () => {
  it("defaults to expanded when no preference exists", () => {
    const { result } = renderHook(() => useSidebarPreference());

    expect(result.current.isCollapsed).toBe(false);
    expect(result.current.isInitialized).toBe(true);
  });

  it.each([
    ["true", true],
    ["false", false],
    ["invalid", false]
  ])("parses stored value %s", (storedValue, expectedCollapsed) => {
    window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, storedValue);

    const { result } = renderHook(() => useSidebarPreference());

    expect(result.current.isCollapsed).toBe(expectedCollapsed);
    expect(result.current.isInitialized).toBe(true);
  });

  it("falls back safely when reading storage throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("storage unavailable");
    });

    const { result } = renderHook(() => useSidebarPreference());

    expect(result.current.isCollapsed).toBe(false);
    expect(result.current.isInitialized).toBe(true);
  });

  it("collapses and persists the preference", () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const { result } = renderHook(() => useSidebarPreference());

    act(() => result.current.collapse());

    expect(result.current.isCollapsed).toBe(true);
    expect(setItem).toHaveBeenCalledWith(SIDEBAR_COLLAPSED_STORAGE_KEY, "true");
  });

  it("expands and persists the preference", () => {
    window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, "true");
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const { result } = renderHook(() => useSidebarPreference());

    act(() => result.current.expand());

    expect(result.current.isCollapsed).toBe(false);
    expect(setItem).toHaveBeenCalledWith(SIDEBAR_COLLAPSED_STORAGE_KEY, "false");
  });

  it("updates memory when writing storage throws", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("storage unavailable");
    });
    const { result } = renderHook(() => useSidebarPreference());

    expect(() => act(() => result.current.collapse())).not.toThrow();
    expect(result.current.isCollapsed).toBe(true);
  });
});

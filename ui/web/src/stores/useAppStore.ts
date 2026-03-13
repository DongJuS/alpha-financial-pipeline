/**
 * ui/src/stores/useAppStore.ts — Zustand 전역 UI 상태
 */
import { create } from "zustand";

interface AppState {
  sidebarOpen: boolean;
  toggleSidebar: () => void;

  isDarkMode: boolean;
  toggleDarkMode: () => void;
}

export const useAppStore = create<AppState>((set) => ({
  sidebarOpen: true,
  toggleSidebar: () =>
    set((state) => ({ sidebarOpen: !state.sidebarOpen })),

  isDarkMode: false,
  toggleDarkMode: () =>
    set((state) => ({ isDarkMode: !state.isDarkMode })),
}));

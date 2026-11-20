import { create } from "zustand";

interface ExplorerState {
  selectedId: string | null;
  hiddenIds: Record<string, true>;
  opacity: number;
  showDetections: boolean;
  // Default 0.5: on the NAIP airport samples almost all false positives scored below it.
  minConfidence: number;
  hiddenClasses: Record<string, true>;
  select: (id: string | null) => void;
  toggleVisible: (id: string) => void;
  setOpacity: (opacity: number) => void;
  setShowDetections: (show: boolean) => void;
  setMinConfidence: (value: number) => void;
  toggleClass: (className: string) => void;
}

function toggle(record: Record<string, true>, key: string): Record<string, true> {
  const next = { ...record };
  if (next[key]) delete next[key];
  else next[key] = true;
  return next;
}

/** Map explorer UI state. Images and detection classes are visible unless hidden. */
export const useExplorerStore = create<ExplorerState>((set) => ({
  selectedId: null,
  hiddenIds: {},
  opacity: 1,
  showDetections: true,
  minConfidence: 0.5,
  hiddenClasses: {},
  select: (id) => set({ selectedId: id }),
  toggleVisible: (id) => set((state) => ({ hiddenIds: toggle(state.hiddenIds, id) })),
  setOpacity: (opacity) => set({ opacity }),
  setShowDetections: (showDetections) => set({ showDetections }),
  setMinConfidence: (minConfidence) => set({ minConfidence }),
  toggleClass: (className) =>
    set((state) => ({ hiddenClasses: toggle(state.hiddenClasses, className) })),
}));

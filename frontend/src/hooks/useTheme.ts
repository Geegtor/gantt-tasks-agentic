import { useState } from "react";

const STORAGE_KEY = "gantt-theme";

function readDarkFromDOM(): boolean {
  // Source of truth is the <html> class that was set by the inline script in index.html.
  if (typeof document === "undefined") return false;
  return document.documentElement.classList.contains("dark");
}

export function useTheme() {
  // Initialise from the DOM class (already set correctly before React hydrates).
  const [isDark, setIsDark] = useState<boolean>(readDarkFromDOM);

  function toggle() {
    const next = !isDark;
    // Apply synchronously — no useEffect delay, no flash.
    if (next) {
      document.documentElement.classList.add("dark");
    } else {
      document.documentElement.classList.remove("dark");
    }
    try {
      localStorage.setItem(STORAGE_KEY, next ? "dark" : "light");
    } catch (_) {}
    setIsDark(next);
  }

  return { isDark, toggle };
}

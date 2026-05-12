import { createContext, useContext, useState, type ReactNode } from "react";
import { translations, type Lang, type T } from "./translations";

const STORAGE_KEY = "gantt-lang";

function getInitialLang(): Lang {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "ru" || stored === "en") return stored;
    return navigator.language.toLowerCase().startsWith("ru") ? "ru" : "en";
  } catch {
    return "en";
  }
}

interface I18nContextValue {
  lang: Lang;
  t: T;
  toggleLang: () => void;
}

const I18nContext = createContext<I18nContextValue>({
  lang: "en",
  t: translations.en,
  toggleLang: () => {},
});

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLang] = useState<Lang>(getInitialLang);

  function toggleLang() {
    const next: Lang = lang === "en" ? "ru" : "en";
    setLang(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* ignore */
    }
  }

  return (
    <I18nContext.Provider value={{ lang, t: translations[lang], toggleLang }}>
      {children}
    </I18nContext.Provider>
  );
}

export function useI18n(): I18nContextValue {
  return useContext(I18nContext);
}

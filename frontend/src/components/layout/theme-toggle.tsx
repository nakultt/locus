"use client";

import { useEffect, useState } from "react";
import { Monitor, Moon, Sun } from "lucide-react";
import { cn } from "@/lib/utils";

type Theme = "light" | "dark" | "system";

/**
 * Light / System / Dark, as a three-way segmented control.
 *
 * The two-state toggle it replaces could not express "follow my OS", so a user
 * whose machine switches at sunset had to switch the app by hand as well. The
 * three states map exactly onto what is stored: `"light"`, `"dark"`, or no key
 * at all — which is why System is the absence of a value rather than a literal,
 * and why the boot script in `app/layout.tsx` reads it the same way.
 */
export function ThemeToggle({ className }: { className?: string }) {
  const [theme, setTheme] = useState<Theme>("system");

  // Read after mount, never during render: the server has no localStorage, and
  // an initialiser that reached for it would disagree with the markup it sent.
  useEffect(() => {
    const saved = localStorage.getItem("theme");
    setTheme(saved === "dark" || saved === "light" ? saved : "system");
  }, []);

  // While on System, follow the OS as it changes rather than only at load.
  useEffect(() => {
    if (theme !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => document.documentElement.classList.toggle("dark", mq.matches);
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, [theme]);

  const choose = (next: Theme) => {
    setTheme(next);
    if (next === "system") {
      localStorage.removeItem("theme");
      document.documentElement.classList.toggle(
        "dark",
        window.matchMedia("(prefers-color-scheme: dark)").matches
      );
    } else {
      localStorage.setItem("theme", next);
      document.documentElement.classList.toggle("dark", next === "dark");
    }
  };

  const options = [
    { value: "light" as const, icon: Sun, label: "Light" },
    { value: "system" as const, icon: Monitor, label: "System" },
    { value: "dark" as const, icon: Moon, label: "Dark" },
  ];

  return (
    <div
      role="group"
      aria-label="Colour theme"
      className={cn(
        "inline-flex items-center gap-0.5 rounded-pill border border-line bg-surface-2 p-0.5",
        className
      )}
    >
      {options.map(({ value, icon: Icon, label }) => (
        <button
          key={value}
          type="button"
          aria-label={label}
          aria-pressed={theme === value}
          title={label}
          onClick={() => choose(value)}
          className={cn(
            "flex size-7 items-center justify-center rounded-pill transition-colors",
            theme === value
              ? "bg-surface text-ink shadow-sm"
              : "text-subtle hover:text-ink"
          )}
        >
          <Icon className="size-3.5" />
        </button>
      ))}
    </div>
  );
}

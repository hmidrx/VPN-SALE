"use client";
import React from "react";
import type { RuntimeConfiguration } from "./runtime-types";
import { fallbackRuntimeConfiguration } from "./configuration";

const RuntimeConfigurationContext = React.createContext<RuntimeConfiguration>(fallbackRuntimeConfiguration);

function applyTheme(configuration: RuntimeConfiguration): void {
  const root = document.documentElement;
  const mode = root.dataset.theme === "light" ? "light" : "dark";
  const theme = configuration.theme[mode];
  const set = (name: string, value: string | undefined) => { if (value) root.style.setProperty(name, value); };
  set("--color-canvas", theme.page_color);
  set("--color-surface", theme.surface_color);
  set("--color-surface-raised", theme.surface_color);
  set("--color-surface-interactive", theme.surface_color);
  set("--color-text", theme.text_primary_color);
  set("--color-text-muted", theme.text_secondary_color);
  set("--color-border", theme.border_color);
  set("--color-primary", theme.primary_color);
  set("--color-focus", theme.focus_ring_color);
}

export function RuntimeConfigurationProvider({ value, children }: { value: RuntimeConfiguration; children: React.ReactNode }): React.ReactElement {
  React.useEffect(() => {
    applyTheme(value);
    const observer = new MutationObserver(() => applyTheme(value));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, [value]);
  return <RuntimeConfigurationContext.Provider value={value}>{children}</RuntimeConfigurationContext.Provider>;
}

export function useRuntimeConfiguration(): RuntimeConfiguration {
  return React.useContext(RuntimeConfigurationContext);
}

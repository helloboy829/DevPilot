"use client";

import { Check } from "lucide-react";

import { useWorkspaceStyle } from "@/core/appearance/provider";
import { WORKSPACE_STYLES } from "@/core/appearance/styles";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

export function WorkspaceStyleGallery() {
  const { style, setStyle } = useWorkspaceStyle();
  const { locale } = useI18n();
  return (
    <div
      role="radiogroup"
      aria-label={locale === "zh-CN" ? "工作台风格" : "Workspace style"}
      className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3"
    >
      {WORKSPACE_STYLES.map((item, index) => (
        <button
          key={item.id}
          type="button"
          role="radio"
          aria-label={item.name[locale]}
          aria-checked={style === item.id}
          tabIndex={style === item.id ? 0 : -1}
          onClick={() => setStyle(item.id)}
          onKeyDown={(event) => {
            const keys = [
              "ArrowRight",
              "ArrowDown",
              "ArrowLeft",
              "ArrowUp",
              "Home",
              "End",
            ];
            if (!keys.includes(event.key)) return;
            event.preventDefault();
            const offset =
              event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : -1;
            const next =
              event.key === "Home"
                ? 0
                : event.key === "End"
                  ? WORKSPACE_STYLES.length - 1
                  : (index + offset + WORKSPACE_STYLES.length) %
                    WORKSPACE_STYLES.length;
            const target = WORKSPACE_STYLES[next]!;
            setStyle(target.id);
            event.currentTarget.parentElement
              ?.querySelectorAll<HTMLButtonElement>("[role=radio]")
              [next]?.focus();
          }}
          className={cn(
            "focus-visible:ring-ring flex min-w-0 flex-col gap-3 rounded-lg border p-3 text-left focus-visible:ring-2 focus-visible:outline-none",
            style === item.id
              ? "border-primary ring-primary/20 ring-2"
              : "hover:border-primary/50",
          )}
        >
          <div
            aria-hidden="true"
            className="flex h-20 w-full overflow-hidden rounded-md border"
            style={{
              backgroundColor: item.swatches[0],
              borderColor: item.swatches[3] + "26",
            }}
          >
            <div
              className="flex w-1/4 flex-col gap-2 border-r p-2"
              style={{ borderColor: item.swatches[3] + "26" }}
            >
              {[0, 1, 2].map((line) => (
                <span
                  key={line}
                  className="h-1.5 rounded"
                  style={{
                    backgroundColor: item.swatches[line === 0 ? 2 : 3],
                    opacity: line === 0 ? 1 : 0.2,
                  }}
                />
              ))}
            </div>
            <div className="flex flex-1 flex-col gap-2 p-2">
              <div
                className="h-1.5 w-1/2 rounded"
                style={{ backgroundColor: item.swatches[3] }}
              />
              <div className="flex flex-1 gap-1">
                {[0, 1, 2].map((panel) => (
                  <div
                    key={panel}
                    className="flex-1 rounded border p-1.5"
                    style={{
                      backgroundColor: item.swatches[1],
                      borderColor: item.swatches[3] + "26",
                    }}
                  >
                    <div
                      className="h-2 w-2 rounded-sm"
                      style={{ backgroundColor: item.swatches[2] }}
                    />
                  </div>
                ))}
              </div>
            </div>
          </div>
          <div className="flex items-center justify-between gap-2 text-sm font-semibold">
            <span>{item.name[locale]}</span>
            {style === item.id && (
              <Check
                aria-hidden="true"
                className="text-primary size-4 shrink-0"
              />
            )}
          </div>
          <p className="text-muted-foreground text-xs leading-relaxed">
            {item.description[locale]}
          </p>
        </button>
      ))}
    </div>
  );
}

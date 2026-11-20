"use client";

import Link from "next/link";

import { BrandLogo } from "@/components/brand-logo";
import { SidebarTrigger, useSidebar } from "@/components/ui/sidebar";
import { env } from "@/env";
import { cn } from "@/lib/utils";

export function WorkspaceHeader({ className }: { className?: string }) {
  const { state } = useSidebar();
  return (
    <>
      <div
        className={cn(
          "group/workspace-header flex h-12 flex-col justify-center",
          className,
        )}
      >
        {state === "collapsed" ? (
          <div className="group-has-data-[collapsible=icon]/sidebar-wrapper:-translate-y flex w-full cursor-pointer items-center justify-center">
            <BrandLogo
              size="compact"
              alt="DevPilot"
              className="group-hover/workspace-header:hidden"
            />
            <SidebarTrigger className="hidden pl-2 group-hover/workspace-header:block" />
          </div>
        ) : (
          <div className="flex items-center justify-between gap-2">
            {env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" ? (
              <Link
                href="/"
                aria-label="DevPilot home"
                className="text-primary ml-2 flex items-center gap-2 font-serif"
              >
                <BrandLogo size="compact" alt="" />
                DevPilot
              </Link>
            ) : (
              <Link
                href="/workspace/evaluations"
                aria-label="DevPilot workspace"
                className="text-primary ml-2 flex items-center gap-2 font-semibold tracking-tight"
              >
                <BrandLogo size="compact" alt="" />
                DevPilot
              </Link>
            )}
            <SidebarTrigger />
          </div>
        )}
      </div>
    </>
  );
}

"use client";

import {
  BotIcon,
  Database,
  LayoutDashboard,
  CalendarClock,
  FileText,
  FlaskConical,
  MessagesSquare,
  Settings2,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import {
  SidebarGroup,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { useAgentsApiEnabled } from "@/core/agents";
import { useI18n } from "@/core/i18n/hooks";

export function WorkspaceNavChatList() {
  const { t, locale } = useI18n();
  const pathname = usePathname();
  const { enabled: agentsEnabled, isLoading: agentsLoading } =
    useAgentsApiEnabled();
  return (
    <SidebarGroup className="pt-1">
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname === "/workspace/evaluations"}
            asChild
          >
            <Link href="/workspace/evaluations">
              <LayoutDashboard />
              <span>
                {locale === "zh-CN" ? "评测工作台" : "Evaluation workbench"}
              </span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname.startsWith("/workspace/datasets")}
            asChild
          >
            <Link className="text-muted-foreground" href="/workspace/datasets">
              <Database />
              <span>
                {locale === "zh-CN" ? "项目与数据" : "Projects & datasets"}
              </span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname.startsWith("/workspace/component-tests")}
            asChild
          >
            <Link
              className="text-muted-foreground"
              href="/workspace/component-tests"
            >
              <FlaskConical />
              <span>{t.sidebar.componentTests}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname.startsWith("/workspace/evaluation-schedules")}
            asChild
          >
            <Link
              className="text-muted-foreground"
              href="/workspace/evaluation-schedules"
            >
              <CalendarClock />
              <span>{t.sidebar.scheduledEvaluations}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname.startsWith("/workspace/reports")}
            asChild
          >
            <Link className="text-muted-foreground" href="/workspace/reports">
              <FileText />
              <span>{t.sidebar.reports}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname.startsWith("/workspace/models")}
            asChild
          >
            <Link className="text-muted-foreground" href="/workspace/models">
              <Settings2 />
              <span>
                {locale === "zh-CN" ? "模型与分工" : "Models & roles"}
              </span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton isActive={pathname === "/workspace/chats"} asChild>
            <Link className="text-muted-foreground" href="/workspace/chats">
              <MessagesSquare />
              <span>{t.sidebar.chats}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
        {!agentsLoading && agentsEnabled && (
          <SidebarMenuItem>
            <SidebarMenuButton
              isActive={pathname.startsWith("/workspace/agents")}
              asChild
            >
              <Link className="text-muted-foreground" href="/workspace/agents">
                <BotIcon />
                <span>{t.sidebar.agents}</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        )}
      </SidebarMenu>
    </SidebarGroup>
  );
}

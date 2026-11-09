"use client";

import {
  BotIcon,
  CalendarClock,
  Database,
  FileText,
  FlaskConical,
  LayoutDashboard,
  MessagesSquare,
  Settings2,
  GitCompareArrows,
  ClipboardCheck,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import {
  SidebarGroup,
  SidebarGroupLabel,
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
  const zh = locale === "zh-CN";
  const groups = [
    {
      label: zh ? "评测中心" : "Evaluation center",
      entries: [
        {
          path: "evaluations",
          label: zh ? "评测工作台" : "Evaluation workbench",
          icon: LayoutDashboard,
        },
        {
          path: "datasets",
          label: zh ? "项目与数据" : "Projects & datasets",
          icon: Database,
        },
        {
          path: "component-tests",
          label: t.sidebar.componentTests,
          icon: FlaskConical,
        },
        {
          path: "evaluation-schedules",
          label: t.sidebar.scheduledEvaluations,
          icon: CalendarClock,
        },
        {
          path: "retests",
          label: zh ? "整改复测" : "Remediation & retesting",
          icon: GitCompareArrows,
        },
        {
          path: "reviews",
          label: zh ? "独立复核" : "Independent review",
          icon: ClipboardCheck,
        },
        { path: "reports", label: t.sidebar.reports, icon: FileText },
        {
          path: "models",
          label: zh ? "模型与分工" : "Models & roles",
          icon: Settings2,
        },
      ],
    },
    {
      label: zh ? "智能协作" : "AI collaboration",
      entries: [
        { path: "chats", label: t.sidebar.chats, icon: MessagesSquare },
        ...(!agentsLoading && agentsEnabled
          ? [{ path: "agents", label: t.sidebar.agents, icon: BotIcon }]
          : []),
      ],
    },
  ];
  return (
    <nav aria-label={zh ? "工作台导航" : "Workspace navigation"}>
      {groups.map((group) => (
        <SidebarGroup key={group.label} className="pt-1">
          <SidebarGroupLabel>{group.label}</SidebarGroupLabel>
          <SidebarMenu>
            {group.entries.map(({ path, label, icon: Icon }) => {
              const href = `/workspace/${path}`;
              const active =
                pathname === href || pathname.startsWith(href + "/");
              return (
                <SidebarMenuItem key={path}>
                  <SidebarMenuButton asChild isActive={active} tooltip={label}>
                    <Link
                      href={href}
                      aria-current={active ? "page" : undefined}
                    >
                      <Icon />
                      <span>{label}</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              );
            })}
          </SidebarMenu>
        </SidebarGroup>
      ))}
    </nav>
  );
}

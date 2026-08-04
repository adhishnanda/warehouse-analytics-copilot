import type { ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";

import { AppSidebar } from "@/components/layout/AppSidebar";
import { ThemeToggle } from "@/components/layout/ThemeToggle";
import { Separator } from "@/components/ui/separator";
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";

const PAGE_TITLES: Record<string, string> = {
  "/ask": "Ask",
  "/monitoring": "Monitoring",
};

export function AppShell({ children }: { children: ReactNode }) {
  const location = useLocation();
  const title = PAGE_TITLES[location.pathname] ?? "Warehouse Copilot";

  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset>
        <header className="flex h-14 shrink-0 items-center gap-2 border-b px-4">
          <SidebarTrigger />
          <Separator orientation="vertical" className="mr-2 h-4" />
          <Link to="/" className="text-sm font-medium">
            {title}
          </Link>
          <div className="ml-auto flex items-center gap-1">
            <ThemeToggle />
          </div>
        </header>
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">{children}</div>
      </SidebarInset>
    </SidebarProvider>
  );
}

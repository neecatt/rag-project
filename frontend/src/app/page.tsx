import { AppShell } from "@/components/app-shell";
import { OverviewDashboard } from "@/components/overview-dashboard";

export default function HomePage() {
  return (
    <AppShell currentPath="/">
      <OverviewDashboard />
    </AppShell>
  );
}

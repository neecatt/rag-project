import { AppShell } from "@/components/app-shell";
import { SearchWorkspace } from "@/components/search-workspace";

export default function SearchPage() {
  return (
    <AppShell currentPath="/search">
      <SearchWorkspace />
    </AppShell>
  );
}

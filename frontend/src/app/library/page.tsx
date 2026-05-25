import { AppShell } from "@/components/app-shell";
import { DocumentLibrary } from "@/components/document-library";

export default function LibraryPage() {
  return (
    <AppShell currentPath="/library">
      <DocumentLibrary />
    </AppShell>
  );
}

import { AppShell } from "@/components/app-shell";
import { UploadWorkspace } from "@/components/upload-workspace";

export default function UploadPage() {
  return (
    <AppShell currentPath="/upload">
      <UploadWorkspace />
    </AppShell>
  );
}

import { AppShell } from "@/components/app-shell";
import { ChatWorkspace } from "@/components/chat-workspace";

export default function ChatPage() {
  return (
    <AppShell currentPath="/chat">
      <ChatWorkspace />
    </AppShell>
  );
}

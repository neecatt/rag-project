import Link from "next/link";
import { FolderOpen, LayoutDashboard, MessagesSquare, Search, Upload } from "lucide-react";
import { cn } from "@/lib/utils";

const navItems = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/upload", label: "Upload", icon: Upload },
  { href: "/library", label: "Library", icon: FolderOpen },
  { href: "/search", label: "Search", icon: Search },
  { href: "/chat", label: "Chat", icon: MessagesSquare },
];

export function AppShell({
  children,
  currentPath,
}: {
  children: React.ReactNode;
  currentPath: string;
}) {
  return (
    <div className="min-h-screen text-ink">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-[28rem] bg-halo" />
      <div className="pointer-events-none absolute inset-0 bg-grid bg-[size:22px_22px] opacity-40" />
      <div className="relative mx-auto flex min-h-screen max-w-7xl flex-col px-4 py-5 sm:px-6 lg:px-8">
        <header className="surface-glass mb-8 overflow-hidden rounded-[2rem] p-6 md:p-7">
          <div className="absolute inset-x-8 top-0 h-px bg-gradient-to-r from-transparent via-white/90 to-transparent" />
          <div className="relative flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
            <div className="max-w-2xl">
              <p className="text-[11px] uppercase tracking-[0.34em] text-slate-500">
              Enterprise Knowledge Assistant
              </p>
              <h1 className="mt-3 text-3xl font-semibold tracking-[-0.04em] text-slate-950 md:text-[2.7rem]">
                Grounded search, chat, and ingestion
              </h1>
              <p className="mt-3 max-w-xl text-sm leading-7 text-slate-600">
                A cleaner operating surface for document pipelines, retrieval, and citation-backed answers.
              </p>
            </div>
            <nav className="flex flex-wrap gap-2 md:max-w-[28rem] md:justify-end">
              {navItems.map(({ href, label, icon: Icon }, index) => (
                <Link
                  key={href}
                  href={href}
                  className={cn(
                    "inline-flex items-center gap-2 rounded-full border px-4 py-2.5 text-sm font-medium transition duration-200 hover:-translate-y-0.5",
                    currentPath === href
                      ? "border-sky-700 bg-[var(--accent)] text-white shadow-[0_18px_34px_-22px_rgba(15,108,189,0.9)] ring-1 ring-white/70"
                      : "surface-soft border-white/70 text-slate-700 hover:border-sky-200 hover:bg-white/95 hover:text-slate-950",
                  )}
                  style={{ animationDelay: `${index * 70}ms` }}
                >
                  <Icon className="h-4 w-4" />
                  {label}
                </Link>
              ))}
            </nav>
          </div>
        </header>
        <main className="flex-1">{children}</main>
      </div>
    </div>
  );
}

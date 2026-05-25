"use client";

import { useEffect, useState } from "react";
import { Activity, Database, Files, MessageSquareText } from "lucide-react";
import { getHealth, listConversations, listDocuments, listSources } from "@/lib/api";
import type {
  ConversationRecord,
  DocumentRecord,
  HealthStatus,
  SourceRecord,
} from "@/lib/types";
import { Pill, SectionCard } from "@/components/ui";

export function OverviewDashboard() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [sources, setSources] = useState<SourceRecord[]>([]);
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [conversations, setConversations] = useState<ConversationRecord[]>([]);

  useEffect(() => {
    async function load() {
      const [nextHealth, nextSources, nextDocuments, nextConversations] =
        await Promise.all([
          getHealth(),
          listSources(),
          listDocuments(),
          listConversations(),
        ]);

      setHealth(nextHealth);
      setSources(nextSources);
      setDocuments(nextDocuments);
      setConversations(nextConversations);
    }

    void load();
  }, []);

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          title="Source Coverage"
          value={String(sources.length)}
          detail="Registered knowledge sources"
          icon={<Database className="h-5 w-5" />}
        />
        <MetricCard
          title="Documents"
          value={String(documents.length)}
          detail="Indexed or staged files"
          icon={<Files className="h-5 w-5" />}
        />
        <MetricCard
          title="Conversations"
          value={String(conversations.length)}
          detail="Recent grounded threads"
          icon={<MessageSquareText className="h-5 w-5" />}
        />
        <MetricCard
          title="Platform Health"
          value={health?.status ?? "loading"}
          detail="API and dependency readiness"
          icon={<Activity className="h-5 w-5" />}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
        <SectionCard className="overflow-hidden">
          <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
            <div>
              <h2 className="text-xl font-semibold tracking-tight text-slate-950">Readiness snapshot</h2>
              <p className="mt-2 max-w-2xl text-sm leading-7 text-slate-600">
                The frontend is wired to the live `/api/v1` backend for health, documents,
                ingestion, and grounded conversations, with search ready for the expected route contract.
              </p>
            </div>
            <Pill tone="neutral">Live client</Pill>
          </div>
          <div className="mt-8 grid gap-4 md:grid-cols-3">
            {Object.entries(health?.services ?? {}).map(([service, status]) => (
              <div key={service} className="surface-soft rounded-[1.4rem] p-4 transition duration-200 hover:-translate-y-1">
                <p className="text-sm capitalize text-slate-500">{service}</p>
                <p className="mt-2 text-lg font-semibold capitalize text-slate-950">{status}</p>
                <div className="mt-4 h-1.5 rounded-full bg-slate-100">
                  <div className="h-1.5 w-full rounded-full bg-gradient-to-r from-amber-400 to-emerald-500" />
                </div>
              </div>
            ))}
          </div>
        </SectionCard>

        <SectionCard className="bg-slate-950 text-white">
          <h2 className="text-xl font-semibold tracking-tight">Primary flows</h2>
          <div className="mt-5 space-y-4 text-sm leading-7 text-slate-300">
            <p>Upload files and track ingestion until processing completes or fails.</p>
            <p>Browse the document library by real backend statuses, source, and detected type.</p>
            <p>Use search to inspect retrieval results, then open chat for citation-backed answers.</p>
          </div>
        </SectionCard>
      </div>
    </div>
  );
}

function MetricCard({
  title,
  value,
  detail,
  icon,
}: {
  title: string;
  value: string;
  detail: string;
  icon: React.ReactNode;
}) {
  return (
    <SectionCard className="group relative overflow-hidden p-5">
      <div className="absolute inset-x-0 top-0 h-20 bg-gradient-to-r from-amber-100/60 via-white/0 to-emerald-100/50 opacity-70 transition duration-300 group-hover:opacity-100" />
      <div className="relative flex items-center justify-between text-slate-500">
        <span className="text-sm font-medium">{title}</span>
        <div className="rounded-2xl bg-white/70 p-2 text-slate-700 shadow-insetGlow">{icon}</div>
      </div>
      <p className="relative mt-6 text-4xl font-semibold tracking-[-0.05em] capitalize text-slate-950">
        {value}
      </p>
      <p className="relative mt-2 text-sm leading-6 text-slate-600">{detail}</p>
    </SectionCard>
  );
}

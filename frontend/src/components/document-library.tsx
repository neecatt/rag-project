"use client";

import { useEffect, useMemo, useState } from "react";
import { Search } from "lucide-react";
import { listDocuments } from "@/lib/api";
import { formatDate } from "@/lib/utils";
import type { DocumentRecord } from "@/lib/types";
import { EmptyState, Pill, SectionCard } from "@/components/ui";

const STATUS_ORDER = ["all", "processing", "completed", "failed", "uploaded"];

export function DocumentLibrary() {
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [source, setSource] = useState("all");
  const [documentType, setDocumentType] = useState("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      setLoading(true);
      setError(null);

      try {
        setDocuments(await listDocuments());
      } catch (nextError) {
        setError(
          nextError instanceof Error
            ? nextError.message
            : "Could not load documents.",
        );
      } finally {
        setLoading(false);
      }
    }

    void load();
  }, []);

  const sourceOptions = useMemo(() => {
    return Array.from(
      new Set(documents.map((document) => document.source_name).filter(Boolean)),
    ) as string[];
  }, [documents]);

  const typeOptions = useMemo(() => {
    return Array.from(
      new Set(documents.map((document) => document.document_type).filter(Boolean)),
    ) as string[];
  }, [documents]);

  const statusOptions = useMemo(() => {
    const known = new Set(documents.map((document) => document.status));
    const ordered = STATUS_ORDER.filter((item) => item === "all" || known.has(item));
    const remaining = Array.from(known).filter((item) => !STATUS_ORDER.includes(item));
    return [...ordered, ...remaining.sort()];
  }, [documents]);

  const filtered = useMemo(() => {
    return documents.filter((document) => {
      const haystack = [
        document.title,
        document.source_name,
        document.document_type,
        document.mime_type,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();

      const matchesQuery =
        query.length === 0 || haystack.includes(query.toLowerCase());
      const matchesStatus = status === "all" || document.status === status;
      const matchesSource =
        source === "all" || document.source_name === source;
      const matchesType =
        documentType === "all" || document.document_type === documentType;

      return matchesQuery && matchesStatus && matchesSource && matchesType;
    });
  }, [documents, query, status, source, documentType]);

  return (
    <SectionCard className="overflow-hidden">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight text-slate-950">
            Document library
          </h2>
          <p className="mt-2 text-sm leading-7 text-slate-600">
            Browse uploaded documents by processing status, source, and detected type.
          </p>
        </div>
        <Pill tone="neutral">
          {loading ? "Loading" : `${documents.length} documents`}
        </Pill>
      </div>

      <div className="mt-6 grid gap-3 lg:grid-cols-[1.25fr_0.75fr_0.75fr_0.75fr]">
        <label className="relative block">
          <Search className="pointer-events-none absolute left-4 top-3.5 h-4 w-4 text-slate-400" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search title, source, type, or MIME"
              disabled={loading}
              className="field-shell interactive-field w-full rounded-full py-3 pl-11 pr-4"
            />
        </label>
        <select
          value={status}
          onChange={(event) => setStatus(event.target.value)}
          disabled={loading}
          className="field-shell interactive-field rounded-full px-4 py-3"
        >
          {statusOptions.map((option) => (
            <option key={option} value={option}>
              {option === "all" ? "All statuses" : formatStatusLabel(option)}
            </option>
          ))}
        </select>
        <select
          value={source}
          onChange={(event) => setSource(event.target.value)}
          disabled={loading}
          className="field-shell interactive-field rounded-full px-4 py-3"
        >
          <option value="all">All sources</option>
          {sourceOptions.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
        <select
          value={documentType}
          onChange={(event) => setDocumentType(event.target.value)}
          disabled={loading}
          className="field-shell interactive-field rounded-full px-4 py-3"
        >
          <option value="all">All types</option>
          {typeOptions.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      </div>

      {error ? (
        <div className="mt-6 rounded-[1.4rem] bg-rose-50 p-4 text-sm text-rose-900 ring-1 ring-rose-200">
          {error}
        </div>
      ) : null}

      <div className="mt-8 overflow-hidden rounded-[1.6rem] border border-white/80 bg-white/55">
        {loading ? (
          <div className="p-6">
            <EmptyState
              title="Loading documents"
              description="Fetching the current backend document inventory and statuses."
            />
          </div>
        ) : filtered.length > 0 ? (
          <table className="min-w-full divide-y divide-slate-100 text-left text-sm">
            <thead className="bg-slate-50/90 text-slate-500">
              <tr>
                <th className="px-5 py-4 font-medium">Title</th>
                <th className="px-5 py-4 font-medium">Source</th>
                <th className="px-5 py-4 font-medium">Type</th>
                <th className="px-5 py-4 font-medium">Status</th>
                <th className="px-5 py-4 font-medium">Updated</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100/80 bg-white/70">
              {filtered.map((document) => (
                <tr key={document.id} className="transition hover:bg-amber-50/55">
                  <td className="px-5 py-4">
                    <div className="font-medium text-slate-900">{document.title}</div>
                    <div className="mt-1 text-xs text-slate-500">
                      {document.mime_type ?? "Unknown MIME type"}
                    </div>
                  </td>
                  <td className="px-5 py-4 text-slate-600">
                    {document.source_name ?? "Direct upload"}
                  </td>
                  <td className="px-5 py-4 text-slate-600">
                    {document.document_type ?? "unknown"}
                  </td>
                  <td className="px-5 py-4">
                    <Pill tone={getStatusTone(document.status)}>
                      {formatStatusLabel(document.status)}
                    </Pill>
                  </td>
                  <td className="px-5 py-4 text-slate-600">
                    {formatDate(document.updated_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="p-6">
            <EmptyState
              title={
                documents.length === 0
                  ? "No documents uploaded yet"
                  : "No documents match the current filters"
              }
              description={
                documents.length === 0
                  ? "Upload a document to start building a searchable library with backend-backed processing states."
                  : "Try a broader query or reset one of the source, type, or status filters."
              }
            />
          </div>
        )}
      </div>
    </SectionCard>
  );
}

function getStatusTone(status: string) {
  if (status === "completed") {
    return "success" as const;
  }
  if (status === "failed") {
    return "danger" as const;
  }
  return "warning" as const;
}

function formatStatusLabel(status: string) {
  if (!status) {
    return "Unknown";
  }

  return status.charAt(0).toUpperCase() + status.slice(1);
}

"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { CheckCircle2, LoaderCircle, UploadCloud, XCircle } from "lucide-react";
import { getDocumentStatus, uploadDocument } from "@/lib/api";
import type { DocumentStatusRecord, DocumentUploadResult } from "@/lib/types";
import { formatDate } from "@/lib/utils";
import { EmptyState, Pill, SectionCard } from "@/components/ui";

const TERMINAL_STATUSES = new Set(["completed", "failed"]);

export function UploadWorkspace() {
  const [name, setName] = useState("");
  const [workspaceId, setWorkspaceId] = useState("");
  const [classification, setClassification] = useState("internal");
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [uploadResult, setUploadResult] = useState<DocumentUploadResult | null>(null);
  const [status, setStatus] = useState<DocumentStatusRecord | null>(null);
  const [polling, setPolling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const documentId = uploadResult?.document_id;
    if (!documentId) {
      return;
    }
    const pollingDocumentId = documentId;

    let cancelled = false;
    let timeoutId: ReturnType<typeof setTimeout> | undefined;

    async function poll() {
      setPolling(true);

      try {
        const nextStatus = await getDocumentStatus(pollingDocumentId);
        if (cancelled) {
          return;
        }

        setStatus(nextStatus);
        if (!TERMINAL_STATUSES.has(nextStatus.status)) {
          timeoutId = setTimeout(poll, 2000);
        }
      } catch (nextError) {
        if (!cancelled) {
          setError(
            nextError instanceof Error
              ? nextError.message
              : "Could not refresh ingestion status. Showing the last known document state.",
          );
        }
      } finally {
        if (!cancelled) {
          setPolling(false);
        }
      }
    }

    void poll();

    return () => {
      cancelled = true;
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
    };
  }, [uploadResult?.document_id]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) {
      setError("Select a file to upload.");
      return;
    }

    setSubmitting(true);
    setError(null);
    setUploadResult(null);
    setStatus(null);

    try {
      const nextResult = await uploadDocument({
        name: name || file.name,
        classification,
        workspaceId: workspaceId || undefined,
        file,
      });

      setUploadResult(nextResult);
      setStatus({
        document_id: nextResult.document_id,
        filename: nextResult.filename,
        title: name || file.name,
        status: nextResult.status,
        error_message: nextResult.error_message,
      });
      setName("");
      setWorkspaceId("");
      setClassification("internal");
      setFile(null);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Upload failed.");
    } finally {
      setSubmitting(false);
    }
  }

  const uploadTone = useMemo(() => {
    return getStatusTone(status?.status ?? uploadResult?.status);
  }, [status?.status, uploadResult?.status]);

  return (
    <div className="grid gap-6 lg:grid-cols-[1.15fr_0.85fr]">
      <SectionCard className="overflow-hidden">
        <div className="flex items-center gap-4">
          <div className="rounded-[1.4rem] bg-gradient-to-br from-amber-100 to-orange-50 p-3 text-amber-700 shadow-float">
            <UploadCloud className="h-6 w-6" />
          </div>
          <div>
            <h2 className="text-2xl font-semibold tracking-tight text-slate-950">
              Document upload
            </h2>
            <p className="mt-1 text-sm leading-7 text-slate-600">
              Register source metadata, upload the file once, and track document processing until it completes or fails.
            </p>
          </div>
        </div>

        <form className="mt-8 space-y-5" onSubmit={onSubmit}>
          <Field label="Display name">
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Engineering Handbook"
              className="field-shell interactive-field w-full rounded-2xl px-4 py-3.5"
            />
          </Field>

          <Field label="Workspace ID">
            <input
              value={workspaceId}
              onChange={(event) => setWorkspaceId(event.target.value)}
              placeholder="Optional workspace UUID"
              className="field-shell interactive-field w-full rounded-2xl px-4 py-3.5"
            />
          </Field>

          <Field label="Classification">
            <select
              value={classification}
              onChange={(event) => setClassification(event.target.value)}
              className="field-shell interactive-field w-full rounded-2xl px-4 py-3.5"
            >
              <option value="public">Public</option>
              <option value="internal">Internal</option>
              <option value="confidential">Confidential</option>
            </select>
          </Field>

          <Field label="File">
            <label
              htmlFor="document-file"
              className="block cursor-pointer rounded-[1.6rem] border border-dashed border-slate-300 bg-gradient-to-br from-white to-slate-50 p-4 transition duration-200 hover:-translate-y-0.5 hover:border-sky-300 hover:bg-white focus-within:border-sky-500 focus-within:ring-4 focus-within:ring-sky-100"
            >
              <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <span className="action-primary inline-flex rounded-full px-4 py-2 text-sm font-semibold">
                    Choose file
                  </span>
                  <p className="mt-3 text-sm font-medium text-slate-900">
                    {file ? file.name : "No file selected yet"}
                  </p>
                  <p className="mt-1 text-xs text-slate-500">
                    PDF, Markdown, DOCX, or text files
                  </p>
                </div>
                <div className="rounded-full bg-amber-100 px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.16em] text-amber-900">
                  {file ? "Selected" : "Awaiting file"}
                </div>
              </div>
            </label>
            <input
              id="document-file"
              type="file"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              className="sr-only"
            />
          </Field>

          <button
            type="submit"
            disabled={submitting || !file}
            className="action-primary action-accent inline-flex items-center justify-center gap-2 rounded-full px-5 py-3 text-sm font-semibold disabled:cursor-not-allowed"
          >
            {submitting ? <LoaderCircle className="h-4 w-4 animate-spin" /> : null}
            Upload and process
          </button>

          {error ? (
            <div className="rounded-[1.4rem] bg-rose-50/95 p-4 text-sm text-rose-950 ring-1 ring-rose-200">
              {error}
            </div>
          ) : null}
        </form>
      </SectionCard>

      <SectionCard>
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-xl font-semibold tracking-tight text-slate-950">
              Ingestion status
            </h3>
            <p className="mt-1 text-sm leading-7 text-slate-600">
              Creates a source with metadata, uploads the file, and polls `/documents/{'{document_id}'}/status` for the authoritative backend state.
            </p>
          </div>
          {status ? (
            <Pill tone={uploadTone}>
              {polling && !TERMINAL_STATUSES.has(status.status)
                ? `${status.status}...`
                : status.status}
            </Pill>
          ) : null}
        </div>

        <div className="mt-6">
          {status ? (
            <div className="space-y-4">
              <div className="surface-soft rounded-[1.4rem] p-5">
                  <div className="flex items-start justify-between gap-4">
                  <div>
                    <p className="text-sm text-slate-500">Document</p>
                    <p className="mt-1 text-lg font-semibold text-slate-950">
                      {status.title ?? status.filename ?? "Uploaded file"}
                    </p>
                    <p className="mt-1 text-sm text-slate-500">
                      {status.filename ?? uploadResult?.filename}
                    </p>
                  </div>
                  <StatusIcon status={status.status} />
                </div>
                <div className="mt-5 grid gap-3 text-sm text-slate-600">
                  {uploadResult?.source_id ? (
                    <div className="flex items-center justify-between gap-4">
                      <span>Source ID</span>
                      <code className="text-xs text-slate-900">{uploadResult.source_id}</code>
                    </div>
                  ) : null}
                  {uploadResult?.job_id ? (
                    <div className="flex items-center justify-between gap-4">
                      <span>Background job</span>
                      <code className="text-xs text-slate-900">{uploadResult.job_id}</code>
                    </div>
                  ) : null}
                  <div className="flex items-center justify-between gap-4">
                    <span>Document ID</span>
                    <code className="text-xs text-slate-900">{status.document_id}</code>
                  </div>
                  <div className="flex items-center justify-between gap-4">
                    <span>Last update</span>
                    <span>{formatDate(status.updated_at)}</span>
                  </div>
                </div>
                <div className="mt-4 rounded-2xl bg-slate-50/90 px-4 py-3 text-sm text-slate-700 ring-1 ring-slate-200/80">
                  {getStatusDescription(status.status)}
                </div>
                {status.error_message ? (
                  <div className="mt-4 rounded-2xl bg-rose-50 px-4 py-3 text-sm text-rose-900 ring-1 ring-rose-200">
                    {status.error_message}
                  </div>
                ) : null}
              </div>
              {!TERMINAL_STATUSES.has(status.status) ? (
                <p className="text-sm text-slate-600">
                  Processing is still running. This panel refreshes automatically from the backend status endpoint.
                </p>
              ) : null}
            </div>
          ) : (
            <EmptyState
              title="No active upload"
              description="Upload a document to see processing progress, completion, or failure details here."
            />
          )}
        </div>
      </SectionCard>
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-2.5 block text-sm font-medium text-slate-700">{label}</span>
      {children}
    </label>
  );
}

function getStatusTone(status?: string) {
  if (status === "completed") {
    return "success" as const;
  }
  if (status === "failed") {
    return "danger" as const;
  }
  return "warning" as const;
}

function StatusIcon({ status }: { status: string }) {
  if (status === "completed") {
    return <CheckCircle2 className="h-6 w-6 text-emerald-600" />;
  }
  if (status === "failed") {
    return <XCircle className="h-6 w-6 text-rose-600" />;
  }
  return <LoaderCircle className="h-6 w-6 animate-spin text-amber-600" />;
}

function getStatusDescription(status: string) {
  if (status === "completed") {
    return "Processing finished successfully. This document is now ready for search and grounded chat.";
  }
  if (status === "failed") {
    return "Processing stopped with an error. Review the backend message above before retrying the upload.";
  }
  if (status === "processing") {
    return "The backend is extracting, chunking, and indexing this file now.";
  }
  if (status === "uploaded") {
    return "The file upload was accepted and is waiting for processing work to continue.";
  }
  return "The latest backend status is shown here as processing continues.";
}

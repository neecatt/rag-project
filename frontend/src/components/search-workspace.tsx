"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { LoaderCircle, Search } from "lucide-react";
import { listDocuments, listSources, searchDocuments } from "@/lib/api";
import type { DocumentRecord, SearchResult, SourceRecord } from "@/lib/types";
import { AnswerContent, EmptyState, EvidenceList, Pill, SectionCard } from "@/components/ui";

export function SearchWorkspace() {
  const [sources, setSources] = useState<SourceRecord[]>([]);
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [query, setQuery] = useState("");
  const [sourceId, setSourceId] = useState("all");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loadingFilters, setLoadingFilters] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      setLoadingFilters(true);
      setError(null);

      try {
        const [nextSources, nextDocuments] = await Promise.all([
          listSources(),
          listDocuments(),
        ]);
        setSources(nextSources);
        setDocuments(nextDocuments);
      } catch (nextError) {
        setError(
          nextError instanceof Error
            ? nextError.message
            : "Could not load search filters.",
        );
      } finally {
        setLoadingFilters(false);
      }
    }

    void load();
  }, []);

  const completedCount = useMemo(() => {
    return documents.filter((document) => document.status === "completed").length;
  }, [documents]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!query.trim()) {
      return;
    }

    setSubmitting(true);
    setHasSearched(true);
    setError(null);

    try {
      const nextResults = await searchDocuments({
        query: query.trim(),
        sourceIds: sourceId === "all" ? undefined : [sourceId],
        topK: 8,
      });
      setResults(nextResults);
    } catch (nextError) {
      setResults([]);
      setError(
        nextError instanceof Error
          ? nextError.message
          : "Search request failed.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[0.9fr_1.1fr]">
      <SectionCard>
        <h2 className="text-2xl font-semibold tracking-tight text-slate-950">
          Search workspace
        </h2>
        <p className="mt-2 text-sm leading-7 text-slate-600">
          Sends grounded search requests to `POST /search` and returns matching document chunks.
        </p>

        <form className="mt-6 space-y-4" onSubmit={onSubmit}>
          <label className="relative block">
            <Search className="pointer-events-none absolute left-4 top-3.5 h-4 w-4 text-slate-400" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="What policy or topic do you want to find?"
              disabled={loadingFilters}
              className="field-shell interactive-field w-full rounded-[1.5rem] py-3.5 pl-11 pr-4"
            />
          </label>

          <div className="grid gap-3 md:grid-cols-1">
            <select
              value={sourceId}
              onChange={(event) => setSourceId(event.target.value)}
              disabled={loadingFilters}
              className="field-shell interactive-field rounded-[1.2rem] px-4 py-3"
            >
              <option value="all">All sources</option>
              {sources.map((source) => (
                <option key={source.id} value={source.id}>
                  {source.name}
                </option>
              ))}
            </select>
          </div>

          <button
            type="submit"
            disabled={loadingFilters || submitting || !query.trim()}
            className="action-primary inline-flex items-center justify-center gap-2 rounded-full px-5 py-3 text-sm font-semibold disabled:cursor-not-allowed"
          >
            {submitting ? <LoaderCircle className="h-4 w-4 animate-spin" /> : null}
            Search knowledge base
          </button>
        </form>

        {completedCount === 0 && !loadingFilters ? (
          <div className="mt-4 rounded-[1.4rem] bg-amber-50/95 p-4 text-sm text-amber-950 ring-1 ring-amber-200">
            Search is available, but grounded results may stay empty until at least one document finishes processing.
          </div>
        ) : null}

        <div className="mt-6 grid gap-4 md:grid-cols-2">
          <div className="surface-soft rounded-[1.4rem] p-4">
            <p className="text-sm text-slate-500">Ready documents</p>
            <p className="mt-2 text-2xl font-semibold tracking-tight text-slate-950">
              {completedCount}
            </p>
          </div>
          <div className="surface-soft rounded-[1.4rem] p-4">
            <p className="text-sm text-slate-500">Searchable sources</p>
            <p className="mt-2 text-2xl font-semibold tracking-tight text-slate-950">
              {loadingFilters ? "..." : sources.length}
            </p>
          </div>
        </div>
      </SectionCard>

      <SectionCard>
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-xl font-semibold tracking-tight text-slate-950">
              Retrieval results
            </h3>
            <p className="mt-1 text-sm leading-7 text-slate-600">
              Ranked snippets that should line up with grounded chat citations.
            </p>
          </div>
          {results.length > 0 ? (
            <Pill tone="neutral">{results.length} results</Pill>
          ) : null}
        </div>

        {error ? (
          <div className="mt-6 rounded-[1.4rem] bg-rose-50 p-4 text-sm text-rose-900 ring-1 ring-rose-200">
            {error}
          </div>
        ) : null}

        <div className="mt-6 space-y-4">
          {submitting ? (
            <EmptyState
              title="Searching knowledge base"
              description="Waiting for grounded retrieval results from the backend."
            />
          ) : results.length > 0 ? (
            results.map((result, index) => (
              <article key={result.chunk_id} className="surface-soft rounded-[1.4rem] p-5">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="text-lg font-semibold text-slate-950">
                      {result.document_title}
                    </p>
                    <p className="mt-1 text-xs uppercase tracking-[0.16em] text-slate-500">
                      Result {index + 1}
                    </p>
                  </div>
                  <Pill tone="neutral">{result.score.toFixed(2)} score</Pill>
                </div>
                <div className="mt-4">
                  <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                    Matched excerpt
                  </p>
                  <AnswerContent
                    content={result.snippet || "No snippet returned from the backend."}
                    className="mt-3 text-slate-700"
                  />
                </div>
                <div className="mt-5">
                  <EvidenceList
                    citations={result.citation ? [result.citation] : []}
                    title="Evidence"
                    emptyLabel="No citation metadata returned"
                  />
                </div>
              </article>
            ))
          ) : error ? (
            <EmptyState
              title="Search request failed"
              description="The backend did not return retrieval results for this request. Check the error above and try again."
            />
          ) : hasSearched ? (
            <EmptyState
              title="No grounded results found"
              description="The backend returned no matching chunks for this query and filter set. Try a broader query or wait for processing to complete."
            />
          ) : (
            <EmptyState
              title={loadingFilters ? "Loading search workspace" : "No search results yet"}
              description={
                loadingFilters
                  ? "Fetching sources and document readiness from the backend."
                  : "Run a search to inspect the backend retrieval output before opening a grounded chat."
              }
            />
          )}
        </div>
      </SectionCard>
    </div>
  );
}

import {
  demoConversations,
  demoDocuments,
  demoHealth,
  demoMessages,
  demoSearchResults,
  demoSources,
} from "@/lib/demo-data";
import type {
  ApiEnvelope,
  ChatMessage,
  ConversationRecord,
  DocumentRecord,
  DocumentStatusRecord,
  DocumentUploadResult,
  HealthStatus,
  SearchPayload,
  SearchResult,
  SourceRecord,
  UploadPayload,
} from "@/lib/types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/v1";
const DEMO_ENABLED =
  (process.env.NEXT_PUBLIC_ENABLE_DEMO_DATA ?? "false") === "true";

export type ConversationDetailRecord = ConversationRecord & {
  messages: ChatMessage[];
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });

  if (!response.ok) {
    const message = await extractErrorMessage(response);
    throw new Error(
      `Request failed with status ${response.status}${message ? `: ${message}` : ""}`,
    );
  }

  const payload = (await response.json()) as T | ApiEnvelope<T>;
  if (
    payload &&
    typeof payload === "object" &&
    "data" in payload &&
    payload.data !== undefined
  ) {
    return payload.data;
  }

  return payload as T;
}

async function extractErrorMessage(response: Response) {
  const contentType = response.headers.get("content-type") ?? "";

  if (contentType.includes("application/json")) {
    const payload = (await response.json()) as
      | { detail?: unknown; message?: unknown; error?: unknown }
      | ApiEnvelope<unknown>;
    const detail =
      asNonEmptyString((payload as { message?: unknown }).message) ??
      asNonEmptyString((payload as { error?: unknown }).error) ??
      flattenDetail((payload as { detail?: unknown }).detail);

    return detail;
  }

  return asNonEmptyString(await response.text());
}

function flattenDetail(detail: unknown): string | undefined {
  if (typeof detail === "string") {
    return asNonEmptyString(detail);
  }

  if (Array.isArray(detail)) {
    const items = detail
      .map((item) => flattenDetail(item))
      .filter((item): item is string => Boolean(item));
    return items.length > 0 ? items.join(", ") : undefined;
  }

  if (detail && typeof detail === "object") {
    const maybeMessage = asNonEmptyString(
      (detail as { msg?: unknown; message?: unknown }).msg ??
        (detail as { msg?: unknown; message?: unknown }).message,
    );
    if (maybeMessage) {
      return maybeMessage;
    }
  }

  return undefined;
}

function makeId(prefix: string) {
  return `${prefix}-${Math.random().toString(36).slice(2, 10)}`;
}

function asNonEmptyString(value: unknown): string | undefined {
  if (typeof value !== "string") {
    return undefined;
  }

  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

function normalizeSource(record: unknown): SourceRecord {
  const item = (record ?? {}) as Record<string, unknown>;

  return {
    id: String(item.id ?? makeId("src")),
    name: asNonEmptyString(item.name) ?? "Unnamed source",
    type: asNonEmptyString(item.type) ?? "upload",
    status: asNonEmptyString(item.status) ?? "unknown",
    classification: asNonEmptyString(item.classification) ?? "internal",
    workspace_id: asNonEmptyString(item.workspace_id),
    created_at:
      asNonEmptyString(item.created_at) ?? new Date().toISOString(),
  };
}

function normalizeDocument(record: unknown): DocumentRecord {
  const item = (record ?? {}) as Record<string, unknown>;
  const metadata =
    item.metadata_json && typeof item.metadata_json === "object"
      ? (item.metadata_json as Record<string, string | number | boolean | null>)
      : undefined;

  return {
    id: String(item.id ?? makeId("doc")),
    title: asNonEmptyString(item.title) ?? "Untitled document",
    source_id: item.source_id ? String(item.source_id) : "",
    source_name: asNonEmptyString(item.source_name),
    document_type:
      asNonEmptyString(item.document_type) ??
      asNonEmptyString(metadata?.document_type) ??
      undefined,
    mime_type: asNonEmptyString(item.mime_type),
    status: asNonEmptyString(item.status) ?? "unknown",
    updated_at:
      asNonEmptyString(item.updated_at) ??
      asNonEmptyString(item.created_at) ??
      new Date().toISOString(),
    metadata_json: metadata,
  };
}

function normalizeConversation(record: unknown): ConversationRecord {
  const item = (record ?? {}) as Record<string, unknown>;

  return {
    id: String(item.id ?? makeId("conv")),
    title: asNonEmptyString(item.title),
    updated_at:
      asNonEmptyString(item.updated_at) ??
      asNonEmptyString(item.created_at) ??
      new Date().toISOString(),
  };
}

function normalizeConversationDetail(record: unknown): ConversationDetailRecord {
  const item = (record ?? {}) as Record<string, unknown>;

  return {
    id: String(item.id ?? makeId("conv")),
    title: asNonEmptyString(item.title),
    updated_at:
      asNonEmptyString(item.updated_at) ??
      asNonEmptyString(item.created_at) ??
      new Date().toISOString(),
    messages: normalizeMessages(item.messages),
  };
}

function normalizeMessage(record: unknown): ChatMessage {
  const item = (record ?? {}) as Record<string, unknown>;
  const citations = Array.isArray(item.citations) ? item.citations : [];

  return {
    id: String(item.id ?? item.message_id ?? makeId("msg")),
    role:
      item.role === "assistant" || item.role === "system" || item.role === "user"
        ? item.role
        : "assistant",
    content:
      asNonEmptyString(item.content) ??
      asNonEmptyString(item.message) ??
      asNonEmptyString(item.text) ??
      "",
    citations: citations.map(normalizeCitation),
    created_at:
      asNonEmptyString(item.created_at) ??
      asNonEmptyString(item.timestamp) ??
      new Date().toISOString(),
  };
}

function normalizeMessages(payload: unknown): ChatMessage[] {
  if (!Array.isArray(payload)) {
    return [];
  }

  return payload.map(normalizeMessage);
}

function normalizeDocumentStatus(record: unknown): DocumentStatusRecord {
  const item = (record ?? {}) as Record<string, unknown>;

  return {
    document_id: String(item.document_id ?? item.id ?? makeId("doc")),
    title: asNonEmptyString(item.title),
    filename: asNonEmptyString(item.filename),
    status: asNonEmptyString(item.status) ?? "unknown",
    error_message: asNonEmptyString(item.error_message),
    created_at: asNonEmptyString(item.created_at),
    updated_at: asNonEmptyString(item.updated_at),
  };
}

function normalizeSearchResult(record: unknown): SearchResult {
  const item = (record ?? {}) as Record<string, unknown>;
  const citation = item.citation as Record<string, unknown> | undefined;

  return {
    chunk_id: String(item.chunk_id ?? makeId("chunk")),
    document_id: String(item.document_id ?? makeId("doc")),
    document_title:
      asNonEmptyString(item.document_title) ??
      asNonEmptyString(item.title) ??
      "Untitled document",
    score:
      typeof item.score === "number"
        ? item.score
        : Number(item.score ?? 0),
    snippet: asNonEmptyString(item.snippet) ?? "",
    source_id: item.source_id ? String(item.source_id) : undefined,
    citation: citation
      ? normalizeCitation({
          ...citation,
          document_id: citation.document_id ?? item.document_id,
          chunk_id: citation.chunk_id ?? item.chunk_id,
          title: citation.title ?? item.document_title,
        })
      : undefined,
  };
}

function normalizeCitation(record: unknown) {
  const citation = (record ?? {}) as Record<string, unknown>;

  return {
    document_id: String(citation.document_id ?? ""),
    chunk_id: String(citation.chunk_id ?? makeId("chunk")),
    title: asNonEmptyString(citation.title) ?? "Supporting excerpt",
    locator: buildCitationLocator(citation),
    excerpt:
      asNonEmptyString(citation.excerpt) ??
      asNonEmptyString(citation.snippet) ??
      asNonEmptyString(citation.text),
  };
}

function buildCitationLocator(citation: Record<string, unknown>) {
  const explicitLocator = asNonEmptyString(citation.locator);
  const sectionTitle = asNonEmptyString(citation.section_title);
  const pageNumber =
    typeof citation.page_number === "number"
      ? `Page ${citation.page_number}`
      : undefined;

  if (explicitLocator && sectionTitle && !explicitLocator.includes(sectionTitle)) {
    return `${explicitLocator} · ${sectionTitle}`;
  }

  if (explicitLocator) {
    return explicitLocator;
  }

  return [pageNumber, sectionTitle].filter(Boolean).join(" · ") || undefined;
}

export async function getHealth(): Promise<HealthStatus> {
  try {
    return await request<HealthStatus>("/health");
  } catch (error) {
    if (DEMO_ENABLED) {
      return demoHealth;
    }
    throw error;
  }
}

export async function listSources(): Promise<SourceRecord[]> {
  try {
    const sources = await request<unknown[]>("/sources");
    return sources.map(normalizeSource);
  } catch (error) {
    if (DEMO_ENABLED) {
      return demoSources;
    }
    throw error;
  }
}

export async function listDocuments(): Promise<DocumentRecord[]> {
  try {
    const documents = await request<unknown[]>("/documents");
    return documents.map(normalizeDocument);
  } catch (error) {
    if (DEMO_ENABLED) {
      return demoDocuments;
    }
    throw error;
  }
}

export async function listConversations(): Promise<ConversationRecord[]> {
  try {
    const conversations = await request<unknown[]>("/conversations");
    return conversations.map(normalizeConversation);
  } catch (error) {
    if (DEMO_ENABLED) {
      return demoConversations;
    }
    throw error;
  }
}

export async function getConversationDetail(
  conversationId: string,
): Promise<ConversationDetailRecord> {
  try {
    const conversation = await request<unknown>(`/conversations/${conversationId}`);
    return normalizeConversationDetail(conversation);
  } catch (error) {
    if (DEMO_ENABLED) {
      return {
        id: conversationId,
        title: demoConversations[0]?.title,
        updated_at: demoConversations[0]?.updated_at ?? new Date().toISOString(),
        messages: demoMessages,
      };
    }
    throw error;
  }
}

export async function getConversationMessages(
  conversationId: string,
): Promise<ChatMessage[]> {
  const conversation = await getConversationDetail(conversationId);
  return conversation.messages;
}

export async function createConversation(): Promise<ConversationRecord> {
  const conversation = await request<unknown>("/conversations", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({}),
  });

  return normalizeConversation(conversation);
}

export async function sendMessage(
  conversationId: string,
  message: string,
  workspaceId?: string,
): Promise<ChatMessage> {
  const payload = await request<Record<string, unknown>>(
    `/conversations/${conversationId}/messages`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        message,
        workspace_id: workspaceId,
        options: {
          stream: false,
          top_k: 8,
        },
      }),
    },
  );

  if (Array.isArray(payload.messages)) {
    const messages = normalizeMessages(payload.messages);
    return messages[messages.length - 1] ?? normalizeMessage(payload);
  }

  return normalizeMessage(payload);
}

export async function uploadDocument(
  payload: UploadPayload,
): Promise<DocumentUploadResult> {
  const source = await request<Record<string, unknown>>("/sources", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      name: payload.name,
      type: "upload",
      workspace_id: payload.workspaceId,
      classification: payload.classification,
      config: {
        filename: payload.file.name,
      },
    }),
  });
  const sourceId = String(source.id ?? makeId("src"));

  const formData = new FormData();
  formData.append("file", payload.file);
  const uploadResponse = await request<Record<string, unknown>>(
    `/sources/${sourceId}/upload`,
    {
      method: "POST",
      body: formData,
    },
  );

  return {
    source_id: sourceId,
    job_id: uploadResponse.job_id ? String(uploadResponse.job_id) : undefined,
    document_id: String(uploadResponse.document_id ?? makeId("doc")),
    filename: asNonEmptyString(uploadResponse.filename) ?? payload.file.name,
    status: asNonEmptyString(uploadResponse.status) ?? "uploaded",
    error_message: asNonEmptyString(uploadResponse.error_message),
  };
}

export async function getDocumentStatus(
  documentId: string,
): Promise<DocumentStatusRecord> {
  const response = await request<unknown>(`/documents/${documentId}/status`);
  return normalizeDocumentStatus(response);
}

export async function searchDocuments(
  payload: SearchPayload,
): Promise<SearchResult[]> {
  try {
    const response = await request<Record<string, unknown>>("/search", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        query: payload.query,
        workspace_id: payload.workspaceId,
        filters: {
          source_ids: payload.sourceIds?.length ? payload.sourceIds : undefined,
        },
        top_k: payload.topK ?? 8,
      }),
    });

    return Array.isArray(response.results)
      ? response.results.map(normalizeSearchResult)
      : [];
  } catch (error) {
    if (DEMO_ENABLED) {
      return demoSearchResults;
    }
    throw error;
  }
}

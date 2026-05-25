import type {
  ChatMessage,
  Citation,
  ConversationRecord,
  DocumentRecord,
  HealthStatus,
  SearchResult,
  SourceRecord,
} from "@/lib/types";

export const demoSources: SourceRecord[] = [
  {
    id: "src-handbook",
    name: "Employee Handbook",
    type: "upload",
    status: "completed",
    classification: "internal",
    workspace_id: "workspace-people",
    created_at: "2026-05-10T09:15:00Z",
  },
  {
    id: "src-security",
    name: "Security Standards",
    type: "upload",
    status: "processing",
    classification: "confidential",
    workspace_id: "workspace-it",
    created_at: "2026-05-12T13:45:00Z",
  },
];

export const demoDocuments: DocumentRecord[] = [
  {
    id: "doc-pto",
    title: "PTO Carryover Policy",
    source_id: "src-handbook",
    source_name: "Employee Handbook",
    document_type: "policy",
    mime_type: "application/pdf",
    status: "completed",
    updated_at: "2026-05-14T15:00:00Z",
    metadata_json: {
      pages: 18,
      owner: "People Ops",
    },
  },
  {
    id: "doc-retention",
    title: "Data Retention Policy",
    source_id: "src-security",
    source_name: "Security Standards",
    document_type: "policy",
    mime_type: "application/pdf",
    status: "processing",
    updated_at: "2026-05-11T08:30:00Z",
    metadata_json: {
      pages: 12,
      owner: "Security",
    },
  },
  {
    id: "doc-vendors",
    title: "Vendor Review Checklist",
    source_id: "src-security",
    source_name: "Security Standards",
    document_type: "guide",
    mime_type: "text/markdown",
    status: "failed",
    updated_at: "2026-05-09T12:10:00Z",
    metadata_json: {
      owner: "Procurement",
    },
  },
];

export const demoConversations: ConversationRecord[] = [
  {
    id: "conv-1",
    title: "Retention policy summary",
    updated_at: "2026-05-15T10:00:00Z",
  },
  {
    id: "conv-2",
    title: "Security review process",
    updated_at: "2026-05-13T16:25:00Z",
  },
];

const demoCitations: Citation[] = [
  {
    document_id: "doc-retention",
    chunk_id: "chunk-4",
    title: "Data Retention Policy",
    locator: "Page 4",
  },
  {
    document_id: "doc-retention",
    chunk_id: "chunk-7",
    title: "Data Retention Policy",
    locator: "Page 6",
  },
];

export const demoMessages: ChatMessage[] = [
  {
    id: "msg-1",
    role: "user",
    content: "Summarize the data retention policy.",
    created_at: "2026-05-15T10:00:00Z",
  },
  {
    id: "msg-2",
    role: "assistant",
    content:
      "The policy keeps operational records for standard retention windows, requires legal holds to pause deletion, and routes exceptions through Security and Legal for approval.",
    citations: demoCitations,
    created_at: "2026-05-15T10:00:08Z",
  },
];

export const demoHealth: HealthStatus = {
  status: "ok",
  services: {
    api: "ok",
    postgres: "ok",
    redis: "ok",
  },
};

export const demoSearchResults: SearchResult[] = [
  {
    chunk_id: "chunk-1",
    document_id: "doc-retention",
    document_title: "Data Retention Policy",
    score: 0.91,
    snippet:
      "Operational records follow standard retention windows, while legal holds suspend deletion until review is cleared.",
    source_id: "src-security",
  },
  {
    chunk_id: "chunk-2",
    document_id: "doc-pto",
    document_title: "PTO Carryover Policy",
    score: 0.76,
    snippet:
      "Unused paid time off may carry into the next cycle up to the capped allowance defined by People Ops.",
    source_id: "src-handbook",
  },
];

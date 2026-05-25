export type ApiEnvelope<T> = {
  data: T;
  meta?: {
    request_id?: string;
  };
};

export type SourceRecord = {
  id: string;
  name: string;
  type: string;
  status: string;
  classification: string;
  workspace_id?: string;
  created_at?: string;
};

export type DocumentRecord = {
  id: string;
  title: string;
  source_id: string;
  source_name?: string;
  document_type?: string;
  mime_type?: string;
  status: string;
  updated_at?: string;
  metadata_json?: Record<string, string | number | boolean | null>;
};

export type DocumentStatusRecord = {
  document_id: string;
  title?: string;
  filename?: string;
  status: string;
  error_message?: string;
  created_at?: string;
  updated_at?: string;
};

export type DocumentUploadResult = {
  source_id?: string;
  job_id?: string;
  document_id: string;
  filename: string;
  status: string;
  error_message?: string;
};

export type Citation = {
  document_id: string;
  chunk_id: string;
  title: string;
  locator?: string;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  citations?: Citation[];
  created_at?: string;
};

export type ConversationRecord = {
  id: string;
  title?: string;
  updated_at?: string;
};

export type SearchResult = {
  chunk_id: string;
  document_id: string;
  document_title: string;
  score: number;
  snippet: string;
  source_id?: string;
  citation?: Citation;
};

export type SearchPayload = {
  query: string;
  workspaceId?: string;
  sourceIds?: string[];
  topK?: number;
};

export type HealthStatus = {
  status: string;
  services: Record<string, string>;
};

export type UploadPayload = {
  name: string;
  classification: string;
  workspaceId?: string;
  file: File;
};

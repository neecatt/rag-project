"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { LoaderCircle, SendHorizontal } from "lucide-react";
import {
  createConversation,
  getConversationDetail,
  getConversationMessages,
  listConversations,
  listDocuments,
  sendMessage,
} from "@/lib/api";
import { formatDate } from "@/lib/utils";
import type { ChatMessage, ConversationRecord, DocumentRecord } from "@/lib/types";
import { AnswerContent, EmptyState, EvidenceList, Pill, SectionCard } from "@/components/ui";

export function ChatWorkspace() {
  const [conversations, setConversations] = useState<ConversationRecord[]>([]);
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [conversationId, setConversationId] = useState<string>("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [loadingWorkspace, setLoadingWorkspace] = useState(true);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const completedDocuments = useMemo(() => {
    return documents.filter((document) => document.status === "completed");
  }, [documents]);

  const activeConversation = useMemo(() => {
    return conversations.find((conversation) => conversation.id === conversationId);
  }, [conversationId, conversations]);

  useEffect(() => {
    async function load() {
      setLoadingWorkspace(true);
      setError(null);

      try {
        const [nextConversations, nextDocuments] = await Promise.all([
          listConversations(),
          listDocuments(),
        ]);
        setConversations(nextConversations);
        setDocuments(nextDocuments);
        if (!conversationId && nextConversations[0]) {
          setConversationId(nextConversations[0].id);
        }
      } catch (nextError) {
        setError(
          nextError instanceof Error
            ? nextError.message
            : "Could not load chat workspace.",
        );
      } finally {
        setLoadingWorkspace(false);
      }
    }

    void load();
  }, []);

  useEffect(() => {
    async function loadMessages() {
      if (!conversationId) {
        setMessages([]);
        return;
      }

      setLoadingMessages(true);
      setError(null);

      try {
        setMessages(await getConversationMessages(conversationId));
      } catch (nextError) {
        setMessages([]);
        setError(
          nextError instanceof Error
            ? nextError.message
            : "Could not load conversation history.",
        );
      } finally {
        setLoadingMessages(false);
      }
    }

    void loadMessages();
  }, [conversationId]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!input.trim()) {
      return;
    }

    setSubmitting(true);
    setError(null);
    const trimmedInput = input.trim();
    const previousMessages = messages;

    const outgoing: ChatMessage = {
      id: `local-${Date.now()}`,
      role: "user",
      content: trimmedInput,
      created_at: new Date().toISOString(),
    };
    setMessages((current) => [...current, outgoing]);
    setInput("");

    try {
      let activeConversationId = conversationId;
      if (!activeConversationId) {
        const created = await createConversation();
        activeConversationId = created.id;
        setConversationId(created.id);
      }
      await sendMessage(activeConversationId, trimmedInput);

      const [nextConversation, nextConversations] = await Promise.all([
        getConversationDetail(activeConversationId),
        listConversations(),
      ]);

      setConversationId(nextConversation.id);
      setMessages(nextConversation.messages);
      setConversations(nextConversations);
    } catch (nextError) {
      setMessages(previousMessages);
      setInput(trimmedInput);
      setError(
        nextError instanceof Error ? nextError.message : "Chat request failed.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[0.85fr_1.15fr]">
      <SectionCard className="overflow-hidden p-5">
        <div className="flex items-start justify-between gap-4 border-b border-slate-100/80 pb-4">
          <div className="min-w-0">
            <h2 className="text-xl font-semibold tracking-tight text-slate-950">
              Conversation list
            </h2>
            <p className="mt-1 text-sm leading-6 text-slate-600">
              Recent grounded threads backed by `/conversations`.
            </p>
          </div>
          <Pill tone="neutral">
            {loadingWorkspace ? "Loading" : `${conversations.length} threads`}
          </Pill>
        </div>

        <div className="mt-4">
          {loadingWorkspace ? (
            <EmptyState
              title="Loading conversations"
              description="Fetching persisted conversation history from the backend."
            />
          ) : conversations.length > 0 ? (
            <div className="space-y-2">
              {conversations.map((conversation, index) => (
                <button
                  key={conversation.id}
                  type="button"
                  onClick={() => {
                    setError(null);
                    setConversationId(conversation.id);
                  }}
                  className={`block w-full rounded-[1.15rem] px-3.5 py-3 text-left transition duration-200 hover:-translate-y-0.5 ${
                    conversationId === conversation.id
                      ? "selectable-surface-active ring-1 ring-white/70"
                      : "surface-soft selectable-surface text-slate-900"
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span
                          className={`h-2 w-2 flex-none rounded-full ${
                            conversationId === conversation.id
                              ? "bg-white/90"
                              : "bg-slate-300"
                          }`}
                        />
                        <p className="truncate text-sm font-medium">
                          {getConversationTitle(conversation) ?? "Untitled thread"}
                        </p>
                      </div>
                      <p
                        className={`mt-1 pl-4 text-[11px] uppercase tracking-[0.14em] ${
                          conversationId === conversation.id
                            ? "text-sky-100/90"
                            : "text-slate-500"
                        }`}
                      >
                        Thread {index + 1}
                      </p>
                    </div>
                    <p
                      className={`whitespace-nowrap pt-0.5 text-[11px] ${
                        conversationId === conversation.id
                          ? "text-sky-100/90"
                          : "text-slate-500"
                      }`}
                    >
                      {formatDate(conversation.updated_at)}
                    </p>
                  </div>
                </button>
              ))}
            </div>
          ) : (
            <EmptyState
              title="No conversations yet"
              description="Start a grounded question on the right to create the first thread."
            />
          )}
        </div>
      </SectionCard>

      <SectionCard className="flex min-h-[680px] flex-col overflow-hidden">
        <div className="border-b border-slate-100/80 pb-4">
          <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
            <div>
              <h2 className="text-2xl font-semibold tracking-tight text-slate-950">
                {activeConversation
                  ? getConversationTitle(activeConversation) ?? "Grounded chat"
                  : "Grounded chat"}
              </h2>
              <p className="mt-2 text-sm leading-7 text-slate-600">
                Backend-persisted messages and titles are loaded from the selected conversation.
              </p>
            </div>
            <Pill tone={completedDocuments.length > 0 ? "success" : "warning"}>
              {completedDocuments.length} ready docs
            </Pill>
          </div>
        </div>

        {error ? (
          <div className="mt-5 rounded-[1.4rem] bg-rose-50 p-4 text-sm text-rose-900 ring-1 ring-rose-200">
            {error}
          </div>
        ) : null}

        <div className="flex-1 space-y-4 overflow-y-auto py-6">
          {loadingMessages ? (
            <EmptyState
              title="Loading messages"
              description="Fetching the selected conversation from the backend."
            />
          ) : messages.length > 0 ? (
            messages.map((message) => (
              <article
                key={message.id}
                className={`max-w-3xl rounded-[1.6rem] p-4 shadow-[0_14px_36px_-28px_rgba(15,23,42,0.35)] ${
                  message.role === "user"
                    ? "ml-auto border border-sky-700/70 bg-[var(--accent-strong)] text-white shadow-[0_22px_40px_-28px_rgba(11,79,138,0.95)]"
                    : "surface-soft text-slate-900"
                }`}
              >
                <div className="flex items-center justify-between gap-4">
                  <p className="text-sm font-medium capitalize opacity-80">
                    {message.role}
                  </p>
                  <span className="text-xs opacity-70">
                    {formatDate(message.created_at)}
                  </span>
                </div>
                {message.role === "assistant" ? (
                  <div className="mt-4 space-y-5">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                        Answer
                      </p>
                      <AnswerContent
                        content={getMessageContent(message)}
                        className="mt-3 text-slate-900"
                      />
                    </div>
                    <EvidenceList citations={message.citations} />
                  </div>
                ) : (
                  <AnswerContent
                    content={getMessageContent(message)}
                    className="mt-2 text-white"
                  />
                )}
              </article>
            ))
          ) : conversationId ? (
            <EmptyState
              title="No messages in this conversation"
              description="Send the first message to create a persisted grounded exchange."
            />
          ) : loadingWorkspace ? (
            <EmptyState
              title="Loading chat workspace"
              description="Checking conversations and document readiness."
            />
          ) : (
            <EmptyState
              title={
                completedDocuments.length > 0
                  ? "No conversations yet"
                  : "No completed documents available yet"
              }
              description={
                completedDocuments.length > 0
                  ? "Start a grounded question to create the first persisted conversation."
                  : "Upload and finish processing at least one document before expecting grounded answers."
              }
            />
          )}
        </div>

        <form onSubmit={onSubmit} className="border-t border-slate-100/80 pt-4">
          <div className="flex flex-col gap-3 md:flex-row">
            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              rows={3}
              placeholder={
                completedDocuments.length > 0
                  ? "Ask a grounded question about your processed documents"
                  : "Upload and process documents before asking grounded questions"
              }
              disabled={submitting || loadingWorkspace}
              className="field-shell interactive-field min-h-[96px] flex-1 resize-none rounded-[1.5rem] px-4 py-3.5 disabled:cursor-not-allowed disabled:opacity-70"
            />
            <button
              type="submit"
              disabled={
                submitting ||
                loadingWorkspace ||
                completedDocuments.length === 0 ||
                !input.trim()
              }
              className="action-primary inline-flex h-fit items-center justify-center gap-2 rounded-full px-5 py-3 text-sm font-semibold disabled:cursor-not-allowed"
            >
              {submitting ? (
                <LoaderCircle className="h-4 w-4 animate-spin" />
              ) : (
                <SendHorizontal className="h-4 w-4" />
              )}
              Send
            </button>
          </div>
        </form>
      </SectionCard>
    </div>
  );
}

function getConversationTitle(conversation: ConversationRecord) {
  const trimmed = conversation.title?.trim();
  return trimmed && trimmed.length > 0 ? trimmed : undefined;
}

function getMessageContent(message: ChatMessage) {
  const trimmed = message.content?.trim();
  if (trimmed && trimmed.length > 0) {
    return trimmed;
  }

  return message.role === "user" ? "Message sent" : "No response text returned.";
}

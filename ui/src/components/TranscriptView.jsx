import React from "react";
import {
    entryLabel,
    getThinkingSummary,
    renderMarkdown,
    transcriptRole
} from "../lib/formatting.js";

export default function TranscriptView({ transcript, chatMessagesRef, expandedThinking, onToggleThinking, onReplay }) {
    return (
        <section className="chat-region">
            <div className="transcript-toolbar">
                <div>
                    <strong>Conversation</strong>
                </div>
            </div>
            <div id="chat-messages" className="chat-messages" ref={chatMessagesRef}>
                {!transcript.length ? (
                    <div className="transcript-empty">
                        No transcript items yet. Start with a task request, or ask for a real-time search.
                    </div>
                ) : (
                    <div className="message-list">
                        {transcript.map((entry) => {
                            const isThinking = entry.kind === "thinking_text";
                            const isExpanded = Boolean(expandedThinking[entry.id]);
                            const collapsed = isThinking && !isExpanded;
                            const bodyHtml = entry.kind === "thinking_text" && entry.pendingPlaceholder && !String(entry.content || "").trim()
                                ? null
                                : ((entry.kind === "assistant_text" || entry.kind === "system_notice" || entry.kind === "tool_result")
                                    ? renderMarkdown(entry.content)
                                    : null);

                            return (
                                <article
                                    key={entry.id}
                                    className={`message ${transcriptRole(entry)}${entry.kind === "system_notice" && entry.phase === "compression" ? " compression-notice" : ""}`}
                                >
                                    <div className="message-meta">
                                        <span>{entryLabel(entry)}</span>
                                        <span>{new Date(entry.timestamp || Date.now()).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
                                    </div>

                                    {isThinking ? (
                                        <div className="message-actions">
                                            <button
                                                type="button"
                                                className={`message-toggle thinking-toggle${isExpanded ? " expanded" : ""}`}
                                                onClick={() => onToggleThinking(entry.id)}
                                                title={isExpanded ? "Collapse thinking" : "Expand thinking"}
                                            >
                                                <i className={`fas fa-chevron-${isExpanded ? "up" : "down"}`} aria-hidden="true" />
                                            </button>
                                        </div>
                                    ) : null}

                                    {entry.kind === "tool_use" || entry.kind === "tool_result" ? (
                                        <div className={`tool-card ${entry.kind}`}>
                                            <div className={`tool-card-icon ${entry.kind === "tool_use" ? "running" : (entry.success === false ? "error" : "done")}`}>
                                                {entry.kind === "tool_use" ? <i className="fas fa-spinner" /> : (entry.success === false ? <i className="fas fa-triangle-exclamation" /> : <i className="fas fa-check" />)}
                                            </div>
                                            <div className="tool-card-content">
                                                <div className="tool-card-title">{entry.toolName || entry.taskId || "tool"}</div>
                                                <div className="tool-card-subtitle">
                                                    {entry.kind === "tool_use" ? "Invoking tool" : (entry.success === false ? "Tool finished with an error" : "Tool result captured")}
                                                </div>
                                            </div>
                                        </div>
                                    ) : null}

                                    {isThinking && collapsed ? (
                                        <div className="thinking-summary">
                                            {getThinkingSummary(entry.content, entry.streaming)}
                                        </div>
                                    ) : null}

                                    <div className={`message-body${entry.streaming ? " is-streaming" : ""}${collapsed ? " collapsed" : ""}`}>
                                        {entry.kind === "thinking_text" && entry.pendingPlaceholder && !String(entry.content || "").trim() ? (
                                            <div className="thinking-pending">
                                                <span className="thinking-pending-label">Waiting for first reasoning token</span>
                                                <span className="thinking-pending-dots" aria-hidden="true">
                                                    <span />
                                                    <span />
                                                    <span />
                                                </span>
                                            </div>
                                        ) : entry.kind === "system_notice" && entry.phase === "compression" ? (
                                            <div className="compression-inline">
                                                <span className="compression-spinner"><i className="fas fa-spinner" /></span>
                                                <span>{entry.content || "Compressing context..."}</span>
                                            </div>
                                        ) : bodyHtml !== null ? (
                                            <div dangerouslySetInnerHTML={{ __html: bodyHtml }} />
                                        ) : (
                                            <div>{entry.content}</div>
                                        )}
                                    </div>

                                    {entry.role === "user" ? (
                                        <div className="message-actions">
                                            <button type="button" className="message-toggle" onClick={() => onReplay(entry.content || "")}>
                                                Replay
                                            </button>
                                        </div>
                                    ) : null}
                                </article>
                            );
                        })}
                    </div>
                )}
            </div>
        </section>
    );
}

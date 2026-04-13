import React from "react";
import {
    entryLabel,
    getThinkingSummary,
    renderMarkdown,
    transcriptRole
} from "../lib/formatting.js";

export default function TranscriptView({ transcript, chatMessagesRef, expandedThinking, onToggleThinking, onReplay, requestIndicator }) {
    const lastUserIndex = (() => {
        for (let index = transcript.length - 1; index >= 0; index -= 1) {
            if (transcript[index]?.role === "user") {
                return index;
            }
        }
        return -1;
    })();

    return (
        <section className="chat-region">

            <div id="chat-messages" className="chat-messages" ref={chatMessagesRef}>
                {!transcript.length ? (
                    <div className="transcript-empty">
                        No transcript items yet. Start with a task request, or ask for a real-time search.
                    </div>
                ) : (
                    <div className="message-list">
                        {transcript.map((entry, index) => {
                            const isThinking = entry.kind === "thinking_text";
                            const isCompressionNotice = entry.kind === "system_notice" && entry.phase === "compression";
                            const isExpanded = Boolean(expandedThinking[entry.id]);
                            const collapsed = isThinking && !isExpanded;
                            const bodyHtml = entry.kind === "thinking_text" && entry.pendingPlaceholder && !String(entry.content || "").trim()
                                ? null
                                : ((entry.kind === "assistant_text" || entry.kind === "system_notice" || entry.kind === "tool_result" || entry.kind === "thinking_text")
                                    ? renderMarkdown(entry.content)
                                    : null);

                            return (
                            <React.Fragment key={entry.id}>
                                <article
                                    className={`message ${transcriptRole(entry)}${isCompressionNotice ? " compression-notice" : ""}`}
                                >
                                    {!isCompressionNotice ? (
                                        <div className="message-meta">
                                            <span>{entryLabel(entry)}</span>
                                            <span>{new Date(entry.timestamp || Date.now()).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
                                        </div>
                                    ) : null}

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
                                        ) : isCompressionNotice ? (
                                            <div className="compression-inline" aria-live="polite">
                                                <span className="compression-line" aria-hidden="true" />
                                                <span className="compression-copy">
                                                    {String(entry.content || "").toLowerCase().includes("compacted") ? (
                                                        <i className="fas fa-check compression-check" />
                                                    ) : (
                                                        <span className="compression-spinner"><i className="fas fa-spinner" /></span>
                                                    )}
                                                    <span>{entry.content || "Automatically compacting context"}</span>
                                                </span>
                                                <span className="compression-line" aria-hidden="true" />
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

                                {requestIndicator?.active && index === lastUserIndex ? (
                                    <div className="request-loading-left" aria-live="polite">
                                        <span className="request-loading-spinner" aria-hidden="true">
                                            <i className="fas fa-spinner" />
                                        </span>
                                        <span>{requestIndicator.label || "Working on your request"}</span>
                                    </div>
                                ) : null}
                            </React.Fragment>
                            );
                        })}
                    </div>
                )}
            </div>
        </section>
    );
}

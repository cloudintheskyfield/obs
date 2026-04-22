import React from "react";
import {
    entryLabel,
    getThinkingSummary,
    normalizeDisplayText,
    renderMarkdown,
    transcriptRole
} from "../lib/formatting.js";

const IMAGE_TOKEN_RE = /\[\[image:[^\]]+\]\]/g;

function stripImageTokens(text) {
    return (text || "").replace(IMAGE_TOKEN_RE, "").trim();
}

export default function TranscriptView({ transcript, chatMessagesRef, expandedThinking, onToggleThinking, requestIndicator, workingTimerLabel, completedLabel }) {
    const lastUserIndex = (() => {
        for (let index = transcript.length - 1; index >= 0; index -= 1) {
            if (transcript[index]?.role === "user") {
                return index;
            }
        }
        return -1;
    })();

    const lastNonUserIndex = (() => {
        for (let index = transcript.length - 1; index >= 0; index -= 1) {
            if (transcript[index]?.role !== "user") {
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
                            const isCompressionComplete = entry.compressionState === "complete";
                            const isExpanded = Boolean(expandedThinking[entry.id]);
                            const collapsed = isThinking && !isExpanded;
                            // While streaming, skip markdown parsing entirely – React updates
                            // plain text nodes incrementally without replacing the DOM, which
                            // eliminates the per-token flicker caused by dangerouslySetInnerHTML.
                            const isRenderableKind = entry.kind === "assistant_text" || entry.kind === "system_notice" || entry.kind === "tool_result" || entry.kind === "thinking_text";
                            const isPendingThinking = entry.kind === "thinking_text" && entry.pendingPlaceholder && !String(entry.content || "").trim();
                            const bodyHtml = (!isPendingThinking && isRenderableKind && !entry.streaming)
                                ? renderMarkdown(entry.content)
                                : null;

                            return (
                            <React.Fragment key={entry.id}>
                                <article
                                    className={`message ${transcriptRole(entry)}${entry.isError ? " error" : ""}${isCompressionNotice ? " compression-notice" : ""}`}
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
                                        {/* elapsed time pinned to bottom-right of the message bubble */}
                                        {(() => {
                                            const label = entry.elapsedLabel
                                                || (!requestIndicator?.active && index === lastNonUserIndex ? completedLabel : null);
                                            return label ? (
                                                <div className="completed-elapsed" aria-label={`Completed in ${label}`}>
                                                    <i className="fas fa-check-circle" aria-hidden="true" />
                                                    <span>{label}</span>
                                                </div>
                                            ) : null;
                                        })()}
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
                                                    {isCompressionComplete ? (
                                                        <i className="fas fa-check compression-check" />
                                                    ) : (
                                                        <span className="compression-spinner"><i className="fas fa-spinner" /></span>
                                                    )}
                                                    <span>{entry.content || (isCompressionComplete ? "Context compacted" : "Compressing conversation context")}</span>
                                                </span>
                                                <span className="compression-line" aria-hidden="true" />
                                            </div>
                                        ) : entry.isError ? (
                                            <pre className="error-body">{entry.content}</pre>
                                        ) : bodyHtml !== null ? (
                                            <div dangerouslySetInnerHTML={{ __html: bodyHtml }} />
                                        ) : entry.streaming && isRenderableKind ? (
                                            // Streaming: plain text via React text node avoids per-token DOM replacement
                                            <div className="streaming-plain-text">{normalizeDisplayText(entry.content)}</div>
                                        ) : (
                                            <div>
                                                {stripImageTokens(entry.content) ? <span>{stripImageTokens(entry.content)}</span> : null}
                                                {Array.isArray(entry.images) && entry.images.length > 0 ? (
                                                    <div className="message-image-chips">
                                                        {entry.images.map((img) => (
                                                            <span key={img.id} className="message-image-chip">
                                                                {img.dataUrl ? (
                                                                    <img src={img.dataUrl} alt={img.name || "image"} className="message-image-thumb" />
                                                                ) : (
                                                                    <i className="fas fa-image" />
                                                                )}
                                                                <span className="message-image-chip-name">{img.name || "image"}</span>
                                                            </span>
                                                        ))}
                                                    </div>
                                                ) : null}
                                            </div>
                                        )}
                                    </div>

                                </article>

                                {requestIndicator?.active && index === lastUserIndex ? (
                                    <div className="request-loading-left" aria-live="polite">
                                        <span className="request-loading-spinner" aria-hidden="true">
                                            <i className="fas fa-spinner" />
                                        </span>
                                        <span>{requestIndicator.label || "Working on your request"}</span>
                                        {workingTimerLabel ? (
                                            <span className="request-loading-timer">{workingTimerLabel}</span>
                                        ) : null}
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

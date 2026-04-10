export function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}

export function shortenModel(model) {
    if (!model) return "--";
    const normalized = String(model).split("/").filter(Boolean).pop() || String(model);
    return normalized.length > 22 ? `${normalized.slice(0, 22)}…` : normalized;
}

export function formatWorkspaceBreadcrumb(path, maxParts = 5) {
    const normalized = String(path || "").trim();
    if (!normalized) return "No workspace selected";
    const segments = normalized.split(/[\\/]+/).filter(Boolean).reverse();
    if (segments.length <= maxParts) {
        return segments.join(" / ");
    }
    return `${segments.slice(0, maxParts).join(" / ")} / ...`;
}

export function renderMarkdown(text) {
    const source = String(text || "").replace(/\r\n/g, "\n").trim();
    if (!source) return "";

    const lines = source.split("\n");
    const html = [];
    let index = 0;

    const renderInline = (value) => {
        let escaped = escapeHtml(value);
        escaped = escaped.replace(/`([^`]+)`/g, "<code>$1</code>");
        escaped = escaped.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
        escaped = escaped.replace(/\*([^*]+)\*/g, "<em>$1</em>");
        escaped = escaped.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer noopener">$1</a>');
        return escaped;
    };

    while (index < lines.length) {
        const line = lines[index];
        const trimmed = line.trim();

        if (!trimmed) {
            index += 1;
            continue;
        }

        if (trimmed.startsWith("```")) {
            const codeLines = [];
            index += 1;
            while (index < lines.length && !lines[index].trim().startsWith("```")) {
                codeLines.push(lines[index]);
                index += 1;
            }
            if (index < lines.length) index += 1;
            html.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
            continue;
        }

        const headingMatch = trimmed.match(/^(#{1,6})\s+(.*)$/);
        if (headingMatch) {
            const level = headingMatch[1].length;
            html.push(`<h${level}>${renderInline(headingMatch[2])}</h${level}>`);
            index += 1;
            continue;
        }

        if (/^\d+\.\s+/.test(trimmed)) {
            const items = [];
            while (index < lines.length && /^\d+\.\s+/.test(lines[index].trim())) {
                items.push(lines[index].trim().replace(/^\d+\.\s+/, ""));
                index += 1;
            }
            html.push(`<ol>${items.map((item) => `<li>${renderInline(item)}</li>`).join("")}</ol>`);
            continue;
        }

        if (/^[-*+]\s+/.test(trimmed)) {
            const items = [];
            while (index < lines.length && /^[-*+]\s+/.test(lines[index].trim())) {
                items.push(lines[index].trim().replace(/^[-*+]\s+/, ""));
                index += 1;
            }
            html.push(`<ul>${items.map((item) => `<li>${renderInline(item)}</li>`).join("")}</ul>`);
            continue;
        }

        if (/^>\s+/.test(trimmed)) {
            const quotes = [];
            while (index < lines.length && /^>\s+/.test(lines[index].trim())) {
                quotes.push(lines[index].trim().replace(/^>\s+/, ""));
                index += 1;
            }
            html.push(`<blockquote>${quotes.map((item) => renderInline(item)).join("<br>")}</blockquote>`);
            continue;
        }

        const paragraphLines = [];
        while (index < lines.length && lines[index].trim()) {
            paragraphLines.push(lines[index].trim());
            index += 1;
        }
        html.push(`<p>${renderInline(paragraphLines.join("\n")).replace(/\n/g, "<br>")}</p>`);
    }

    return html.join("");
}

export function getThinkingSummary(content, streaming) {
    const normalized = (content || "").replace(/\s+/g, " ").trim();
    if (!normalized) {
        return streaming ? "Analyzing request..." : "Reasoning captured.";
    }
    const firstSentence = normalized.split(/(?<=[.!?。！？])\s/)[0] || normalized;
    const clipped = firstSentence.length > 110 ? `${firstSentence.slice(0, 110)}...` : firstSentence;
    return streaming ? `${clipped} · streaming` : clipped;
}

export function transcriptRole(entry) {
    if (entry.kind === "thinking_text") return "thinking";
    if (entry.kind === "tool_use") return "tool";
    if (entry.kind === "tool_result") return "tool-result";
    if (entry.kind === "system_notice") return "system";
    return entry.role === "user" ? "user" : "assistant";
}

export function entryLabel(entry) {
    if (entry.kind === "thinking_text") return "Thinking";
    if (entry.kind === "tool_use") return `Tool · ${entry.toolName || entry.taskId || "tool"}`;
    if (entry.kind === "tool_result") return `Tool · ${entry.toolName || entry.taskId || "tool"}`;
    if (entry.kind === "system_notice") return "System";
    return entry.role === "user" ? "User" : "OBS";
}

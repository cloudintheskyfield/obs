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
    const segments = normalized.split(/[\\/]+/).filter(Boolean);
    const parentSegments = segments.slice(0, -1).filter((segment, index, list) => segment !== list[index - 1]);
    if (parentSegments.length === 0) {
        return segments[segments.length - 1] || normalized;
    }
    if (parentSegments.length <= maxParts) {
        return parentSegments.join(" / ");
    }
    return `... / ${parentSegments.slice(-maxParts).join(" / ")}`;
}

export function normalizeDisplayText(text, { preserveCodeFences = true } = {}) {
    let raw = String(text || "").replace(/\r\n/g, "\n");
    if (!raw) {
        return "";
    }
    raw = raw
        .replace(/^\s*\n+/, "")
        .replace(/[ \t]+\n/g, "\n")
        .replace(/\n[ \t]+/g, "\n")
        .trimEnd();

    if (!preserveCodeFences || !raw.includes("```")) {
        raw = raw.replace(/\n(?:[ \t]*\n){2,}/g, "\n\n");
    }
    return raw;
}

let _katex = null;
async function _loadKatex() {
    if (_katex) return _katex;
    try {
        const mod = await import("katex");
        _katex = mod.default || mod;
    } catch {
        _katex = null;
    }
    return _katex;
}
// Pre-load KaTeX eagerly so first render is synchronous
_loadKatex();

function _renderMath(expr, displayMode) {
    if (!_katex) return `<code class="math-fallback">${escapeHtml(expr)}</code>`;
    try {
        return _katex.renderToString(expr, { throwOnError: false, displayMode, output: "html" });
    } catch {
        return `<code class="math-fallback">${escapeHtml(expr)}</code>`;
    }
}

// Extract and protect math blocks before HTML-escaping so $ signs don't get mangled.
// Returns { processed: string with placeholders, restore: fn(html) }
function _protectMath(source) {
    const blocks = [];
    let s = source;

    // Display math $$...$$
    s = s.replace(/\$\$([^$]+?)\$\$/gs, (_, expr) => {
        blocks.push({ expr: expr.trim(), display: true });
        return `\x00MATH${blocks.length - 1}\x00`;
    });
    // Inline math $...$  (not $$)
    s = s.replace(/(?<!\$)\$([^$\n]+?)\$(?!\$)/g, (_, expr) => {
        blocks.push({ expr: expr.trim(), display: false });
        return `\x00MATH${blocks.length - 1}\x00`;
    });

    const restore = (html) =>
        html.replace(/\x00MATH(\d+)\x00/g, (_, i) => {
            const { expr, display } = blocks[Number(i)];
            return display
                ? `<div class="math-block">${_renderMath(expr, true)}</div>`
                : _renderMath(expr, false);
        });

    return { processed: s, restore };
}

export function renderMarkdown(text) {
    const raw = normalizeDisplayText(text).trim();
    if (!raw) return "";

    const { processed: source, restore } = _protectMath(raw);
    const lines = source.split("\n");
    const html = [];
    let index = 0;

    const renderInline = (value) => {
        let s = escapeHtml(value);
        // inline code (before other replacements)
        s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
        // bold / italic
        s = s.replace(/\*\*\*([^*]+)\*\*\*/g, "<strong><em>$1</em></strong>");
        s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
        s = s.replace(/\*([^*\n]+)\*/g, "<em>$1</em>");
        s = s.replace(/~~([^~]+)~~/g, "<del>$1</del>");
        // named links [text](url)
        s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer noopener">$1</a>');
        // bare URLs (not already inside an <a>)
        s = s.replace(/(^|[\s(])((https?:\/\/)[^\s<>"&]+)/g, (_, pre, url) =>
            `${pre}<a href="${url}" target="_blank" rel="noreferrer noopener">${url}</a>`);
        // restore math placeholders
        return restore(s);
    };

    // Detect table: line starts and ends with |, and second line is a separator row
    const isTableRow = (ln) => /^\|.+\|$/.test(ln.trim());
    const isSeparatorRow = (ln) => /^\|[\s\-:|]+\|$/.test(ln.trim());

    while (index < lines.length) {
        const line = lines[index];
        const trimmed = line.trim();

        if (!trimmed) {
            index += 1;
            continue;
        }

        // ── fenced code block ──────────────────────────────────────────
        if (trimmed.startsWith("```")) {
            const lang = trimmed.slice(3).trim();
            const codeLines = [];
            index += 1;
            while (index < lines.length && !lines[index].trim().startsWith("```")) {
                codeLines.push(lines[index]);
                index += 1;
            }
            if (index < lines.length) index += 1;
            const langAttr = lang ? ` class="language-${escapeHtml(lang)}"` : "";
            html.push(`<pre><code${langAttr}>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
            continue;
        }

        // ── heading ────────────────────────────────────────────────────
        const headingMatch = trimmed.match(/^(#{1,6})\s+(.*)$/);
        if (headingMatch) {
            const level = headingMatch[1].length;
            html.push(`<h${level}>${renderInline(headingMatch[2])}</h${level}>`);
            index += 1;
            continue;
        }

        // ── horizontal rule ────────────────────────────────────────────
        if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
            html.push("<hr>");
            index += 1;
            continue;
        }

        // ── table ──────────────────────────────────────────────────────
        if (isTableRow(trimmed) && index + 1 < lines.length && isSeparatorRow(lines[index + 1])) {
            const parseRow = (ln) =>
                ln.trim().replace(/^\||\|$/g, "").split("|").map((cell) => cell.trim());

            const headers = parseRow(lines[index]);
            index += 2; // skip header + separator

            const dataRows = [];
            while (index < lines.length && isTableRow(lines[index])) {
                dataRows.push(parseRow(lines[index]));
                index += 1;
            }

            const thead = `<thead><tr>${headers.map((h) => `<th>${renderInline(h)}</th>`).join("")}</tr></thead>`;
            const tbody = dataRows.length
                ? `<tbody>${dataRows.map((row) => `<tr>${row.map((cell) => `<td>${renderInline(cell)}</td>`).join("")}</tr>`).join("")}</tbody>`
                : "";
            html.push(`<div class="md-table-wrap"><table>${thead}${tbody}</table></div>`);
            continue;
        }

        // ── ordered list ───────────────────────────────────────────────
        if (/^\d+\.\s+/.test(trimmed)) {
            const items = [];
            while (index < lines.length && /^\d+\.\s+/.test(lines[index].trim())) {
                items.push(lines[index].trim().replace(/^\d+\.\s+/, ""));
                index += 1;
            }
            html.push(`<ol>${items.map((item) => `<li>${renderInline(item)}</li>`).join("")}</ol>`);
            continue;
        }

        // ── unordered list ─────────────────────────────────────────────
        if (/^[-*+]\s+/.test(trimmed)) {
            const items = [];
            while (index < lines.length && /^[-*+]\s+/.test(lines[index].trim())) {
                items.push(lines[index].trim().replace(/^[-*+]\s+/, ""));
                index += 1;
            }
            html.push(`<ul>${items.map((item) => `<li>${renderInline(item)}</li>`).join("")}</ul>`);
            continue;
        }

        // ── blockquote ─────────────────────────────────────────────────
        if (/^>\s?/.test(trimmed)) {
            const quotes = [];
            while (index < lines.length && /^>\s?/.test(lines[index].trim())) {
                quotes.push(lines[index].trim().replace(/^>\s?/, ""));
                index += 1;
            }
            html.push(`<blockquote>${quotes.map((q) => renderInline(q)).join("<br>")}</blockquote>`);
            continue;
        }

        // ── paragraph ──────────────────────────────────────────────────
        // Stop collecting when we hit a line that starts a new block element
        // so that a bare paragraph like "加入方式：" followed immediately by
        // "- item" (no blank line) still produces separate <p> and <ul> nodes.
        const isBlockStart = (ln) => {
            const t = ln.trim();
            return !t
                || t.startsWith("```")
                || /^#{1,6}\s/.test(t)
                || /^[-*+]\s+/.test(t)
                || /^\d+\.\s+/.test(t)
                || /^>\s?/.test(t)
                || /^(-{3,}|\*{3,}|_{3,})$/.test(t)
                || (isTableRow(t) && false); // tables handled above; don't break mid-row
        };
        const paragraphLines = [];
        while (index < lines.length) {
            const cur = lines[index];
            if (!cur.trim()) break;             // blank line ends paragraph
            if (paragraphLines.length > 0 && isBlockStart(cur)) break; // block start
            paragraphLines.push(cur);
            index += 1;
        }
        html.push(`<p>${renderInline(paragraphLines.join("\n")).replace(/\n/g, "<br>")}</p>`);
    }

    return restore(html.join(""));
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

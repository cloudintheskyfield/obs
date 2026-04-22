import React, { useState, useMemo, useCallback, memo } from "react";

const LOG_RANGE_OPTIONS = [
    ["1h",     "最近 1h"],
    ["15m",    "最近 15m"],
    ["24h",    "最近 24h"],
    ["all",    "全部"],
    ["custom", "自定义"],
];

const PAGE_SIZE = 50; // entries per "load more" batch

// ── Formatters (lazy – only called when entry is expanded) ──────────────────

function indent(depth) {
    return "  ".repeat(depth);
}

function formatMultilineString(value, depth) {
    const lines = String(value || "").split("\n");
    if (lines.length <= 1) return `"${value}"`;
    return ['"""', ...lines.map((l) => `${indent(depth + 1)}${l}`), `${indent(depth)}"""`].join("\n");
}

function formatStructuredValue(value, depth = 0) {
    if (value === null) return "null";
    if (value === undefined) return "undefined";
    if (typeof value === "string") return value.includes("\n") ? formatMultilineString(value, depth) : `"${value}"`;
    if (typeof value === "number" || typeof value === "boolean") return String(value);
    if (Array.isArray(value)) {
        if (!value.length) return "[]";
        return ["[", ...value.map((item) => `${indent(depth + 1)}${formatStructuredValue(item, depth + 1)}`), `${indent(depth)}]`].join("\n");
    }
    if (typeof value === "object") {
        const entries = Object.entries(value);
        if (!entries.length) return "{}";
        return [
            "{",
            ...entries.map(([k, v]) => {
                const fv = formatStructuredValue(v, depth + 1);
                if (typeof v === "string" && v.includes("\n"))
                    return `${indent(depth + 1)}${k}:\n${indent(depth + 2)}${fv.replace(/\n/g, `\n${indent(depth + 2)}`)}`;
                return `${indent(depth + 1)}${k}: ${fv}`;
            }),
            `${indent(depth)}}`,
        ].join("\n");
    }
    return String(value);
}

// ── Time group helpers ───────────────────────────────────────────────────────

function getGroupLabel(ts, now) {
    const diff = now - ts;
    if (diff < 5 * 60_000)   return "刚刚";
    if (diff < 60 * 60_000)  return "最近 1 小时";
    if (diff < 24 * 3600_000) return "今天早些时候";
    return "更早";
}

const GROUP_ORDER = ["刚刚", "最近 1 小时", "今天早些时候", "更早"];

function groupLogs(entries) {
    const now = Date.now();
    const groups = {};
    for (const entry of entries) {
        const label = getGroupLabel(new Date(entry.timestamp || now).getTime(), now);
        (groups[label] ??= []).push(entry);
    }
    return GROUP_ORDER.filter((g) => groups[g]).map((g) => ({ label: g, entries: groups[g] }));
}

// ── Single collapsed/expandable log entry ────────────────────────────────────

const LogEntry = memo(function LogEntry({ entry }) {
    const [open, setOpen] = useState(false);
    const title = [entry.type, entry.phase, entry.direction].filter(Boolean).join(" · ");
    const timeLabel = new Date(entry.timestamp || Date.now()).toLocaleTimeString([], {
        hour: "2-digit", minute: "2-digit", second: "2-digit",
    });
    const formatted = useMemo(() => open ? formatStructuredValue(entry.payload || {}) : null, [open, entry.payload]);

    return (
        <article className={`log-entry${open ? " expanded" : ""}`}>
            <button type="button" className="log-entry-head" onClick={() => setOpen((v) => !v)}>
                <i className={`fas fa-chevron-right log-entry-chevron${open ? " open" : ""}`} aria-hidden="true" />
                <strong className="log-entry-title">{title || "log"}</strong>
                <span className="log-entry-time">{timeLabel}</span>
            </button>
            {open && (
                <pre className="log-entry-body"><code>{formatted}</code></pre>
            )}
        </article>
    );
});

// ── Main drawer ──────────────────────────────────────────────────────────────

export default function LogsDrawer({
    open,
    logRange,
    setLogRange,
    logsFrom,
    setLogsFrom,
    logsTo,
    setLogsTo,
    onRefresh,
    onClose,
    logs,
    threadTitle,
    threadId,
}) {
    const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);

    // Reset visible count when the log range or session changes
    const totalCount = logs.length;
    const sliced = useMemo(() => logs.slice(0, visibleCount), [logs, visibleCount]);
    const groups = useMemo(() => groupLogs(sliced), [sliced]);
    const hasMore = visibleCount < totalCount;

    const handleRangeChange = useCallback((e) => {
        setLogRange(e.target.value || "1h");
        setVisibleCount(PAGE_SIZE);
    }, [setLogRange]);

    return (
        <section id="logs-drawer" className={`logs-drawer${open ? "" : " hidden"}`} aria-hidden={open ? "false" : "true"}>
            <div className="logs-backdrop" onClick={onClose} />
            <div className="logs-sheet">
                <div className="logs-header">
                    <div className="logs-header-copy">
                        <div className="logs-title-row">
                            <strong>LLM Logs</strong>
                            <span className="logs-meta">
                                Structured request / response events
                                {totalCount > 0 && <em className="logs-count"> · {totalCount} 条</em>}
                            </span>
                        </div>
                        {(threadTitle || threadId) && (
                            <div className="logs-thread-scope" title={threadId || undefined}>
                                <span className="logs-thread-badge">当前 Thread</span>
                                {threadTitle && <strong className="logs-thread-title">{threadTitle}</strong>}
                                {threadId && <code className="logs-thread-id">{threadId}</code>}
                            </div>
                        )}
                        <div className="logs-scope-note">只显示当前 thread 对应的日志</div>
                    </div>
                    <div className="logs-filters">
                        <select
                            className="mode-select logs-range-select"
                            value={logRange}
                            onChange={handleRangeChange}
                        >
                            {LOG_RANGE_OPTIONS.map(([value, label]) => (
                                <option key={value} value={value}>{label}</option>
                            ))}
                        </select>
                        {logRange === "custom" && (
                            <>
                                <input className="logs-time-input" type="datetime-local" value={logsFrom} onChange={(e) => setLogsFrom(e.target.value)} />
                                <input className="logs-time-input" type="datetime-local" value={logsTo} onChange={(e) => setLogsTo(e.target.value)} />
                            </>
                        )}
                        <button className="tiny-pill" type="button" onClick={onRefresh}>Refresh</button>
                    </div>
                    <button className="icon-button" type="button" title="关闭日志" onClick={onClose}>
                        <i className="fas fa-times" />
                    </button>
                </div>

                <div className="logs-list">
                    {logs.length === 0 ? (
                        <p className="panel-empty">No LLM logs yet.</p>
                    ) : (
                        <>
                            {groups.map(({ label, entries }) => (
                                <div key={label} className="log-group">
                                    <div className="log-group-label">{label}</div>
                                    {entries.map((entry) => (
                                        <LogEntry key={entry.id} entry={entry} />
                                    ))}
                                </div>
                            ))}
                            {hasMore && (
                                <button
                                    type="button"
                                    className="log-load-more"
                                    onClick={() => setVisibleCount((n) => n + PAGE_SIZE)}
                                >
                                    加载更多 · 还剩 {totalCount - visibleCount} 条
                                </button>
                            )}
                        </>
                    )}
                </div>
            </div>
        </section>
    );
}

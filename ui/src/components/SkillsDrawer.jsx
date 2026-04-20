import React, { useState } from "react";

const DISPLAY_NAME_MAP = {
    "code-sandbox": "Python",
    "file-operations": "File",
    "terminal": "Terminal",
    "web-search": "Web Search",
    "computer-use": "Computer Use",
    "weather": "Weather"
};

function displayName(skill) {
    return DISPLAY_NAME_MAP[skill.name] || skill.name;
}

function skillMeta(skill) {
    const description = skill.description || skill.name;
    const tools = Array.isArray(skill.tool_names) && skill.tool_names.length
        ? `Tools: ${skill.tool_names.join(", ")}`
        : "";
    return [description, tools].filter(Boolean).join(" · ");
}

function formatInstallDate(iso) {
    if (!iso || iso.startsWith("1970")) return null;
    try {
        return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
    } catch {
        return null;
    }
}

const BLANK_MANUAL = { name: "", skill_md: "", python_code: "" };
const BLANK_URL = { url: "", name: "" };

const SORT_OPTIONS = [
    { key: "time_asc",  label: "Time ↑",  icon: "fa-clock",      compare: (a, b) => (a.installed_at || "").localeCompare(b.installed_at || "") },
    { key: "time_desc", label: "Time ↓",  icon: "fa-clock",      compare: (a, b) => (b.installed_at || "").localeCompare(a.installed_at || "") },
    { key: "name_asc",  label: "A → Z",   icon: "fa-sort-alpha-down", compare: (a, b) => displayName(a).localeCompare(displayName(b), "en", { sensitivity: "base" }) },
    { key: "name_desc", label: "Z → A",   icon: "fa-sort-alpha-up",   compare: (a, b) => displayName(b).localeCompare(displayName(a), "en", { sensitivity: "base" }) },
];

export default function SkillsDrawer({
    open,
    skills,
    selectedSkills,
    onToggleAll,
    onToggleSkill,
    onClose,
    onReload,
    onInstall,
    onDelete,
}) {
    const [showInstall, setShowInstall] = useState(false);
    const [installTab, setInstallTab] = useState("url");
    const [manualForm, setManualForm] = useState(BLANK_MANUAL);
    const [urlForm, setUrlForm] = useState(BLANK_URL);
    const [urlPreview, setUrlPreview] = useState("");
    const [fetching, setFetching] = useState(false);
    const [installing, setInstalling] = useState(false);
    const [reloading, setReloading] = useState(false);
    const [deletingSkill, setDeletingSkill] = useState(null);
    const [feedback, setFeedback] = useState(null);
    const [sortKey, setSortKey] = useState("time_asc");

    const sortOption = SORT_OPTIONS.find(o => o.key === sortKey) || SORT_OPTIONS[0];
    const sortedSkills = [...skills].sort(sortOption.compare);
    // Protected skills are always-on; exclude them from the "All" toggle calculation
    const toggleableSkills = sortedSkills.filter(s => !s.protected);
    const allSelected = toggleableSkills.length > 0 && toggleableSkills.every(s => selectedSkills.includes(s.name));

    function resetInstall() {
        setShowInstall(false);
        setFeedback(null);
        setManualForm(BLANK_MANUAL);
        setUrlForm(BLANK_URL);
        setUrlPreview("");
    }

    async function handleReload() {
        setReloading(true);
        setFeedback(null);
        try {
            await onReload?.();
            setFeedback({ ok: true, msg: "Skills reloaded." });
        } catch {
            setFeedback({ ok: false, msg: "Reload failed." });
        } finally {
            setReloading(false);
        }
    }

    async function handleFetchPreview() {
        if (!urlForm.url.trim()) return;
        setFetching(true);
        setFeedback(null);
        setUrlPreview("");
        try {
            const resp = await fetch(urlForm.url.trim());
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            setUrlPreview(await resp.text());
        } catch (err) {
            setFeedback({ ok: false, msg: `Fetch failed: ${err.message}` });
        } finally {
            setFetching(false);
        }
    }

    async function handleInstallFromUrl(e) {
        e.preventDefault();
        if (!urlForm.url.trim()) { setFeedback({ ok: false, msg: "URL is required." }); return; }
        setInstalling(true);
        setFeedback(null);
        try {
            let skill_md = urlPreview;
            if (!skill_md) {
                const resp = await fetch(urlForm.url.trim());
                if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                skill_md = await resp.text();
            }
            let name = urlForm.name.trim();
            if (!name) {
                const m = skill_md.match(/^---[\s\S]*?^name:\s*(.+?)\s*$/m);
                name = m ? m[1].replace(/['"]/g, "").trim() : "";
            }
            if (!name) {
                name = urlForm.url.trim().replace(/\?.*$/, "").replace(/\/$/, "").split("/").pop().replace(/\.md$/i, "") || "unnamed-skill";
            }
            await onInstall?.({ name, skill_md, python_code: "" });
            setFeedback({ ok: true, msg: `Skill "${name}" installed.` });
            resetInstall();
        } catch (err) {
            setFeedback({ ok: false, msg: err.message || "Install failed." });
        } finally {
            setInstalling(false);
        }
    }

    async function handleInstallManual(e) {
        e.preventDefault();
        if (!manualForm.name.trim() || !manualForm.skill_md.trim()) {
            setFeedback({ ok: false, msg: "Name and SKILL.md content are required." }); return;
        }
        setInstalling(true);
        setFeedback(null);
        try {
            await onInstall?.(manualForm);
            setFeedback({ ok: true, msg: `Skill "${manualForm.name}" installed.` });
            resetInstall();
        } catch (err) {
            setFeedback({ ok: false, msg: err.message || "Install failed." });
        } finally {
            setInstalling(false);
        }
    }

    async function handleDelete(skillName) {
        if (!window.confirm(`Delete skill "${skillName}"?`)) return;
        setDeletingSkill(skillName);
        setFeedback(null);
        try {
            await onDelete?.(skillName);
            setFeedback({ ok: true, msg: `Skill "${skillName}" deleted.` });
        } catch (err) {
            setFeedback({ ok: false, msg: err.message || "Delete failed." });
        } finally {
            setDeletingSkill(null);
        }
    }

    return (
        <section className={`logs-drawer skills-drawer${open ? "" : " hidden"}`} aria-hidden={open ? "false" : "true"}>
            <div className="logs-backdrop" onClick={onClose} />
            <div className="logs-sheet skills-sheet">

                {/* Header */}
                <div className="logs-header">
                    <div>
                        <strong>Available Skills</strong>
                        <span className="logs-meta">Selected skills are the only ones the model can use.</span>
                    </div>
                    <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                        <button className="icon-button" type="button" title="Reload from disk" disabled={reloading} onClick={handleReload}>
                            <i className={`fas fa-sync-alt${reloading ? " fa-spin" : ""}`} />
                        </button>
                        <button className="icon-button" type="button" title="Install a skill"
                            onClick={() => { setShowInstall(v => !v); setFeedback(null); }}>
                            <i className="fas fa-plus" />
                        </button>
                        <button className="icon-button" type="button" title="Close" onClick={onClose}>
                            <i className="fas fa-times" />
                        </button>
                    </div>
                </div>

                {/* Sort bar */}
                <div style={{ display: "flex", gap: 4, padding: "6px 16px", borderBottom: "1px solid var(--border-color)", alignItems: "center" }}>
                    <span style={{ fontSize: 11, color: "var(--text-muted, #888)", marginRight: 4 }}>Sort:</span>
                    {SORT_OPTIONS.map(opt => (
                        <button
                            key={opt.key}
                            type="button"
                            onClick={() => setSortKey(opt.key)}
                            title={opt.label}
                            style={{
                                padding: "2px 9px",
                                fontSize: 11,
                                borderRadius: 4,
                                border: "1px solid var(--border-color)",
                                cursor: "pointer",
                                background: sortKey === opt.key ? "var(--color-primary, #1976d2)" : "var(--bg-secondary)",
                                color: sortKey === opt.key ? "#fff" : "inherit",
                                fontWeight: sortKey === opt.key ? 600 : 400,
                            }}
                        >
                            {opt.label}
                        </button>
                    ))}
                </div>

                {/* Feedback */}
                {feedback && (
                    <div style={{
                        padding: "6px 16px", fontSize: 12,
                        color: feedback.ok ? "var(--color-success, #4caf50)" : "var(--color-error, #f44336)",
                        borderBottom: "1px solid var(--border-color)"
                    }}>
                        {feedback.msg}
                    </div>
                )}

                {/* Install panel */}
                {showInstall && (
                    <div style={{ borderBottom: "1px solid var(--border-color)", padding: "12px 16px" }}>
                        <div style={{ display: "flex", gap: 0, marginBottom: 10 }}>
                            {["url", "manual"].map(tab => (
                                <button key={tab} type="button" onClick={() => setInstallTab(tab)} style={{
                                    flex: 1, padding: "5px 0", fontSize: 12, cursor: "pointer",
                                    border: "1px solid var(--border-color)",
                                    borderRadius: tab === "url" ? "4px 0 0 4px" : "0 4px 4px 0",
                                    background: installTab === tab ? "var(--color-primary, #1976d2)" : "var(--bg-secondary)",
                                    color: installTab === tab ? "#fff" : "inherit",
                                    fontWeight: installTab === tab ? 600 : 400,
                                }}>
                                    {tab === "url" ? "Install from URL" : "Paste SKILL.md"}
                                </button>
                            ))}
                        </div>

                        {installTab === "url" ? (
                            <form onSubmit={handleInstallFromUrl} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                                <div style={{ display: "flex", gap: 6 }}>
                                    <input type="text" placeholder="http://127.0.0.1:8001/skill.md"
                                        value={urlForm.url}
                                        onChange={e => { setUrlForm(f => ({ ...f, url: e.target.value })); setUrlPreview(""); }}
                                        style={{ flex: 1, padding: "4px 8px", borderRadius: 4, border: "1px solid var(--border-color)", fontSize: 12, background: "var(--bg-secondary)", color: "inherit" }}
                                    />
                                    <button type="button" disabled={fetching || !urlForm.url.trim()} onClick={handleFetchPreview}
                                        style={{ padding: "4px 10px", borderRadius: 4, border: "1px solid var(--border-color)", fontSize: 12, cursor: "pointer", background: "var(--bg-secondary)", color: "inherit", whiteSpace: "nowrap" }}>
                                        {fetching ? "…" : "Preview"}
                                    </button>
                                </div>
                                <input type="text" placeholder="Skill name (auto-detected)" value={urlForm.name}
                                    onChange={e => setUrlForm(f => ({ ...f, name: e.target.value }))}
                                    style={{ padding: "4px 8px", borderRadius: 4, border: "1px solid var(--border-color)", fontSize: 12, background: "var(--bg-secondary)", color: "inherit" }}
                                />
                                {urlPreview && (
                                    <textarea readOnly value={urlPreview} rows={5}
                                        style={{ padding: "4px 8px", borderRadius: 4, border: "1px solid var(--border-color)", fontSize: 11, fontFamily: "monospace", resize: "vertical", background: "var(--bg-secondary)", color: "inherit", opacity: 0.8 }}
                                    />
                                )}
                                <div style={{ display: "flex", gap: 8 }}>
                                    <button type="submit" disabled={installing}
                                        style={{ padding: "4px 14px", borderRadius: 4, background: "var(--color-primary, #1976d2)", color: "#fff", border: "none", fontSize: 12, cursor: "pointer" }}>
                                        {installing ? "Installing…" : "Install"}
                                    </button>
                                    <button type="button" onClick={resetInstall}
                                        style={{ padding: "4px 14px", borderRadius: 4, background: "transparent", border: "1px solid var(--border-color)", fontSize: 12, cursor: "pointer", color: "inherit" }}>
                                        Cancel
                                    </button>
                                </div>
                            </form>
                        ) : (
                            <form onSubmit={handleInstallManual} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                                <input type="text" placeholder="Skill name (e.g. my-skill)" value={manualForm.name}
                                    onChange={e => setManualForm(f => ({ ...f, name: e.target.value }))}
                                    style={{ padding: "4px 8px", borderRadius: 4, border: "1px solid var(--border-color)", fontSize: 12, background: "var(--bg-secondary)", color: "inherit" }}
                                />
                                <textarea placeholder={"SKILL.md content\n---\nname: my-skill\ndescription: ...\n---"} value={manualForm.skill_md} rows={6}
                                    onChange={e => setManualForm(f => ({ ...f, skill_md: e.target.value }))}
                                    style={{ padding: "4px 8px", borderRadius: 4, border: "1px solid var(--border-color)", fontSize: 11, fontFamily: "monospace", resize: "vertical", background: "var(--bg-secondary)", color: "inherit" }}
                                />
                                <textarea placeholder="Python implementation (optional)" value={manualForm.python_code} rows={3}
                                    onChange={e => setManualForm(f => ({ ...f, python_code: e.target.value }))}
                                    style={{ padding: "4px 8px", borderRadius: 4, border: "1px solid var(--border-color)", fontSize: 11, fontFamily: "monospace", resize: "vertical", background: "var(--bg-secondary)", color: "inherit" }}
                                />
                                <div style={{ display: "flex", gap: 8 }}>
                                    <button type="submit" disabled={installing}
                                        style={{ padding: "4px 14px", borderRadius: 4, background: "var(--color-primary, #1976d2)", color: "#fff", border: "none", fontSize: 12, cursor: "pointer" }}>
                                        {installing ? "Installing…" : "Install"}
                                    </button>
                                    <button type="button" onClick={resetInstall}
                                        style={{ padding: "4px 14px", borderRadius: 4, background: "transparent", border: "1px solid var(--border-color)", fontSize: 12, cursor: "pointer", color: "inherit" }}>
                                        Cancel
                                    </button>
                                </div>
                            </form>
                        )}
                    </div>
                )}

                {/* Skill list */}
                <div className="skills-list">
                    <button type="button" className={`skill-option all${allSelected ? " active" : ""}`} onClick={onToggleAll}>
                        <span className="skill-option-name">All</span>
                        <span className="skill-option-meta">{allSelected ? "Selected" : "Select all"}</span>
                    </button>

                    {sortedSkills.map(skill => {
                        const active = selectedSkills.includes(skill.name);
                        const dateLabel = formatInstallDate(skill.installed_at);
                        const isDeleting = deletingSkill === skill.name;
                        const isProtected = !!skill.protected;
                        return (
                            <div key={skill.name}
                                className={`skill-option${active ? " active" : ""}${isProtected ? " skill-protected" : ""}`}
                                style={{
                                    position: "relative",
                                    padding: 0,
                                    ...(isProtected ? {
                                        borderLeft: "3px solid var(--color-primary, #1976d2)",
                                        background: active
                                            ? "linear-gradient(90deg, rgba(25,118,210,0.18) 0%, transparent 100%)"
                                            : "linear-gradient(90deg, rgba(25,118,210,0.07) 0%, transparent 100%)",
                                    } : {}),
                                }}>
                                {/* Main clickable area — protected skills are not toggleable */}
                                <button type="button"
                                    style={{
                                        width: "100%", display: "flex", flexDirection: "column",
                                        alignItems: "flex-start", padding: "10px 14px 24px",
                                        background: "transparent", border: "none",
                                        cursor: isProtected ? "default" : "pointer",
                                        color: "inherit", textAlign: "left",
                                    }}
                                    onClick={() => { if (!isProtected) onToggleSkill(skill.name); }}>
                                    <span className="skill-option-name" style={{ display: "flex", alignItems: "center", gap: 6 }}>
                                        {isProtected && (
                                            <i className="fas fa-shield-alt" style={{ fontSize: 10, color: "var(--color-primary, #1976d2)", opacity: 0.9 }} title="System skill — protected" />
                                        )}
                                        {displayName(skill)}
                                        {isProtected && (
                                            <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.04em", color: "var(--color-primary, #1976d2)", opacity: 0.8, textTransform: "uppercase" }}>
                                                system
                                            </span>
                                        )}
                                    </span>
                                    <span className="skill-option-meta">
                                        {skillMeta(skill)}
                                        {dateLabel && <span style={{ marginLeft: 6, opacity: 0.5, fontSize: 10 }}>· {dateLabel}</span>}
                                    </span>
                                </button>

                                {/* Bottom-right icon */}
                                {isProtected ? (
                                    <span style={{
                                        position: "absolute", bottom: 8, right: 10,
                                        fontSize: 11, opacity: 0.35, pointerEvents: "none",
                                    }}>
                                        <i className="fas fa-lock" title="Protected — cannot be deleted" />
                                    </span>
                                ) : (
                                    <button type="button"
                                        title={`Delete ${skill.name}`}
                                        disabled={isDeleting}
                                        onClick={e => { e.stopPropagation(); handleDelete(skill.name); }}
                                        style={{
                                            position: "absolute", bottom: 6, right: 8,
                                            padding: "2px 4px", background: "transparent", border: "none",
                                            cursor: "pointer", fontSize: 11, opacity: 0.3,
                                            transition: "opacity 0.15s", color: "inherit",
                                        }}
                                        onMouseEnter={e => e.currentTarget.style.opacity = "1"}
                                        onMouseLeave={e => e.currentTarget.style.opacity = "0.3"}
                                    >
                                        <i className={`fas ${isDeleting ? "fa-spinner fa-spin" : "fa-trash-alt"}`} />
                                    </button>
                                )}
                            </div>
                        );
                    })}
                </div>
            </div>
        </section>
    );
}

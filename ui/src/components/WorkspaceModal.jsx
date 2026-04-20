import React from "react";
import { formatWorkspaceBreadcrumb } from "../lib/formatting.js";

export default function WorkspaceModal({
    open,
    currentPath,
    browserPath,
    browserEntries,
    browserParent,
    isLoading,
    draftPath,
    error,
    onDraftChange,
    onBrowse,
    onOpenParent,
    onClose,
    onSave,
    onNativePick,
    nativePickLabel = "Choose Folder",
    nativePickHelp = "",
}) {
    return (
        <section className={`logs-drawer workspace-drawer${open ? "" : " hidden"}`} aria-hidden={open ? "false" : "true"}>
            <div className="logs-backdrop" onClick={onClose} />
            <div className="logs-sheet workspace-sheet">
                <div className="logs-header workspace-header">
                    <div>
                        <strong>Workspace</strong>
                        <span className="logs-meta">Select the active working root for terminal, file editing, and Python execution.</span>
                    </div>
                    <div className="logs-filters workspace-toolbar">
                        <button className="tiny-pill" type="button" onClick={onNativePick}>
                            {nativePickLabel}
                        </button>
                        <button className="tiny-pill" type="button" onClick={onOpenParent} disabled={!browserParent || isLoading}>
                            Up One Level
                        </button>
                    </div>
                    <button className="icon-button" type="button" title="关闭工作区" onClick={onClose}>
                        <i className="fas fa-times" />
                    </button>
                </div>

                <div className="logs-list workspace-list">
                    {nativePickHelp ? <div className="workspace-picker-note">{nativePickHelp}</div> : null}

                    <div className="workspace-current">
                        <span className="workspace-current-label">Current workspace</span>
                        <strong>{currentPath || "Not set"}</strong>
                        <span className="workspace-current-breadcrumb">{formatWorkspaceBreadcrumb(currentPath)}</span>
                    </div>

                    <label className="field">
                        <span>Workspace path</span>
                        <input
                            type="text"
                            value={draftPath}
                            onChange={(event) => onDraftChange(event.target.value)}
                            placeholder="/absolute/path/to/workspace"
                        />
                    </label>

                    <div className="workspace-browser">
                        <div className="workspace-browser-head">
                            <div>
                                <span className="workspace-browser-label">Browse directories</span>
                                <strong>{browserPath || currentPath || "Workspace root"}</strong>
                            </div>
                        </div>

                        <div className="workspace-browser-list">
                            {isLoading ? (
                                <div className="workspace-browser-empty">Loading directories...</div>
                            ) : browserEntries.length === 0 ? (
                                <div className="workspace-browser-empty">No subdirectories available here.</div>
                            ) : browserEntries.map((entry) => (
                                <button
                                    key={entry.path}
                                    className={`workspace-entry${draftPath === entry.path ? " active" : ""}`}
                                    type="button"
                                    onClick={() => onBrowse(entry.path)}
                                >
                                    <span className="workspace-entry-name">
                                        <i className="fas fa-folder" />
                                        <span>{entry.name}</span>
                                    </span>
                                    <span className="workspace-entry-path">{formatWorkspaceBreadcrumb(entry.path, 4)}</span>
                                </button>
                            ))}
                        </div>
                    </div>

                    {error ? <div className="workspace-error">{error}</div> : null}
                </div>

                <div className="logs-header workspace-footer">
                    <div className="logs-meta">Changes are persisted locally and restored when you come back.</div>
                    <div className="workspace-actions">
                        <button className="secondary-btn" type="button" onClick={onClose}>Cancel</button>
                        <button className="primary-btn" type="button" onClick={onSave} disabled={!draftPath || isLoading}>Use This Workspace</button>
                    </div>
                </div>
            </div>
        </section>
    );
}

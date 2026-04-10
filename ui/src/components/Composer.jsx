import React from "react";

const IMAGE_TOKEN_PATTERN = /\[\[image:([^\]]+)\]\]/g;

function renderComposerPreview(value, images) {
    const source = String(value || "");
    const imageMap = new Map((images || []).map((image, index) => [image.id, { ...image, label: `Image ${index + 1}` }]));
    const nodes = [];
    let cursor = 0;
    let match;

    IMAGE_TOKEN_PATTERN.lastIndex = 0;
    while ((match = IMAGE_TOKEN_PATTERN.exec(source)) !== null) {
        const before = source.slice(cursor, match.index);
        if (before) {
            nodes.push(<span key={`text_${cursor}`}>{before}</span>);
        }
        const image = imageMap.get(match[1]);
        if (image) {
            nodes.push(
                <span key={image.id} className="composer-image-chip">
                    <span className="composer-image-chip-label">{image.label}</span>
                    <span className="composer-image-preview">
                        <img src={image.dataUrl} alt={image.name || image.label} />
                    </span>
                </span>
            );
        }
        cursor = match.index + match[0].length;
    }

    const tail = source.slice(cursor);
    if (tail) {
        nodes.push(<span key={`text_tail_${cursor}`}>{tail}</span>);
    }
    return nodes;
}

export default function Composer({
    selectedModel,
    onModelToggle,
    permissionMode,
    onPermissionToggle,
    thinkingMode,
    onThinkingToggle,
    value,
    onChange,
    onKeyDown,
    onPaste,
    onSend,
    isSending,
    images,
    logsOpen,
    onLogsToggle,
    skillsOpen,
    onSkillsToggle,
    workspacePath,
    workspaceSummary,
    onWorkspaceOpen,
    statusItems,
    inputRef
}) {
    return (
        <section className="composer-wrap">
            <div className="composer-card">
                <div className="composer-head">
                    <div className="composer-meta">
                        <div className="composer-workspace">
                            <span className="composer-placeholder">Current workspace</span>
                            <strong className="workspace-inline-path">{workspacePath || "No workspace selected"}</strong>
                            <span className="workspace-inline-breadcrumb">{workspaceSummary}</span>
                        </div>
                        <div className="composer-toggles">
                            <button className="tiny-pill" type="button" onClick={onModelToggle}>
                                Model · {selectedModel}
                            </button>
                            <button className="tiny-pill" type="button" onClick={onPermissionToggle}>
                                Permission · {permissionMode}
                            </button>
                            <button className={`tiny-pill${thinkingMode ? " active" : ""}`} type="button" onClick={onThinkingToggle}>
                                Thinking · {thinkingMode ? "on" : "off"}
                            </button>
                        </div>
                    </div>
                </div>
                {value ? (
                    <div className="composer-rich-preview" aria-hidden="true">
                        {renderComposerPreview(value, images)}
                    </div>
                ) : null}
                <textarea
                    id="message-input"
                    ref={inputRef}
                    rows="1"
                    value={value}
                    onChange={(event) => onChange(event.target.value)}
                    onKeyDown={onKeyDown}
                    onPaste={onPaste}
                    placeholder="Describe the task, mention files, or ask for a coordinated refactor"
                />
                <div className="composer-foot">
                    <div className="composer-left">
                        <button className="small-tool workspace-tool active" type="button" onClick={onWorkspaceOpen}>
                            <i className="fas fa-folder-tree" />
                            <span>Workspace</span>
                        </button>
                        <button className={`small-tool${logsOpen ? " active" : ""}`} type="button" onClick={onLogsToggle}>
                            <i className="fas fa-wave-square" />
                            <span>Logs</span>
                        </button>
                        <button className={`small-tool${skillsOpen ? " active" : ""}`} type="button" onClick={onSkillsToggle}>
                            <i className="fas fa-sliders" />
                            <span>Skills</span>
                        </button>
                    </div>
                    <div className="composer-right">
                        <button className={`send-btn${isSending ? " is-sending" : ""}`} type="button" onClick={onSend} disabled={isSending}>
                            <i className={`fas ${isSending ? "fa-spinner fa-spin" : "fa-arrow-up"}`} />
                        </button>
                    </div>
                </div>
            </div>

            <div className="statusline">
                <div className="statusline-group">
                    {statusItems.map((item) => (
                        <span key={item} className="status-item">{item}</span>
                    ))}
                </div>
            </div>
        </section>
    );
}

import React from "react";

export default function BaseDrawer({
    open,
    onClose,
    title,
    meta,
    headerExtra,
    actions,
    className = "",
    sheetClassName = "",
    id,
    children,
}) {
    return (
        <section
            id={id}
            className={`logs-drawer ${className}${open ? "" : " hidden"}`}
            aria-hidden={open ? "false" : "true"}
        >
            <div className="logs-backdrop" onClick={onClose} />
            <div className={`logs-sheet ${sheetClassName}`}>
                {(title || meta || actions || headerExtra) && (
                    <div className="logs-header">
                        <div className="logs-header-copy">
                            {(title || meta) && (
                                <div className="logs-title-row">
                                    {title && <strong>{title}</strong>}
                                    {meta && <span className="logs-meta">{meta}</span>}
                                </div>
                            )}
                            {headerExtra}
                        </div>
                        <div className="logs-filters" style={{ display: "flex", gap: 6, alignItems: "center" }}>
                            {actions}
                            <button type="button" className="icon-button logs-close" onClick={onClose} aria-label="Close">
                                <i className="fas fa-times" aria-hidden="true" />
                            </button>
                        </div>
                    </div>
                )}
                {children}
            </div>
        </section>
    );
}

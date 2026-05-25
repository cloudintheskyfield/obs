import React from "react";

export default function BaseDrawer({
    open,
    onClose,
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
                {children}
            </div>
        </section>
    );
}

export function createRequestIndicator(label, startedAt = Date.now()) {
    return {
        active: true,
        startedAt,
        label: label || "Working on your request",
    };
}

export function switchRequestStatus(setRequestIndicator, label, fallback = null) {
    setRequestIndicator((current) => current?.active ? {
        ...current,
        label: label || fallback || current.label || "Working",
    } : current);
}

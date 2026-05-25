export function joinList(items, fallback = "none") {
    return items.length ? items.join(" · ") : fallback;
}

export function localizeValue(node, key, locale, fallback = "") {
    if (!node || typeof node !== "object") {
        return fallback;
    }
    const localized = node[`${key}_${locale}`];
    if (localized) {
        return localized;
    }
    return node[key] || fallback;
}

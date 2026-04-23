"""
Skill Manager Skill — lets the OBS agent manage its own skills at runtime.
Calls the local OBS API (http://localhost:8000) internally.
"""
import json
import re
from typing import Any, Dict, Optional

try:
    import httpx
    _HAS_HTTPX = True
except ImportError:
    _HAS_HTTPX = False

try:
    from base_skill import BaseSkill, SkillResult
except ImportError:
    from .base_skill import BaseSkill, SkillResult  # type: ignore


_API_BASE = "http://localhost:8000"
_TIMEOUT = 20


def _rewrite_localhost(url: str) -> str:
    url = re.sub(r"127\.0\.0\.1", "host.docker.internal", url)
    url = re.sub(r"(?<![.\w])localhost(?![.\w])", "host.docker.internal", url)
    return url


async def _api(method: str, path: str, **kwargs) -> Dict[str, Any]:
    if not _HAS_HTTPX:
        raise RuntimeError("httpx is not installed inside the container")
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await getattr(client, method)(f"{_API_BASE}{path}", **kwargs)
        resp.raise_for_status()
        return resp.json()


class SkillManagerSkill(BaseSkill):
    name = "skill_manager"

    def __init__(self, **kwargs):
        super().__init__(
            name="skill_manager",
            description="Manage OBS agent skills — list, install from URL or content, delete, and reload",
        )

    # ------------------------------------------------------------------ #

    async def _list_skills(self) -> SkillResult:
        data = await _api("get", "/skill-catalog")
        skills = data.get("skills", [])
        if not skills:
            return SkillResult(success=True, content="No skills installed.")
        lines = ["Installed skills:\n"]
        for s in skills:
            protected = " 🔒" if s.get("protected") else ""
            tools = ", ".join(s.get("tool_names") or []) or "—"
            date = (s.get("installed_at") or "")[:10]
            lines.append(f"• **{s['name']}**{protected}  [{date}]")
            lines.append(f"  {s.get('description', '')}")
            lines.append(f"  Tools: {tools}")
        return SkillResult(success=True, content="\n".join(lines))

    async def _install_url(self, url: str, name: str = "") -> SkillResult:
        if not url:
            return SkillResult(success=False, error="url is required")
        payload: Dict[str, Any] = {"url": url}
        if name:
            payload["name"] = name
        data = await _api("post", "/skills/install-from-url", json=payload)
        if not data.get("success"):
            return SkillResult(success=False, error=data.get("error", "install failed"))
        entry = data.get("catalog_entry") or {}
        return SkillResult(
            success=True,
            content=f"Skill **{entry.get('name', name)}** installed successfully.\n"
                    f"Description: {entry.get('description', '')}\n"
                    f"Tools: {', '.join(entry.get('tool_names') or []) or '—'}",
        )

    async def _install_md(self, name: str, skill_md: str, python_code: str = "") -> SkillResult:
        if not name or not skill_md:
            return SkillResult(success=False, error="name and skill_md are required")
        data = await _api("post", "/skills/install", json={
            "name": name,
            "skill_md": skill_md,
            "python_code": python_code,
        })
        if not data.get("success"):
            return SkillResult(success=False, error=data.get("error", "install failed"))
        entry = data.get("catalog_entry") or {}
        return SkillResult(
            success=True,
            content=f"Skill **{entry.get('name', name)}** installed from content.\n"
                    f"Description: {entry.get('description', '')}",
        )

    async def _delete_skill(self, name: str) -> SkillResult:
        if not name:
            return SkillResult(success=False, error="name is required")
        data = await _api("delete", f"/skills/{name}")
        if not data.get("success"):
            return SkillResult(success=False, error=data.get("error", "delete failed"))
        return SkillResult(success=True, content=f"Skill **{name}** deleted.")

    async def _reload_skills(self) -> SkillResult:
        data = await _api("post", "/skills/reload")
        if not data.get("success"):
            return SkillResult(success=False, error=data.get("error", "reload failed"))
        info = data.get("reload", {})
        added = info.get("added") or []
        removed = info.get("removed") or []
        total = info.get("total", 0)
        parts = [f"Skills reloaded — {total} total."]
        if added:
            parts.append(f"Added: {', '.join(added)}")
        if removed:
            parts.append(f"Removed: {', '.join(removed)}")
        return SkillResult(success=True, content="\n".join(parts))

    async def _get_info(self, name: str) -> SkillResult:
        if not name:
            return SkillResult(success=False, error="name is required")
        data = await _api("get", "/skill-catalog")
        skill = next((s for s in data.get("skills", []) if s["name"] == name), None)
        if not skill:
            return SkillResult(success=False, error=f"Skill '{name}' not found")
        lines = [
            f"**{skill['name']}**{'  🔒 protected' if skill.get('protected') else ''}",
            f"Description: {skill.get('description', '')}",
            f"Tools: {', '.join(skill.get('tool_names') or []) or '—'}",
            f"Installed: {(skill.get('installed_at') or '')[:19]}",
            f"Location: {skill.get('location', '')}",
        ]
        return SkillResult(success=True, content="\n".join(lines))

    async def _search_store(self, query: str, include_github: bool = False) -> SkillResult:
        if not query:
            return SkillResult(success=False, error="query is required")
        params = f"q={query}"
        if include_github:
            params += "&include_github=true"
        data = await _api("get", f"/skills/store/search?{params}")
        if not data.get("success"):
            return SkillResult(success=False, error=data.get("error", "store search failed"))

        results = data.get("results", [])
        github_results = data.get("github_results", [])
        total = data.get("total", 0)

        if not results and not github_results:
            return SkillResult(
                success=True,
                content=(
                    f"No skills found in the store for '{query}'.\n"
                    "You can build a custom skill with:\n"
                    "  skill_manager command=\"install_md\" name=\"<name>\" skill_md=\"...\""
                ),
                metadata={"found": False, "query": query},
            )

        lines = [f"**Skill Store** — {total} result(s) for '{query}':\n"]
        for r in results:
            status = " ✅ installed" if r.get("installed") else ""
            lines.append(f"### {r['display_name']}{status}")
            lines.append(f"Name: `{r['name']}` · Category: {r.get('category', '—')}")
            lines.append(f"{r.get('description', '')}")
            tags = ", ".join(r.get("tags") or [])
            if tags:
                lines.append(f"Tags: {tags}")
            if not r.get("installed"):
                if r.get("skill_md"):
                    lines.append(f"**Install:** `skill_manager command=\"install_store\" name=\"{r['name']}\"`")
                elif r.get("skill_md_url"):
                    lines.append(f"**Install:** `skill_manager command=\"install_url\" url=\"{r['skill_md_url']}\"`")
            lines.append("")

        if github_results:
            lines.append("**From GitHub:**")
            for r in github_results:
                status = " ✅ installed" if r.get("installed") else ""
                lines.append(f"• **{r['name']}**{status} — {r.get('description', '')}")
                if r.get("skill_md_url"):
                    lines.append(f"  Install: `skill_manager command=\"install_url\" url=\"{r['skill_md_url']}\"`")

        return SkillResult(
            success=True,
            content="\n".join(lines),
            metadata={"found": True, "query": query, "count": total, "results": results},
        )

    async def _install_from_store(self, name: str) -> SkillResult:
        """Install a skill directly from the built-in registry by name."""
        if not name:
            return SkillResult(success=False, error="name is required")
        # Fetch the registry entry
        data = await _api("get", f"/skills/store/search?q={name}")
        if not data.get("success"):
            return SkillResult(success=False, error=data.get("error", "store unavailable"))
        results = data.get("results", [])
        # Find exact or best match
        entry = next((r for r in results if r["name"] == name), None)
        if entry is None and results:
            entry = results[0]
        if entry is None:
            return SkillResult(
                success=False,
                error=f"Skill '{name}' not found in store. Use search_store to browse available skills.",
            )
        if entry.get("installed"):
            return SkillResult(success=True, content=f"Skill **{entry['name']}** is already installed.")
        if entry.get("skill_md"):
            return await self._install_md(
                name=entry["name"],
                skill_md=entry["skill_md"],
            )
        elif entry.get("skill_md_url"):
            return await self._install_url(url=entry["skill_md_url"], name=entry["name"])
        else:
            return SkillResult(success=False, error=f"No installable content for skill '{name}'")

    # ------------------------------------------------------------------ #

    async def execute(self, command: str = "list", **kwargs) -> SkillResult:
        try:
            if command == "list":
                return await self._list_skills()
            elif command == "install_url":
                return await self._install_url(
                    url=kwargs.get("url", ""),
                    name=kwargs.get("name", ""),
                )
            elif command == "install_md":
                return await self._install_md(
                    name=kwargs.get("name", ""),
                    skill_md=kwargs.get("skill_md", ""),
                    python_code=kwargs.get("python_code", ""),
                )
            elif command == "delete":
                return await self._delete_skill(name=kwargs.get("name", ""))
            elif command == "reload":
                return await self._reload_skills()
            elif command == "info":
                return await self._get_info(name=kwargs.get("name", ""))
            elif command == "search_store":
                return await self._search_store(
                    query=kwargs.get("query", ""),
                    include_github=bool(kwargs.get("include_github", False)),
                )
            elif command == "install_store":
                return await self._install_from_store(name=kwargs.get("name", ""))
            else:
                return SkillResult(
                    success=False,
                    error=(
                        f"Unknown command '{command}'. "
                        "Available: list, install_url, install_md, install_store, search_store, delete, reload, info"
                    ),
                )
        except Exception as exc:
            return SkillResult(success=False, error=str(exc))

"""Harness skill manager."""
import os
import json
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone

from loguru import logger

from base_skill import BaseSkill, SkillResult
from skill_loader import SkillLoader


class InstructionOnlySkill(BaseSkill):
    """Minimal executable wrapper for documentation-only skills."""

    def __init__(self, skill_name: str, description: str, instructions: str):
        super().__init__(
            name=skill_name,
            description=description or f"Documentation helper for {skill_name}",
        )
        self._instructions = instructions.strip()
        self.add_parameter(
            "query",
            "str",
            "Optional question or topic to focus when returning the skill instructions",
            False,
            "",
        )

    async def execute(self, **kwargs) -> SkillResult:
        query = str(kwargs.get("query") or "").strip()
        content = self._instructions
        if query:
            content = f"Requested topic: {query}\n\n{content}"
        return SkillResult(
            success=True,
            content=content or "No instructions available.",
            metadata={"mode": "instruction_only"},
        )


class SkillManager:
    """Manage the FindSkills-backed Harness skill set."""

    HARNESS_SPEC_SKILLS = {
        "desktop-commander",
        "file-manager",
        "filesystem",
        "agent-skills",
        "skill-management-python-runtime",
        "computer-use",
        "web-e2e",
        "playwright-e2e",
        "web-testing-playwright-e2e",
        "e2e",
        "web-search-free",
        "search",
        "web-scraper-pro",
        "firecrawl-scraper",
        "skill-lookup",
        "skill-manager",
    }

    TOOL_SKILL_ALIASES = {
        "advanced_web_search": "web-search-free",
        "web_search": "web-search-free",
        "bash": "desktop-commander",
        "str_replace_editor": "file-manager",
        "computer": "computer-use",
        "skill_manager": "skill-manager",
    }

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.skills: Dict[str, BaseSkill] = {}
        self.skill_loader = SkillLoader(skills_root=config.get("skills_dir"))
        self._initialize_skills()
    
    def _initialize_skills(self):
        """Initialize skills from the configured project skills directory."""
        work_dir = self.config.get("work_dir", "workspace")
        screenshot_dir = self.config.get("screenshot_dir", "screenshots")
        
        all_definitions = self.skill_loader.load_all_skills()
        skill_definitions = {
            name: skill_def
            for name, skill_def in all_definitions.items()
            if name in self.HARNESS_SPEC_SKILLS
        }
        skipped = sorted(set(all_definitions) - set(skill_definitions))
        if skipped:
            logger.info(f"Filtered non-harness skills from default runtime: {skipped}")
        self.skill_loader.skills = dict(skill_definitions)
        logger.info(f"Loaded {len(skill_definitions)} harness skill definitions from {self.skill_loader.skills_root}")
        
        # 从skill definitions创建skill实例
        for skill_name, skill_def in skill_definitions.items():
            if self._should_enable_skill(skill_name):
                try:
                    # 尝试从Level 3 Python实现创建实例
                    skill_instance = self._create_skill_instance(skill_name, skill_def, work_dir, screenshot_dir)
                    
                    if skill_instance:
                        # 关联SKILL.md定义
                        skill_instance.skill_definition = skill_def
                        
                        # Skip regular web_search if we already have advanced web_search loaded,
                        # but associate the SKILL.md definition so it doesn't warn as missing
                        self.skills[skill_name] = skill_instance
                        logger.info(f"Initialized skill from {self.skill_loader.skills_root}: {skill_name} -> {skill_instance.name}")
                    else:
                        logger.debug(f"Skill '{skill_name}' loaded as definition-only (no Python tools, instructions only)")
                        
                except Exception as e:
                    logger.error(f"Error initializing skill {skill_name}: {e}")
        
        logger.info(f"Initialized {len(self.skills)} skills: {list(self.skills.keys())}")
    
    def _should_enable_skill(self, skill_name: str) -> bool:
        """检查skill是否应该启用"""
        skill_config_map = {
            "computer-use": "enable_computer_use",
            "file-manager": "enable_text_editor",
            "filesystem": "enable_text_editor",
            "desktop-commander": "enable_bash",
        }
        
        config_key = skill_config_map.get(skill_name)
        if config_key:
            return self.config.get(config_key, True)
        
        # 默认启用未知的skills
        return True
    
    def _create_skill_instance(self, skill_name: str, skill_def, work_dir: str, screenshot_dir: str) -> Optional[BaseSkill]:
        """从skill definition创建skill实例"""
        if skill_def.skill_class:
            # 使用Level 3的Python实现
            try:
                # 根据skill类型传递适当的参数
                if skill_name == "computer-use":
                    return skill_def.skill_class(screenshot_dir=screenshot_dir)
                elif skill_name in ["file-manager", "filesystem", "desktop-commander"]:
                    return skill_def.skill_class(work_dir=work_dir)
                else:
                    # 尝试通用初始化
                    return skill_def.skill_class()
                    
            except Exception as e:
                logger.error(f"Failed to create instance from Level 3 implementation for {skill_name}: {e}")

        instructions = getattr(skill_def, "instructions", "")
        if instructions.strip():
            logger.debug(f"Skill '{skill_name}' has no runtime backend; using instruction-only wrapper")
            return InstructionOnlySkill(skill_name, skill_def.description, instructions)

        logger.debug(f"Skill '{skill_name}' has no Python implementation; will be used as context instructions only")
        return None
    
    def get_skill(self, name: str) -> Optional[BaseSkill]:
        """获取指定Skill"""
        resolved_name = self.resolve_skill_name_for_tool(name) or name
        return self.skills.get(name) or self.skills.get(resolved_name)

    def get_current_workspace(self) -> str:
        for skill_name in ["desktop-commander", "file-manager"]:
            skill = self.skills.get(skill_name)
            if skill is not None and hasattr(skill, "work_dir"):
                return str(Path(skill.work_dir).resolve())

        return str(Path(self.config.get("work_dir", "workspace")).expanduser().resolve())

    def set_workspace(self, work_dir: str) -> str:
        workspace = Path(work_dir).expanduser().resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        self.config["work_dir"] = str(workspace)

        for skill_name in ["desktop-commander", "file-manager"]:
            skill = self.skills.get(skill_name)
            if skill is None or not hasattr(skill, "work_dir"):
                continue
            skill.work_dir = workspace
            skill.work_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Workspace updated to {workspace}")
        return str(workspace)

    def resolve_skill_name_for_tool(self, tool_name: str) -> Optional[str]:
        """Map runtime tool names back to SKILL.md skill names."""
        if tool_name in self.TOOL_SKILL_ALIASES:
            return self.TOOL_SKILL_ALIASES[tool_name]

        if tool_name in self.skill_loader.skills:
            return tool_name

        return None
    
    def list_skills(self) -> List[Dict[str, Any]]:
        """列出所有Skills"""
        items = []
        for skill_name, skill in self.skills.items():
            item = skill.to_dict()
            item["name"] = skill_name
            item["tool_name"] = getattr(skill, "name", skill_name)
            items.append(item)
        return items
    
    def get_enabled_skills(self) -> Dict[str, BaseSkill]:
        """获取所有启用的Skills"""
        return {name: skill for name, skill in self.skills.items() if skill.enabled}
    
    def enable_skill(self, name: str) -> bool:
        """启用Skill"""
        resolved_name = self.resolve_skill_name_for_tool(name) or name
        if resolved_name in self.skills:
            self.skills[resolved_name].enabled = True
            return True
        return False
    
    def disable_skill(self, name: str) -> bool:
        """禁用Skill"""
        resolved_name = self.resolve_skill_name_for_tool(name) or name
        if resolved_name in self.skills:
            self.skills[resolved_name].enabled = False
            return True
        return False
    
    async def execute_skill(
        self,
        skill_name: str,
        **kwargs
    ) -> SkillResult:
        """执行指定Skill"""
        if skill_name not in self.skills:
            resolved_name = self.resolve_skill_name_for_tool(skill_name)
        else:
            resolved_name = skill_name

        if resolved_name not in self.skills:
            return SkillResult(
                success=False,
                error=f"Unknown skill: {skill_name}",
                metadata={
                    "available_skills": list(self.skills.keys()),
                    "requested_skill": skill_name
                }
            )
        
        skill = self.skills[resolved_name]
        
        if not skill.enabled:
            return SkillResult(
                success=False,
                error=f"Skill '{skill_name}' is disabled",
                metadata={"skill_name": skill_name}
            )
        
        logger.info(f"Executing skill: {resolved_name} via {skill_name}")
        
        try:
            result = await skill.safe_execute(**kwargs)
            result.metadata["skill_name"] = resolved_name
            result.metadata["tool_name"] = skill_name
            result.metadata["execution_timestamp"] = datetime.now().isoformat()
            
            if result.success:
                logger.info(f"Skill {skill_name} executed successfully")
            else:
                logger.warning(f"Skill {skill_name} execution failed: {result.error}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error executing skill {skill_name}: {e}")
            return SkillResult(
                success=False,
                error=f"Unexpected error executing {skill_name}: {str(e)}",
                metadata={"skill_name": skill_name}
            )
    
    async def cleanup(self):
        """清理所有Skills资源"""
        logger.info("Cleaning up skills...")
        
        for skill_name, skill in self.skills.items():
            try:
                if hasattr(skill, 'cleanup'):
                    await skill.cleanup()
                    logger.debug(f"Cleaned up skill: {skill_name}")
            except Exception as e:
                logger.error(f"Error cleaning up skill {skill_name}: {e}")
        
        logger.info("Skills cleanup completed")
    
    def get_skill_info(self, skill_name: str) -> Optional[Dict[str, Any]]:
        """获取Skill详细信息 - 包含SKILL.md的完整instructions (Level 2)"""
        resolved_name = self.resolve_skill_name_for_tool(skill_name) or skill_name
        if resolved_name not in self.skills:
            return None
        
        skill = self.skills[resolved_name]
        info = {
            **skill.to_dict(),
            "name": resolved_name,
            "tool_name": getattr(skill, "name", resolved_name),
            "usage_examples": self._get_usage_examples(resolved_name)
        }
        
        if skill.skill_definition:
            info["instructions"] = skill.skill_definition.instructions
            info["skill_directory"] = str(skill.skill_definition.skill_dir)
        
        return info
    
    def _get_usage_examples(self, skill_name: str) -> List[Dict[str, str]]:
        """获取Skill使用示例"""
        examples = {
            "computer-use": [
                {
                    "description": "Take a screenshot",
                    "command": '{"action": "screenshot"}'
                },
                {
                    "description": "Click at coordinates",
                    "command": '{"action": "click", "coordinate": [640, 360]}'
                },
                {
                    "description": "Type text",
                    "command": '{"action": "type", "text": "Hello World"}'
                },
                {
                    "description": "Navigate to URL",
                    "command": '{"action": "navigate", "url": "https://example.com"}'
                }
            ],
            "file-manager": [
                {
                    "description": "View a file",
                    "command": '{"command": "view", "path": "example.txt"}'
                },
                {
                    "description": "Create a new file",
                    "command": '{"command": "create", "path": "new_file.txt", "file_text": "Hello World"}'
                },
                {
                    "description": "Replace text in file",
                    "command": '{"command": "str_replace", "path": "example.txt", "old_str": "old", "new_str": "new"}'
                },
                {
                    "description": "View specific lines",
                    "command": '{"command": "view", "path": "example.txt", "view_range": [1, 10]}'
                }
            ],
            "desktop-commander": [
                {
                    "description": "List files",
                    "command": '{"command": "ls -la"}'
                },
                {
                    "description": "Run Python script",
                    "command": '{"command": "python script.py"}'
                },
                {
                    "description": "Install package",
                    "command": '{"command": "pip install requests"}'
                },
                {
                    "description": "Background process",
                    "command": '{"command": "python server.py", "background": true}'
                }
            ]
        }
        
        return examples.get(skill_name, [])
    
    def get_skills_status(self) -> Dict[str, Any]:
        """获取所有Skills状态"""
        status = {
            "total_skills": len(self.skills),
            "enabled_skills": len(self.get_enabled_skills()),
            "disabled_skills": len(self.skills) - len(self.get_enabled_skills()),
            "skills": {}
        }
        
        for name, skill in self.skills.items():
            status["skills"][name] = {
                "enabled": skill.enabled,
                "description": skill.description,
                "parameters_count": len(skill.parameters)
            }
        
        return status
    
    async def health_check(self) -> Dict[str, Any]:
        """健康检查所有Skills"""
        health_status = {
            "overall_healthy": True,
            "timestamp": datetime.now().isoformat(),
            "skills": {}
        }

        if not self.skills:
            health_status["overall_healthy"] = False
            return health_status
        
        for skill_name, skill in self.skills.items():
            try:
                skill_healthy = skill.enabled and hasattr(skill, 'execute')
                
                health_status["skills"][skill_name] = {
                    "healthy": skill_healthy,
                    "enabled": skill.enabled,
                    "error": None
                }
                
                if not skill_healthy:
                    health_status["overall_healthy"] = False
                    
            except Exception as e:
                health_status["skills"][skill_name] = {
                    "healthy": False,
                    "enabled": skill.enabled,
                    "error": str(e)
                }
                health_status["overall_healthy"] = False
                logger.error(f"Health check failed for skill {skill_name}: {e}")
        
        return health_status
    
    def get_anthropic_tools(self) -> List[Dict[str, Any]]:
        """获取符合Anthropic API规范的Tool定义列表
        
        使用SKILL.md的Level 1 metadata (name + description)
        
        返回格式符合Claude API的tools参数：
        [
            {
                "name": "tool_name",
                "description": "Tool description from SKILL.md",
                "input_schema": {
                    "type": "object",
                    "properties": {...},
                    "required": [...]
                }
            },
            ...
        ]
        """
        tools = []
        seen_tool_names = set()
        
        for skill_name, skill in self.get_enabled_skills().items():
            try:
                tool_def = skill.to_anthropic_tool()
                tool_name = tool_def.get("name")
                if tool_name in seen_tool_names:
                    logger.debug(f"Skipping duplicate tool definition: {tool_name}")
                    continue

                tools.append(tool_def)
                if tool_name:
                    seen_tool_names.add(tool_name)
                
                if skill.skill_definition:
                    logger.debug(f"Generated tool from SKILL.md: {skill.skill_definition.name}")
                else:
                    logger.warning(f"No SKILL.md found for {skill_name}, using fallback")
                    
            except Exception as e:
                logger.error(f"Error generating tool definition for {skill_name}: {e}")
        
        logger.info(f"Generated {len(tools)} Anthropic tool definitions from SKILL.md")
        return tools
    
    def get_skill_instructions(self, skill_name: str) -> Optional[str]:
        """获取Skill的Level 2 instructions (当skill被触发时加载)"""
        resolved_name = self.resolve_skill_name_for_tool(skill_name) or skill_name

        skill = self.skills.get(resolved_name)
        if skill and skill.skill_definition:
            return skill.skill_definition.instructions

        definition = self.skill_loader.skills.get(resolved_name)
        if definition:
            return definition.instructions

        return None
    
    def list_skill_metadata(self) -> Dict[str, Dict[str, str]]:
        """列出所有Skills的Level 1 metadata (轻量级)"""
        return {
            name: metadata
            for name, metadata in self.skill_loader.get_all_skill_metadata().items()
            if name in self.HARNESS_SPEC_SKILLS
        }

    def get_skill_metadata_for_tool(self, tool_name: str) -> Optional[Dict[str, str]]:
        resolved_name = self.resolve_skill_name_for_tool(tool_name)
        if not resolved_name:
            return None

        metadata = self.list_skill_metadata().get(resolved_name)
        if not metadata:
            return None

        definition = self.skill_loader.skills.get(resolved_name)
        location = str(getattr(definition, "skill_file", definition.skill_dir / "SKILL.md")) if definition else ""
        return {
            **metadata,
            "location": location,
            "tool_name": tool_name,
        }

    def build_skill_index(self, tool_names: Optional[List[str]] = None) -> List[Dict[str, str]]:
        """Build a compact skill index, similar to OpenClaw's lightweight skill list."""
        if tool_names:
            metadata_entries = []
            seen = set()
            for tool_name in tool_names:
                item = self.get_skill_metadata_for_tool(tool_name)
                if not item:
                    continue
                skill_name = item.get("name") or tool_name
                if skill_name in seen:
                    continue
                seen.add(skill_name)
                metadata_entries.append(item)
            return metadata_entries

        entries = []
        for skill_name, metadata in self.list_skill_metadata().items():
            definition = self.skill_loader.skills.get(skill_name)
            entries.append({
                **metadata,
                "location": str(getattr(definition, "skill_file", definition.skill_dir / "SKILL.md")) if definition else "",
                "tool_name": skill_name,
            })
        return entries

    @staticmethod
    def _read_skill_meta(skill_dir: Optional[Path]) -> dict:
        """Read _meta.json if present; return {} otherwise."""
        if skill_dir is None:
            return {}
        meta_file = skill_dir / "_meta.json"
        if meta_file.exists():
            try:
                return json.loads(meta_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    @staticmethod
    def _skill_installed_at(skill_dir: Optional[Path], meta: Optional[dict] = None) -> str:
        """Return ISO timestamp for when a skill was installed."""
        if meta and meta.get("installed_at"):
            return meta["installed_at"]
        if skill_dir is None:
            return "1970-01-01T00:00:00+00:00"
        skill_md = skill_dir / "SKILL.md"
        target = skill_md if skill_md.exists() else skill_dir
        try:
            mtime = target.stat().st_mtime
            return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
        except Exception:
            return "1970-01-01T00:00:00+00:00"

    @staticmethod
    def _is_protected(skill_dir: Optional[Path], meta: Optional[dict] = None) -> bool:
        """A skill is protected if _meta.json has protected=true OR SKILL.md frontmatter has protected: true."""
        if meta and meta.get("protected"):
            return True
        if skill_dir is None:
            return False
        skill_md_file = skill_dir / "SKILL.md"
        if skill_md_file.exists():
            try:
                text = skill_md_file.read_text(encoding="utf-8")
                # Quick frontmatter check
                import re as _re
                m = _re.search(r"^protected:\s*true", text, _re.MULTILINE | _re.IGNORECASE)
                if m:
                    return True
            except Exception:
                pass
        return False

    def get_skill_catalog(self) -> List[Dict[str, Any]]:
        """Return available skills sorted by install time (oldest first)."""
        catalog = []
        metadata_map = self.list_skill_metadata()
        tool_map: Dict[str, List[str]] = {}

        for skill_name, skill in self.get_enabled_skills().items():
            tool_name = getattr(skill, "name", skill_name)
            tool_map.setdefault(skill_name, []).append(tool_name)

        for skill_name, metadata in metadata_map.items():
            definition = self.skill_loader.skills.get(skill_name)
            skill_dir = definition.skill_dir if definition else None
            meta = self._read_skill_meta(skill_dir)
            tool_names = sorted(tool_map.get(skill_name, []))
            installed_at = self._skill_installed_at(skill_dir, meta)
            protected = self._is_protected(skill_dir, meta)
            catalog.append({
                "name": skill_name,
                "description": metadata.get("description", ""),
                "location": str(getattr(definition, "skill_file", skill_dir / "SKILL.md")) if definition and skill_dir else "",
                "tool_names": tool_names,
                "installed_at": installed_at,
                "protected": protected,
            })

        # Default: built-ins (by mtime = old) first, newly installed last
        return sorted(catalog, key=lambda item: item["installed_at"])

    # ------------------------------------------------------------------ #
    #  Hot-reload & install                                                #
    # ------------------------------------------------------------------ #

    def reload_skills(self) -> Dict[str, Any]:
        """Hot-reload all skills from disk without restarting the server."""
        before = set(self.skills.keys())
        self.skills = {}
        self.skill_loader = SkillLoader(skills_root=self.config.get("skills_dir"))
        self._initialize_skills()
        after = set(self.skills.keys())
        added = sorted(after - before)
        removed = sorted(before - after)
        logger.info(f"Skills reloaded: +{added} -{removed}")
        return {"added": added, "removed": removed, "total": len(self.skills)}

    def install_skill(self, name: str, skill_md: str, python_code: str = "") -> Dict[str, Any]:
        """
        Install a new skill from SKILL.md content (and optional Python implementation).
        Creates the skill directory under the active skills root then hot-reloads.
        Returns the updated catalog entry or raises on error.
        """
        if name not in self.HARNESS_SPEC_SKILLS:
            raise ValueError(f"Skill '{name}' is outside the Harness spec allowlist")
        skills_root = self.skill_loader.skills_root if hasattr(self.skill_loader, "skills_root") else None
        if skills_root is None:
            # Fall back: derive from existing skill locations
            for defn in self.skill_loader.skills.values():
                skills_root = defn.skill_dir.parent
                break
        if skills_root is None:
            raise RuntimeError("Cannot determine skills root directory")

        skill_dir = Path(skills_root) / name
        skill_dir.mkdir(parents=True, exist_ok=True)

        skill_md_path = skill_dir / "SKILL.md"
        skill_md_path.write_text(skill_md, encoding="utf-8")

        if python_code.strip():
            py_path = skill_dir / f"{name.replace('-', '_')}.py"
            py_path.write_text(python_code, encoding="utf-8")

        # Record install timestamp (preserved across reloads)
        meta_file = skill_dir / "_meta.json"
        if not meta_file.exists():
            meta_file.write_text(
                json.dumps({"installed_at": datetime.now(tz=timezone.utc).isoformat()}, ensure_ascii=False),
                encoding="utf-8",
            )

        logger.info(f"Installed skill '{name}' to {skill_dir}")
        reload_info = self.reload_skills()
        catalog = self.get_skill_catalog()
        installed = next((s for s in catalog if s["name"] == name), None)
        return {
            "skill_dir": str(skill_dir),
            "reload": reload_info,
            "catalog_entry": installed,
        }

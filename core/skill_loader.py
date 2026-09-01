"""
AgentCore Skill Loader.

Skill  is a hot-loadable business capability description. is used to supplement the Agent's system prompt.
 It is suitable for placing corporate speech,Processing flow, Compliance boundary, Troubleshooting SOPs and other rules that require rapid adjustment on the operation side.
"""
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Skill:
    """ Standardized representation of a single Skill, Shield differences between different file formats such as Markdown/JSON."""
    name: str
    description: str
    content: str
    path: str
    keywords: List[str] = field(default_factory=list)
    agents: List[str] = field(default_factory=list)
    enabled: bool = True

    def matches(self, message: str, agent_type: Optional[str] = None) -> bool:
        """
         Determine whether the current request should be injected into this Skill.

        - agents  is empty: Applies to all Agents; Otherwise only the specified Agent will be matched.
        - keywords  is empty: Injected as a global Skill; Otherwise, only the hit keyword will be injected.
        """
        if not self.enabled:
            return False

        if self.agents and agent_type and agent_type.lower() not in self.agents:
            return False

        if not self.keywords:
            return True

        lowered = (message or "").lower()
        return any(keyword.lower() in lowered for keyword in self.keywords)

    def to_prompt_block(self, max_chars: int = 3200) -> str:
        """ Formatted into a block of text that can be typed directly into the system prompt, and limit the length of a single Skill."""
        body = self.content.strip()
        if len(body) > max_chars:
            body = body[:max_chars].rstrip() + "\n..."
        description = f"\n Description: {self.description}" if self.description else ""
        return f"### {self.name}{description}\n{body}"

    def to_summary(self) -> Dict[str, Any]:
        """ Return API serializable summary, Avoid exposing full long text to health checks by default."""
        return {
            "name": self.name,
            "description": self.description,
            "path": self.path,
            "keywords": self.keywords,
            "agents": self.agents,
            "enabled": self.enabled,
            "content_chars": len(self.content),
        }


class SkillManager:
    """
     Found from the directory, Parse and manage Skills.

     Supports two common structures:
      1. skills/refund/SKILL.md
      2. skills/refund.json / skills/refund.md / skills/refund.txt
    """

    SUPPORTED_SUFFIXES = {".md", ".txt", ".json"}

    def __init__(self, root_dir: str, max_prompt_chars: int = 5000):
        self.root_dir = Path(root_dir).expanduser().resolve()
        self.max_prompt_chars = max_prompt_chars
        self._skills: List[Skill] = []
        self._errors: List[str] = []

    @property
    def skills(self) -> List[Skill]:
        return list(self._skills)

    @property
    def errors(self) -> List[str]:
        return list(self._errors)

    def load(self) -> List[Skill]:
        """ Rescan the directory and load Skills; Failure of a single file will not affect other Skills."""
        loaded: List[Skill] = []
        errors: List[str] = []

        if not self.root_dir.exists():
            logger.info(f"Skill  Directory does not exist, Skip loading: {self.root_dir}")
            self._skills = []
            self._errors = []
            return []

        for path in self._discover_files(self.root_dir):
            try:
                skill = self._load_file(path)
                if skill is not None:
                    loaded.append(skill)
            except Exception as ex:
                msg = f"{path}: {ex}"
                errors.append(msg)
                logger.warning(f"Skill  Loading failed: {msg}")

        self._skills = loaded
        self._errors = errors
        self._log_loaded_skills()
        return self.skills

    def reload(self) -> List[Skill]:
        """ Hot loading entry during runtime, For API calls."""
        return self.load()

    def prompt_for(self, message: str, agent_type: Optional[str] = None) -> str:
        """
         Build Skill prompt for current user request.

         Only inject matching Skills, and truncated by total length, Avoid crowding out the main conversation context.
        """
        blocks: List[str] = []
        matched: List[tuple[Skill, List[str]]] = []
        remaining = self.max_prompt_chars
        lowered_message = (message or "").lower()

        for skill in self._skills:
            if not skill.matches(message, agent_type):
                continue
            matched_keywords = [
                keyword for keyword in skill.keywords
                if keyword.lower() in lowered_message
            ]
            block = skill.to_prompt_block()
            if len(block) > remaining:
                block = block[:remaining].rstrip() + "\n..."
            blocks.append(block)
            matched.append((skill, matched_keywords))
            remaining -= len(block)
            if remaining <= 0:
                break

        if not blocks:
            logger.debug(
                "Skills Missed: agent=%s message=%r",
                agent_type or "all",
                (message or "")[:80],
            )
            return ""

        detail = "; ".join(
            f"{skill.name}(keywords={', '.join(keywords) if keywords else 'all'})"
            for skill, keywords in matched
        )
        logger.info(
            "Skills Injected: agent=%s matched=%s message=%r",
            agent_type or "all",
            detail,
            (message or "")[:80],
        )

        return (
            " The following are the AgentCore Skills available for the current request."
            " Please follow these business rules first; If conflicting with system roles, Subject to system roles and security boundaries.\n\n"
            + "\n\n".join(blocks)
        )

    def summary(self) -> Dict[str, Any]:
        """ Return to Skill Manager status, For /skills interface and troubleshooting."""
        return {
            "root_dir": str(self.root_dir),
            "count": len(self._skills),
            "skills": [skill.to_summary() for skill in self._skills],
            "errors": self.errors,
        }

    def _log_loaded_skills(self) -> None:
        """ Output the eye-catching Skill loading result on the console, Conveniently confirm the effective status during startup and hot reloading."""
        lines = [
            "",
            "================ AgentCore Skills Loaded ================",
            f" Table of Contents: {self.root_dir}",
            f"Quantity: {len(self._skills)}",
        ]

        if self._skills:
            for index, skill in enumerate(self._skills, start=1):
                agents = ", ".join(skill.agents) if skill.agents else "all"
                keywords = ", ".join(skill.keywords[:8]) if skill.keywords else "all"
                if len(skill.keywords) > 8:
                    keywords += ", ..."
                lines.extend([
                    f"{index}. {skill.name}",
                    f"   agents: {agents}",
                    f"   keywords: {keywords}",
                    f"   path: {skill.path}",
                ])
        else:
            lines.append(" No Skill loaded.")

        if self._errors:
            lines.append(" Parse error:")
            lines.extend(f"  - {error}" for error in self._errors)

        lines.append("========================================================")
        logger.info("\n".join(lines))

    def _discover_files(self, root_dir: Path) -> Iterable[Path]:
        """Loadable file found, Prioritize reading the directory specification file SKILL.md."""
        skill_md_files = sorted(root_dir.rglob("SKILL.md"))
        yielded = {path.resolve() for path in skill_md_files}
        for path in skill_md_files:
            yield path

        for path in sorted(root_dir.rglob("*")):
            resolved = path.resolve()
            if resolved in yielded or not path.is_file():
                continue
            if path.name.startswith(".") or path.name.upper() == "README.MD":
                continue
            if path.suffix.lower() in self.SUPPORTED_SUFFIXES:
                yield path

    def _load_file(self, path: Path) -> Optional[Skill]:
        if path.suffix.lower() == ".json":
            return self._load_json(path)
        return self._load_text(path)

    def _load_json(self, path: Path) -> Optional[Skill]:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("JSON Skill  Must be in object format")

        content = str(raw.get("content") or raw.get("instructions") or "").strip()
        if not content:
            raise ValueError(" Missing content or instructions")

        return Skill(
            name=str(raw.get("name") or path.stem),
            description=str(raw.get("description") or ""),
            content=content,
            path=str(path),
            keywords=self._as_list(raw.get("keywords")),
            agents=[item.lower() for item in self._as_list(raw.get("agents"))],
            enabled=self._as_bool(raw.get("enabled"), default=True),
        )

    def _load_text(self, path: Path) -> Optional[Skill]:
        raw = path.read_text(encoding="utf-8")
        meta, body = self._split_front_matter(raw)
        body = body.strip()
        if not body:
            return None

        default_name = path.parent.name if path.name == "SKILL.md" else path.stem
        name = str(meta.get("name") or self._first_heading(body) or default_name)

        #  If the first line title is just the Skill name, Remove prompt when injecting it, Reduce repetitive noise.
        body = self._strip_first_heading(body, name)

        return Skill(
            name=name,
            description=str(meta.get("description") or ""),
            content=body,
            path=str(path),
            keywords=self._as_list(meta.get("keywords")),
            agents=[item.lower() for item in self._as_list(meta.get("agents"))],
            enabled=self._as_bool(meta.get("enabled"), default=True),
        )

    def _split_front_matter(self, raw: str) -> tuple[Dict[str, Any], str]:
        """
         Parse simple front matter at the top of Markdown.

         PyYAML is intentionally not used here. Avoid adding runtime dependencies for a lightweight configuration format.
        """
        text = raw.lstrip()
        if not text.startswith("---"):
            return {}, raw

        lines = text.splitlines()
        if not lines or lines[0].strip() != "---":
            return {}, raw

        meta: Dict[str, Any] = {}
        end_idx: Optional[int] = None
        for idx, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                end_idx = idx
                break
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip().strip("\"'")

        if end_idx is None:
            return {}, raw
        return meta, "\n".join(lines[end_idx + 1:])

    @staticmethod
    def _first_heading(body: str) -> Optional[str]:
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                return stripped.lstrip("#").strip() or None
        return None

    @staticmethod
    def _strip_first_heading(body: str, name: str) -> str:
        lines = body.splitlines()
        if not lines:
            return body
        first = lines[0].strip()
        if first.startswith("#") and first.lstrip("#").strip() == name:
            return "\n".join(lines[1:]).strip()
        return body

    @staticmethod
    def _as_list(value: Any) -> List[str]:
        if value is None or value == "":
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [item.strip() for item in str(value).split(",") if item.strip()]

    @staticmethod
    def _as_bool(value: Any, default: bool = False) -> bool:
        if value is None or value == "":
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() not in {"0", "false", "no", "off", "disabled"}

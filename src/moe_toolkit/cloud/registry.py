"""Static curated registry and rule-based router for MOE Toolkit."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path

from moe_toolkit.schemas.common import RoutePlan, ToolManifest, ToolMatch, ToolSummary, UploadRef


def default_registry_root() -> Path:
    """Returns the curated tools directory bundled with the repo."""

    candidates = [
        Path.cwd() / "tools" / "curated",
        Path("/app/tools/curated"),
        Path(__file__).resolve().parents[3] / "tools" / "curated",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def detect_input_type(filename: str) -> str:
    """Maps a filename to a registry input type label."""

    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        return "csv"
    if suffix == ".tsv":
        return "tsv"
    if suffix == ".xlsx":
        return "xlsx"
    if suffix == ".zip":
        return "zip"
    return suffix.lstrip(".") or "unknown"


@dataclass(slots=True)
class RouteDecision:
    """Internal route decision with logs and selected manifests."""

    route_plan: RoutePlan
    matches: list[ToolMatch]
    required_capabilities: list[str]
    input_types: list[str]


class CuratedRegistry:
    """Loads static tool manifests from the repo."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or default_registry_root()
        self._manifests = self._load_manifests()

    def _load_manifests(self) -> dict[str, ToolManifest]:
        manifests: dict[str, ToolManifest] = {}
        for manifest_path in sorted(self.root.glob("*/manifest.json")):
            manifest = ToolManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
            manifests[manifest.tool_id] = manifest
        return manifests

    def summaries(self) -> list[ToolSummary]:
        """Returns summarized tools for API responses."""

        return [
            ToolSummary.model_validate(manifest.model_dump(mode="json"))
            for manifest in sorted(self._manifests.values(), key=lambda item: (item.priority, item.tool_id))
        ]

    def search(
        self,
        *,
        capability: str | None = None,
        input_type: str | None = None,
        enabled: bool | None = None,
    ) -> list[ToolSummary]:
        """Searches curated tools with simple filters."""

        results: list[ToolSummary] = []
        for manifest in sorted(self._manifests.values(), key=lambda item: (item.priority, item.tool_id)):
            if capability and capability not in manifest.capabilities:
                continue
            if input_type and input_type not in manifest.input_types:
                continue
            if enabled is not None and manifest.enabled is not enabled:
                continue
            results.append(ToolSummary.model_validate(manifest.model_dump(mode="json")))
        return results

    def get_summary(self, tool_id: str) -> ToolSummary:
        """Returns a tool summary by ID."""

        manifest = self.get_manifest(tool_id)
        return ToolSummary.model_validate(manifest.model_dump(mode="json"))

    def get_manifest(self, tool_id: str, version: str | None = None) -> ToolManifest:
        """Returns a full manifest by tool ID and optional version."""

        try:
            manifest = self._manifests[tool_id]
        except KeyError as exc:
            raise KeyError(f"Unknown tool_id: {tool_id}") from exc
        if version and manifest.version != version:
            raise KeyError(f"Unknown manifest version for {tool_id}: {version}")
        return manifest


class RuleBasedCuratedRouter:
    """Routes tasks against the static curated registry."""

    def __init__(self, registry: CuratedRegistry) -> None:
        self.registry = registry

    def build_route(
        self,
        *,
        task: str,
        uploads: list[UploadRef],
    ) -> RouteDecision:
        """Builds a route plan and captures why tools were selected."""

        input_types = sorted({detect_input_type(upload.filename) for upload in uploads})
        required_capabilities = self._infer_capabilities(task=task, input_types=input_types)
        matches = self._match_tools(required_capabilities=required_capabilities, input_types=input_types)
        covered_capabilities = sorted(
            {
                capability
                for match in matches
                for capability in match.matched_capabilities
            }
        )
        missing_capabilities = [
            capability
            for capability in required_capabilities
            if capability not in covered_capabilities
        ]
        if not matches or missing_capabilities:
            explanation = self._explain_no_match(
                task=task,
                required_capabilities=required_capabilities,
                missing_capabilities=missing_capabilities,
            )
            return RouteDecision(
                route_plan=RoutePlan(
                    plan_id=uuid.uuid4().hex,
                    capabilities=required_capabilities,
                    selected_images=[],
                    selected_tools=[],
                    execution_steps=[],
                    selection_reason="no_match",
                    explanation=explanation,
                ),
                matches=[],
                required_capabilities=required_capabilities,
                input_types=input_types,
            )

        selected_images = [match.image for match in matches]
        selected_tools = [match.tool_id for match in matches]
        explanation = self._build_explanation(required_capabilities, matches)
        return RouteDecision(
            route_plan=RoutePlan(
                plan_id=uuid.uuid4().hex,
                capabilities=required_capabilities,
                selected_images=selected_images,
                selected_tools=selected_tools,
                execution_steps=selected_tools.copy(),
                selection_reason="matched_curated_registry",
                explanation=explanation,
            ),
            matches=matches,
            required_capabilities=required_capabilities,
            input_types=input_types,
        )

    def _infer_capabilities(self, *, task: str, input_types: list[str]) -> list[str]:
        task_text = task.lower()
        capabilities: list[str] = []

        if {"csv", "tsv"} & set(input_types):
            capabilities.extend(["csv_parse", "table_read", "data_analysis"])
        if "xlsx" in input_types:
            capabilities.extend(["table_read", "data_analysis"])
        if any(token in task_text for token in ["图", "chart", "plot", "trend", "趋势"]):
            capabilities.extend(["chart_generate", "visualization"])
        if any(token in task_text for token in ["excel", "xlsx", "表格", "报表", "spreadsheet"]):
            capabilities.append("spreadsheet_generate")
        if any(token in task_text for token in ["markdown", "report", "报告", "总结", "summary"]):
            capabilities.append("report_export")
        if any(token in task_text for token in ["search", "web", "http", "网页", "联网", "检索"]):
            capabilities.append("web_research")

        deduped: list[str] = []
        for capability in capabilities:
            if capability not in deduped:
                deduped.append(capability)
        return deduped

    def _match_tools(
        self,
        *,
        required_capabilities: list[str],
        input_types: list[str],
    ) -> list[ToolMatch]:
        chosen: dict[str, ToolMatch] = {}
        if not required_capabilities or not input_types:
            return []

        for capability in required_capabilities:
            candidates = self.registry.search(capability=capability, enabled=True)
            compatible = [
                self.registry.get_manifest(candidate.tool_id)
                for candidate in candidates
                if not input_types or set(candidate.input_types) & set(input_types)
            ]
            compatible.sort(key=lambda manifest: (manifest.priority, manifest.tool_id))
            if not compatible:
                continue
            manifest = compatible[0]
            existing = chosen.get(manifest.tool_id)
            if existing is None:
                chosen[manifest.tool_id] = ToolMatch(
                    tool_id=manifest.tool_id,
                    image=manifest.image,
                    matched_capabilities=[capability],
                    score=100 - manifest.priority,
                    reason=f"Matched capability '{capability}'",
                )
            else:
                if capability not in existing.matched_capabilities:
                    existing.matched_capabilities.append(capability)
                    existing.score += 5
        return sorted(chosen.values(), key=lambda item: (-item.score, item.tool_id))

    @staticmethod
    def _build_explanation(required_capabilities: list[str], matches: list[ToolMatch]) -> str:
        tool_names = ", ".join(match.tool_id for match in matches)
        capability_text = ", ".join(required_capabilities) or "no capabilities"
        return f"Selected curated tools [{tool_names}] for capabilities [{capability_text}]."

    @staticmethod
    def _explain_no_match(
        *,
        task: str,
        required_capabilities: list[str],
        missing_capabilities: list[str] | None = None,
    ) -> str:
        if missing_capabilities:
            missing_text = ", ".join(missing_capabilities)
            return (
                f"No curated tool covered missing capabilities [{missing_text}] "
                f"for task: {task}"
            )
        if required_capabilities:
            capability_text = ", ".join(required_capabilities)
            return f"No curated tool matched required capabilities [{capability_text}] for task: {task}"
        return f"No curated tool matched the task: {task}"

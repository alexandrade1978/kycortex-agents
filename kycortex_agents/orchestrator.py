import ast
import logging
import re
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Any, Optional, cast

from kycortex_agents.agents.registry import AgentRegistry, build_default_registry
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError, WorkflowDefinitionError
from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.types import AgentInput, AgentOutput, ArtifactRecord, ArtifactType, TaskStatus

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")


_THIRD_PARTY_PACKAGE_ALIASES = {
    "bs4": "beautifulsoup4",
    "cv2": "opencv-python",
    "crypto": "pycryptodome",
    "pil": "pillow",
    "sklearn": "scikit-learn",
    "yaml": "pyyaml",
}

_STDLIB_MODULES = set(getattr(sys, "stdlib_module_names", set()))


class Orchestrator:
    """Public workflow runtime for executing tasks with a configured or custom registry.

    Pass a custom AgentRegistry when consumers need to register their own agent
    implementations while keeping `execute_workflow()` and `run_task()` as the
    supported execution entry points.
    """

    def __init__(self, config: Optional[KYCortexConfig] = None, registry: Optional[AgentRegistry] = None):
        self.config = config or KYCortexConfig()
        self.registry = registry or build_default_registry(self.config)
        self.logger = logging.getLogger("Orchestrator")

    def _log_event(self, level: str, event: str, **fields: Any) -> None:
        log_method = getattr(self.logger, level)
        log_method(event, extra={"event": event, **fields})

    def run_task(self, task: Task, project: ProjectState) -> str:
        """Execute one task through the public orchestrator runtime contract."""
        self._log_event(
            "info",
            "task_started",
            project_name=project.project_name,
            task_id=task.id,
            task_title=task.title,
            assigned_to=task.assigned_to,
            attempt=task.attempts + 1,
        )
        agent = self.registry.get(task.assigned_to)
        agent_input = self._build_agent_input(task, project)
        project.start_task(task.id)
        normalized_output: Optional[AgentOutput] = None
        try:
            output = self._execute_agent(agent, agent_input)
            normalized_output = self._normalize_agent_result(output)
            self._validate_task_output(task, agent_input.context, normalized_output)
        except Exception as exc:
            project.fail_task(task.id, exc, provider_call=self._provider_call_metadata(agent, normalized_output))
            if project.should_retry_task(task.id):
                self._log_event(
                    "warning",
                    "task_retry_scheduled",
                    project_name=project.project_name,
                    task_id=task.id,
                    task_title=task.title,
                    assigned_to=task.assigned_to,
                    attempt=task.attempts,
                    error_type=type(exc).__name__,
                )
            else:
                provider_call = self._provider_call_metadata(agent, normalized_output)
                self._log_event(
                    "error",
                    "task_failed",
                    project_name=project.project_name,
                    task_id=task.id,
                    task_title=task.title,
                    assigned_to=task.assigned_to,
                    attempt=task.attempts,
                    error_type=type(exc).__name__,
                    provider=provider_call.get("provider") if provider_call else None,
                    model=provider_call.get("model") if provider_call else None,
                )
            raise
        self._persist_artifacts(normalized_output.artifacts)
        for decision in normalized_output.decisions:
            project.add_decision_record(decision)
        for artifact in normalized_output.artifacts:
            project.add_artifact_record(artifact)
        provider_call = self._provider_call_metadata(agent, normalized_output)
        project.complete_task(task.id, normalized_output, provider_call=provider_call)
        self._log_event(
            "info",
            "task_completed",
            project_name=project.project_name,
            task_id=task.id,
            task_title=task.title,
            assigned_to=task.assigned_to,
            attempt=task.attempts,
            provider=provider_call.get("provider") if provider_call else None,
            model=provider_call.get("model") if provider_call else None,
            total_tokens=(provider_call.get("usage") or {}).get("total_tokens") if provider_call else None,
        )
        return normalized_output.raw_content

    def _validate_task_output(self, task: Task, context: Dict[str, Any], output: AgentOutput) -> None:
        if AgentRegistry.normalize_key(task.assigned_to) != "dependency_manager":
            return
        raw_code_analysis = context.get("code_analysis")
        code_analysis = cast(Dict[str, Any], raw_code_analysis) if isinstance(raw_code_analysis, dict) else {}
        dependency_analysis = self._analyze_dependency_manifest(output.raw_content, code_analysis)
        if dependency_analysis.get("is_valid"):
            return
        missing_entries = ", ".join(dependency_analysis.get("missing_manifest_entries") or []) or "unknown"
        raise AgentExecutionError(
            f"Dependency manifest validation failed: missing manifest entries for {missing_entries}"
        )

    def _provider_call_metadata(self, agent: Any, output: Optional[AgentOutput] = None) -> Optional[Dict[str, Any]]:
        if output is not None:
            provider_call = output.metadata.get("provider_call")
            if isinstance(provider_call, dict):
                return dict(provider_call)
        getter = getattr(agent, "get_last_provider_call_metadata", None)
        if callable(getter):
            metadata = getter()
            if isinstance(metadata, dict):
                return metadata
        return None

    def _persist_artifacts(self, artifacts: list[ArtifactRecord]) -> None:
        for artifact in artifacts:
            content = artifact.content
            if not isinstance(content, str) or not content.strip():
                continue
            target_path = self._resolve_artifact_output_path(artifact)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(content, encoding="utf-8")
            artifact.path = self._artifact_record_path(target_path)

    def _resolve_artifact_output_path(self, artifact: ArtifactRecord) -> Path:
        configured_path = Path(artifact.path) if artifact.path else None
        if configured_path is not None and configured_path.is_absolute():
            return configured_path
        output_root = Path(self.config.output_dir).resolve()
        relative_path = configured_path if configured_path is not None else Path(self._default_artifact_path(artifact))
        return output_root / relative_path

    def _artifact_record_path(self, target_path: Path) -> str:
        output_root = Path(self.config.output_dir).resolve()
        resolved_target = target_path.resolve()
        try:
            return str(resolved_target.relative_to(output_root))
        except ValueError:
            return str(resolved_target)

    def _default_artifact_path(self, artifact: ArtifactRecord) -> str:
        suffix_map = {
            ArtifactType.DOCUMENT: ".md",
            ArtifactType.CODE: ".py",
            ArtifactType.TEST: ".py",
            ArtifactType.CONFIG: ".json",
            ArtifactType.TEXT: ".txt",
            ArtifactType.OTHER: ".artifact",
        }
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", artifact.name).strip("._") or "artifact"
        return f"artifacts/{safe_name}{suffix_map.get(artifact.artifact_type, '.artifact')}"

    def _build_context(self, task: Task, project: ProjectState) -> Dict[str, Any]:
        snapshot = project.snapshot()
        ctx: Dict[str, Any] = {
            "goal": project.goal,
            "project_name": project.project_name,
            "phase": project.phase,
            "task": {
                "id": task.id,
                "title": task.title,
                "description": task.description,
                "assigned_to": task.assigned_to,
            },
            "snapshot": asdict(snapshot),
            "completed_tasks": {},
            "decisions": snapshot.decisions,
            "artifacts": snapshot.artifacts,
        }
        ctx.update(self._planned_module_context(project))
        default_module_name = self._default_module_name_for_task(task)
        if default_module_name:
            ctx["module_name"] = default_module_name
            ctx["module_filename"] = f"{default_module_name}.py"
        for prev_task in project.tasks:
            if prev_task.status == TaskStatus.DONE.value and prev_task.output:
                ctx[prev_task.id] = prev_task.output
                ctx["completed_tasks"][prev_task.id] = prev_task.output
                semantic_key = self._semantic_output_key(prev_task)
                if semantic_key:
                    ctx[semantic_key] = prev_task.output
                if AgentRegistry.normalize_key(prev_task.assigned_to) == "code_engineer":
                    ctx.update(self._code_artifact_context(prev_task))
                if AgentRegistry.normalize_key(prev_task.assigned_to) == "dependency_manager":
                    ctx.update(self._dependency_artifact_context(prev_task, ctx))
                if AgentRegistry.normalize_key(prev_task.assigned_to) == "qa_tester":
                    ctx.update(self._test_artifact_context(prev_task, ctx))
        return ctx

    def _planned_module_context(self, project: ProjectState) -> Dict[str, Any]:
        for existing_task in project.tasks:
            if AgentRegistry.normalize_key(existing_task.assigned_to) != "code_engineer":
                continue
            module_name = self._default_module_name_for_task(existing_task)
            if not module_name:
                continue
            return {
                "planned_module_name": module_name,
                "planned_module_filename": f"{module_name}.py",
            }
        return {}

    def _default_module_name_for_task(self, task: Task) -> Optional[str]:
        if AgentRegistry.normalize_key(task.assigned_to) != "code_engineer":
            return None
        return f"{task.id}_implementation"

    def _code_artifact_context(self, task: Task) -> Dict[str, Any]:
        if not isinstance(task.output_payload, dict):
            return {}
        artifacts = task.output_payload.get("artifacts")
        if not isinstance(artifacts, list):
            return {}
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            if artifact.get("artifact_type") != ArtifactType.CODE.value:
                continue
            artifact_path = artifact.get("path")
            if not isinstance(artifact_path, str) or not artifact_path.strip():
                continue
            path_obj = Path(artifact_path)
            module_name = path_obj.stem
            code_analysis = self._analyze_python_module(task.output or "")
            return {
                "code_artifact_path": artifact_path,
                "module_name": module_name,
                "module_filename": path_obj.name,
                "code_summary": self._summarize_output(task.output or ""),
                "code_outline": self._build_code_outline(task.output or ""),
                "code_analysis": code_analysis,
                "code_public_api": self._build_code_public_api(code_analysis),
                "module_run_command": self._build_module_run_command(path_obj.name, code_analysis),
            }
        return {}

    def _test_artifact_context(self, task: Task, context: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(task.output_payload, dict):
            return {}
        artifacts = task.output_payload.get("artifacts")
        if not isinstance(artifacts, list):
            return {}
        module_name = context.get("module_name")
        code_analysis = context.get("code_analysis")
        if not isinstance(module_name, str) or not module_name or not isinstance(code_analysis, dict):
            return {}
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            if artifact.get("artifact_type") != ArtifactType.TEST.value:
                continue
            artifact_path = artifact.get("path")
            if not isinstance(artifact_path, str) or not artifact_path.strip():
                continue
            test_analysis = self._analyze_test_module(task.output or "", module_name, code_analysis)
            return {
                "tests_artifact_path": artifact_path,
                "test_analysis": test_analysis,
                "test_validation_summary": self._build_test_validation_summary(test_analysis),
            }
        return {}

    def _dependency_artifact_context(self, task: Task, context: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(task.output_payload, dict):
            return {}
        artifacts = task.output_payload.get("artifacts")
        if not isinstance(artifacts, list):
            return {}
        raw_code_analysis = context.get("code_analysis")
        code_analysis = cast(Dict[str, Any], raw_code_analysis) if isinstance(raw_code_analysis, dict) else {}
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            artifact_path = artifact.get("path")
            if not isinstance(artifact_path, str) or not artifact_path.strip():
                continue
            path_obj = Path(artifact_path)
            if path_obj.name != "requirements.txt":
                continue
            dependency_analysis = self._analyze_dependency_manifest(task.output or "", code_analysis)
            return {
                "dependency_manifest": task.output or "",
                "dependency_manifest_path": artifact_path,
                "dependency_analysis": dependency_analysis,
                "dependency_validation_summary": self._build_dependency_validation_summary(dependency_analysis),
            }
        return {}

    def _analyze_dependency_manifest(self, manifest_content: str, code_analysis: Dict[str, Any]) -> Dict[str, Any]:
        declared_packages: list[str] = []
        normalized_declared_packages: set[str] = set()
        for raw_line in manifest_content.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            package_name = re.split(r"\s*(?:==|>=|<=|~=|!=|>|<)", line, maxsplit=1)[0].strip()
            if not package_name:
                continue
            declared_packages.append(package_name)
            normalized_declared_packages.add(self._normalize_package_name(package_name))

        required_imports = sorted(code_analysis.get("third_party_imports") or []) if isinstance(code_analysis, dict) else []
        normalized_required_imports = {self._normalize_import_name(module_name) for module_name in required_imports}
        missing_manifest_entries = [
            module_name
            for module_name in required_imports
            if self._normalize_import_name(module_name) not in normalized_declared_packages
        ]
        unused_manifest_entries = [
            package_name
            for package_name in declared_packages
            if self._normalize_package_name(package_name) not in normalized_required_imports
        ]
        return {
            "required_imports": required_imports,
            "declared_packages": declared_packages,
            "missing_manifest_entries": missing_manifest_entries,
            "unused_manifest_entries": unused_manifest_entries,
            "is_valid": not missing_manifest_entries,
        }

    def _build_dependency_validation_summary(self, dependency_analysis: Dict[str, Any]) -> str:
        lines = ["Dependency manifest validation:"]
        lines.append(
            f"- Required third-party imports: {', '.join(dependency_analysis.get('required_imports') or ['none'])}"
        )
        lines.append(
            f"- Declared packages: {', '.join(dependency_analysis.get('declared_packages') or ['none'])}"
        )
        lines.append(
            f"- Missing manifest entries: {', '.join(dependency_analysis.get('missing_manifest_entries') or ['none'])}"
        )
        lines.append(
            f"- Unused manifest entries: {', '.join(dependency_analysis.get('unused_manifest_entries') or ['none'])}"
        )
        lines.append(f"- Verdict: {'PASS' if dependency_analysis.get('is_valid') else 'FAIL'}")
        return "\n".join(lines)

    def _normalize_package_name(self, package_name: str) -> str:
        return package_name.strip().lower().replace("-", "_")

    def _normalize_import_name(self, module_name: str) -> str:
        normalized_name = module_name.strip().lower().replace("-", "_")
        package_name = _THIRD_PARTY_PACKAGE_ALIASES.get(normalized_name, normalized_name)
        return self._normalize_package_name(package_name)

    def _build_code_outline(self, raw_content: str) -> str:
        if not raw_content.strip():
            return ""
        pattern = re.compile(r"^(class\s+\w+.*|def\s+\w+.*|async\s+def\s+\w+.*)$")
        outline_lines = [line.strip() for line in raw_content.splitlines() if pattern.match(line.strip())]
        return "\n".join(outline_lines[:40])

    def _analyze_python_module(self, raw_content: str) -> Dict[str, Any]:
        analysis: Dict[str, Any] = {
            "syntax_ok": True,
            "syntax_error": None,
            "functions": [],
            "classes": {},
            "imports": [],
            "third_party_imports": [],
            "symbols": [],
            "has_main_guard": '__name__ == "__main__"' in raw_content or "__name__ == '__main__'" in raw_content,
        }
        if not raw_content.strip():
            return analysis
        try:
            tree = ast.parse(raw_content)
        except SyntaxError as exc:
            analysis["syntax_ok"] = False
            analysis["syntax_error"] = f"{exc.msg} at line {exc.lineno}"
            return analysis

        functions: list[Dict[str, Any]] = []
        classes: Dict[str, Dict[str, Any]] = {}
        import_roots: set[str] = set()

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("_"):
                    continue
                params = [arg.arg for arg in node.args.args]
                functions.append({
                    "name": node.name,
                    "params": params,
                    "signature": f"{node.name}({', '.join(params)})",
                    "async": isinstance(node, ast.AsyncFunctionDef),
                })
                continue
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_name = alias.name.split(".", 1)[0]
                    if root_name:
                        import_roots.add(root_name)
                continue
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    continue
                module_name = (node.module or "").split(".", 1)[0]
                if module_name:
                    import_roots.add(module_name)
                continue
            if not isinstance(node, ast.ClassDef):
                continue

            field_names: list[str] = []
            class_attributes: list[str] = []
            init_params: list[str] = []
            methods: list[str] = []
            bases = [self._ast_name(base) for base in node.bases]
            is_enum = any(base.endswith("Enum") for base in bases)

            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    field_names.append(stmt.target.id)
                elif isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name):
                            class_attributes.append(target.id)
                elif isinstance(stmt, ast.FunctionDef) and stmt.name == "__init__":
                    init_params = [arg.arg for arg in stmt.args.args if arg.arg != "self"]
                elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and not stmt.name.startswith("_"):
                    params = [arg.arg for arg in stmt.args.args]
                    methods.append(f"{stmt.name}({', '.join(params)})")

            constructor_params = init_params or field_names
            classes[node.name] = {
                "name": node.name,
                "bases": bases,
                "is_enum": is_enum,
                "fields": field_names,
                "attributes": class_attributes,
                "constructor_params": constructor_params,
                "methods": methods,
            }

        analysis["functions"] = functions
        analysis["classes"] = classes
        analysis["imports"] = sorted(import_roots)
        analysis["third_party_imports"] = [
            module_name for module_name in sorted(import_roots) if self._is_probable_third_party_import(module_name)
        ]
        analysis["symbols"] = sorted([item["name"] for item in functions] + list(classes.keys()))
        return analysis

    def _is_probable_third_party_import(self, module_name: str) -> bool:
        normalized_name = module_name.strip()
        if not normalized_name:
            return False
        if normalized_name == "__future__":
            return False
        if normalized_name in _STDLIB_MODULES:
            return False
        return True

    def _build_code_public_api(self, code_analysis: Dict[str, Any]) -> str:
        if not code_analysis.get("syntax_ok", True):
            return f"Module syntax error: {code_analysis.get('syntax_error') or 'unknown syntax error'}"

        lines: list[str] = []
        functions = code_analysis.get("functions") or []
        classes = code_analysis.get("classes") or {}

        if functions:
            lines.append("Functions:")
            for function in functions:
                lines.append(f"- {function['signature']}")
        else:
            lines.append("Functions:\n- none")

        if classes:
            lines.append("Classes:")
            for class_name in sorted(classes):
                class_info = classes[class_name]
                if class_info.get("is_enum"):
                    members = ", ".join(class_info.get("attributes") or []) or "none"
                    lines.append(f"- {class_name} enum members: {members}")
                    continue
                constructor = ", ".join(class_info.get("constructor_params") or [])
                class_attrs = ", ".join(class_info.get("attributes") or class_info.get("fields") or [])
                methods = ", ".join(class_info.get("methods") or [])
                suffix = f"({constructor})" if constructor else "()"
                if class_attrs:
                    lines.append(f"- {class_name}{suffix}; class attributes/fields: {class_attrs}")
                else:
                    lines.append(f"- {class_name}{suffix}")
                if methods:
                    lines.append(f"  methods: {methods}")
        else:
            lines.append("Classes:\n- none")

        lines.append(
            f"Entrypoint: {'python ' + 'MODULE_FILE' if code_analysis.get('has_main_guard') else 'no __main__ entrypoint detected'}"
        )
        return "\n".join(lines)

    def _build_module_run_command(self, module_filename: str, code_analysis: Dict[str, Any]) -> str:
        if code_analysis.get("has_main_guard"):
            return f"python {module_filename}"
        return ""

    def _analyze_test_module(self, raw_content: str, module_name: str, code_analysis: Dict[str, Any]) -> Dict[str, Any]:
        analysis: Dict[str, Any] = {
            "syntax_ok": True,
            "syntax_error": None,
            "imported_module_symbols": [],
            "missing_function_imports": [],
            "unknown_module_symbols": [],
            "invalid_member_references": [],
            "constructor_arity_mismatches": [],
        }
        if not raw_content.strip():
            return analysis
        try:
            tree = ast.parse(raw_content)
        except SyntaxError as exc:
            analysis["syntax_ok"] = False
            analysis["syntax_error"] = f"{exc.msg} at line {exc.lineno}"
            return analysis

        module_symbols = set(code_analysis.get("symbols") or [])
        function_names = {item["name"] for item in code_analysis.get("functions") or []}
        class_map = code_analysis.get("classes") or {}

        imported_symbols: set[str] = set()
        called_names: list[tuple[str, int]] = []
        attribute_refs: list[tuple[str, str, int]] = []
        constructor_calls: list[tuple[str, int, int]] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == module_name:
                for alias in node.names:
                    imported_symbols.add(alias.asname or alias.name)
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    called_names.append((node.func.id, node.lineno))
                    if node.func.id in class_map:
                        constructor_calls.append((node.func.id, len(node.args) + len(node.keywords), node.lineno))
                elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                    attribute_refs.append((node.func.value.id, node.func.attr, node.lineno))
            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                attribute_refs.append((node.value.id, node.attr, node.lineno))

        missing_imports = sorted(
            {
                f"{name} (line {lineno})"
                for name, lineno in called_names
                if name in function_names and name not in imported_symbols
            }
        )
        unknown_symbols = sorted(symbol for symbol in imported_symbols if symbol not in module_symbols)

        invalid_member_refs: list[str] = []
        for owner, member, lineno in attribute_refs:
            if owner not in imported_symbols or owner not in class_map:
                continue
            class_info = class_map[owner]
            allowed = set(class_info.get("attributes") or [])
            if not class_info.get("is_enum"):
                allowed.update(class_info.get("fields") or [])
            if member not in allowed:
                invalid_member_refs.append(f"{owner}.{member} (line {lineno})")

        arity_mismatches: list[str] = []
        for class_name, actual_count, lineno in constructor_calls:
            expected_params = class_map.get(class_name, {}).get("constructor_params") or []
            expected_count = len(expected_params)
            if expected_count != actual_count:
                arity_mismatches.append(
                    f"{class_name} expects {expected_count} args but test uses {actual_count} at line {lineno}"
                )

        analysis["imported_module_symbols"] = sorted(imported_symbols)
        analysis["missing_function_imports"] = missing_imports
        analysis["unknown_module_symbols"] = unknown_symbols
        analysis["invalid_member_references"] = sorted(set(invalid_member_refs))
        analysis["constructor_arity_mismatches"] = sorted(set(arity_mismatches))
        return analysis

    def _build_test_validation_summary(self, test_analysis: Dict[str, Any]) -> str:
        if not test_analysis.get("syntax_ok", True):
            return f"Test syntax error: {test_analysis.get('syntax_error') or 'unknown syntax error'}"

        lines = ["Generated test validation:"]
        lines.append(
            f"- Imported module symbols: {', '.join(test_analysis.get('imported_module_symbols') or ['none'])}"
        )
        lines.append(
            f"- Missing function imports: {', '.join(test_analysis.get('missing_function_imports') or ['none'])}"
        )
        lines.append(
            f"- Unknown module symbols: {', '.join(test_analysis.get('unknown_module_symbols') or ['none'])}"
        )
        lines.append(
            f"- Invalid member references: {', '.join(test_analysis.get('invalid_member_references') or ['none'])}"
        )
        lines.append(
            f"- Constructor arity mismatches: {', '.join(test_analysis.get('constructor_arity_mismatches') or ['none'])}"
        )
        return "\n".join(lines)

    def _ast_name(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return f"{self._ast_name(node.value)}.{node.attr}"
        return ""

    def _build_agent_input(self, task: Task, project: ProjectState) -> AgentInput:
        return AgentInput(
            task_id=task.id,
            task_title=task.title,
            task_description=task.description,
            project_name=project.project_name,
            project_goal=project.goal,
            context=self._build_context(task, project),
        )

    def _execute_agent(self, agent: Any, agent_input: AgentInput) -> Any:
        if hasattr(agent, "execute"):
            return agent.execute(agent_input)
        if hasattr(agent, "run_with_input"):
            return agent.run_with_input(agent_input)
        return agent.run(agent_input.task_description, agent_input.context)

    def _normalize_agent_result(self, result: Any) -> AgentOutput:
        if isinstance(result, AgentOutput):
            return result
        return AgentOutput(summary=self._summarize_output(result), raw_content=result)

    def _summarize_output(self, raw_content: str) -> str:
        stripped = raw_content.strip()
        if not stripped:
            return ""
        return stripped.splitlines()[0].strip()[:120]

    def _semantic_output_key(self, task: Task) -> Optional[str]:
        role_key = AgentRegistry.normalize_key(task.assigned_to)
        semantic_map = {
            "architect": "architecture",
            "code_engineer": "code",
            "dependency_manager": "dependencies",
            "code_reviewer": "review",
            "qa_tester": "tests",
            "docs_writer": "documentation",
            "legal_advisor": "legal",
        }
        if role_key in semantic_map:
            return semantic_map[role_key]
        title_key = task.title.lower().replace(" ", "_")
        if "architect" in title_key or "architecture" in title_key:
            return "architecture"
        if "review" in title_key:
            return "review"
        if "test" in title_key:
            return "tests"
        if "depend" in title_key or "requirement" in title_key or "package" in title_key:
            return "dependencies"
        if "doc" in title_key:
            return "documentation"
        if "legal" in title_key or "license" in title_key:
            return "legal"
        return None

    def _validate_agent_resolution(self, project: ProjectState) -> None:
        for task in project.tasks:
            if not self.registry.has(task.assigned_to):
                raise AgentExecutionError(
                    f"Task '{task.id}' is assigned to unknown agent '{task.assigned_to}'"
                )

    def execute_workflow(self, project: ProjectState):
        """Execute the full workflow until completion or an unrecoverable failure."""
        project.execution_plan()
        self._validate_agent_resolution(project)
        self._log_event("info", "workflow_started", project_name=project.project_name, phase=project.phase)
        resumed_task_ids = project.resume_interrupted_tasks()
        if self.config.workflow_resume_policy == "resume_failed":
            resumed_task_ids.extend(project.resume_failed_tasks())
        if resumed_task_ids:
            self._log_event("info", "workflow_resumed", project_name=project.project_name, task_ids=list(resumed_task_ids))
            project.save()
        project.mark_workflow_running()
        while True:
            pending = project.pending_tasks()
            if not pending:
                project.mark_workflow_finished("completed")
                project.save()
                self._log_event("info", "workflow_completed", project_name=project.project_name, phase=project.phase)
                break
            try:
                runnable = project.runnable_tasks()
            except WorkflowDefinitionError:
                project.mark_workflow_finished("failed")
                project.save()
                self._log_event("error", "workflow_failed", project_name=project.project_name, phase=project.phase)
                raise
            if not runnable:
                blocked_task_ids = ", ".join(task.id for task in project.blocked_tasks())
                project.mark_workflow_finished("failed")
                project.save()
                self._log_event(
                    "error",
                    "workflow_blocked",
                    project_name=project.project_name,
                    phase=project.phase,
                    blocked_task_ids=blocked_task_ids,
                )
                raise AgentExecutionError(
                    f"Workflow is blocked because pending tasks have unsatisfied dependencies: {blocked_task_ids}"
                )
            for task in runnable:
                try:
                    self.run_task(task, project)
                except Exception:
                    project.save()
                    if project.should_retry_task(task.id):
                        continue
                    if self.config.workflow_failure_policy == "continue":
                        skipped = project.skip_dependent_tasks(
                            task.id,
                            f"Skipped because dependency '{task.id}' failed",
                        )
                        if skipped:
                            self._log_event(
                                "warning",
                                "dependent_tasks_skipped",
                                project_name=project.project_name,
                                task_id=task.id,
                                skipped_task_ids=list(skipped),
                            )
                        continue
                    project.mark_workflow_finished("failed")
                    project.save()
                    self._log_event("error", "workflow_failed", project_name=project.project_name, phase=project.phase)
                    raise
                project.save()
        self._log_event("info", "workflow_finished", project_name=project.project_name, phase=project.phase)

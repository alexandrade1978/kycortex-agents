import argparse
import ast
import inspect
import importlib.util
from pathlib import Path
import py_compile
import sys
from typing import TypedDict

from kycortex_agents import KYCortexConfig, Orchestrator, ProjectState, Task
from kycortex_agents.provider_matrix import _public_path_label
from kycortex_agents.types import FailureCategory, TaskStatus, WorkflowOutcome


DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-haiku-4-5-20251001",
    "ollama": "qwen2.5-coder:7b",
}


class SmokeScenario(TypedDict):
    income: float
    expenses: list[float]
    prompt_focus: str


SMOKE_SCENARIOS: dict[str, SmokeScenario] = {
    "baseline": {
        "income": 5000.0,
        "expenses": [1200.0, 700.0, 450.0],
        "prompt_focus": "Typical monthly household budget with rent, utilities, and groceries.",
    },
    "tight_margin": {
        "income": 3200.0,
        "expenses": [1450.0, 620.0, 390.0, 510.0, 180.0],
        "prompt_focus": "Tight monthly margin where small arithmetic mistakes materially change the result.",
    },
    "many_expenses": {
        "income": 8700.0,
        "expenses": [
            1320.0,
            815.5,
            274.25,
            90.0,
            125.75,
            300.0,
            455.25,
            610.4,
            220.0,
            145.6,
        ],
        "prompt_focus": "Larger expense list that stresses list handling, sum correctness, and numeric stability.",
    },
}

RELEASE_USER_SMOKE_PUBLIC_CONTRACT_ANCHOR = (
    "\n\nPublic contract anchor:\n"
    "- Primary workflow function: calculate_budget_balance(income: float, expenses: list[float]) -> float\n"
    "- Supporting helper: format_currency(amount: float) -> str\n"
    "- Required CLI entrypoint: main() -> None with a literal if __name__ == \"__main__\": block\n"
    "- Keep these names exact. Do not rename calculate_budget_balance(...), format_currency(...), or main().\n"
    "- Do not wrap income and expenses in a request object, dataclass, dict, tuple, or alternate signature. Keep calculate_budget_balance(...) callable with exactly two arguments named income and expenses.\n"
    "- Use only the Python standard library."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a realistic user-style project creation smoke workflow.",
    )
    parser.add_argument(
        "provider",
        nargs="?",
        default="ollama",
        choices=sorted(DEFAULT_MODELS),
        help="Provider to validate. Defaults to ollama.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override the default model for the selected provider.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Optional custom output directory.",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Optional provider base URL override. Useful for Ollama on a custom port.",
    )
    parser.add_argument(
        "--ollama-num-ctx",
        type=int,
        default=16384,
        help="Explicit Ollama num_ctx to request during local smoke runs.",
    )
    parser.add_argument(
        "--failure-policy",
        choices=["fail_fast", "continue"],
        default="continue",
        help="Workflow failure policy for the smoke run.",
    )
    parser.add_argument(
        "--max-repair-cycles",
        type=int,
        default=1,
        help="Maximum repair cycles allowed during the smoke run.",
    )
    parser.add_argument(
        "--scenario",
        choices=sorted(SMOKE_SCENARIOS),
        default="baseline",
        help=(
            "Validation scenario profile. 'baseline' preserves historical canary behavior; "
            "other profiles add controlled daily variation."
        ),
    )
    return parser


def resolve_scenario(name: str) -> SmokeScenario:
    try:
        return SMOKE_SCENARIOS[name]
    except KeyError as exc:
        supported = ", ".join(sorted(SMOKE_SCENARIOS))
        raise ValueError(f"Unsupported scenario '{name}'. Supported: {supported}.") from exc


def build_config(args: argparse.Namespace, output_dir: str) -> KYCortexConfig:
    provider = args.provider
    model = args.model or DEFAULT_MODELS[provider]
    config_kwargs = {
        "llm_provider": provider,
        "llm_model": model,
        "temperature": 0.0,
        "max_tokens": 700,
        "timeout_seconds": 180.0,
        "workflow_failure_policy": args.failure_policy,
        "workflow_max_repair_cycles": args.max_repair_cycles,
        "project_name": f"release-user-smoke-{provider}",
        "output_dir": output_dir,
    }
    if args.base_url:
        config_kwargs["base_url"] = args.base_url
    if provider == "ollama":
        config_kwargs["ollama_num_ctx"] = args.ollama_num_ctx

    config = KYCortexConfig(**config_kwargs)
    config.validate_runtime()
    return config


def build_project(output_dir: str, provider: str, scenario_name: str = "baseline") -> ProjectState:
    scenario = resolve_scenario(scenario_name)
    prompt_focus = scenario["prompt_focus"]
    project = ProjectState(
        project_name=f"ReleaseUserSmoke{provider.title()}",
        goal=(
            "Create a single-file Python budget planner using only the standard library that exposes a function named "
            "`calculate_budget_balance(income: float, expenses: list[float]) -> float` and a minimal CLI entrypoint. "
            f"Scenario focus: {prompt_focus}"
        ),
        state_file=str(Path(output_dir) / "project_state.json"),
    )
    project.add_task(
        Task(
            id="arch",
            title="Architecture",
            description=(
                "Design a concise single-module architecture for a Python budget planner that exposes "
                "`calculate_budget_balance(income: float, expenses: list[float]) -> float`, one formatting helper, and a minimal CLI entrypoint. "
                "Use only the Python standard library and do not introduce third-party runtime dependencies or imports. "
                "Keep the architecture practical and compact."
                f" Scenario focus: {prompt_focus}"
                f"{RELEASE_USER_SMOKE_PUBLIC_CONTRACT_ANCHOR}"
            ),
            assigned_to="architect",
        )
    )
    project.add_task(
        Task(
            id="code",
            title="Implementation",
            description=(
                "Implement the planned single-file Python budget planner using only the standard library. "
                "Do not add third-party runtime dependencies or imports such as click, typer, requests, rich, or pydantic. "
                "The module must expose `calculate_budget_balance(income: float, expenses: list[float]) -> float` and a working `main()` CLI entrypoint."
                f" Scenario focus: {prompt_focus}"
                f"{RELEASE_USER_SMOKE_PUBLIC_CONTRACT_ANCHOR}"
            ),
            assigned_to="code_engineer",
            dependencies=["arch"],
        )
    )
    project.add_task(
        Task(
            id="review",
            title="Review",
            description=(
                "Review the generated budget planner for correctness, API clarity, obvious edge cases, strict compliance with the standard-library-only dependency contract, and exact preservation of the anchored public function plus CLI entrypoint."
                f" Scenario focus: {prompt_focus}"
                f"{RELEASE_USER_SMOKE_PUBLIC_CONTRACT_ANCHOR}"
            ),
            assigned_to="code_reviewer",
            dependencies=["code"],
        )
    )
    return project


def _presence_label(value: object) -> str:
    return "present" if value else "none"


def _artifact_paths(task: Task) -> list[str]:
    payload = task.output_payload if isinstance(task.output_payload, dict) else {}
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list):
        return []
    paths: list[str] = []
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        path = artifact.get("path")
        if isinstance(path, str) and path.strip():
            paths.append(path)
    return paths


def _format_output_presence(output: str | None) -> str:
    return "present" if output else "none"


def _code_artifact_path(task: Task, output_dir: str) -> Path | None:
    for relative_path in _artifact_paths(task):
        if relative_path.endswith(".py"):
            return Path(output_dir) / relative_path
    return None


def _unsupported_non_stdlib_imports(artifact_path: Path) -> list[str]:
    code_content = artifact_path.read_text(encoding="utf-8")
    module_ast = ast.parse(code_content, filename=str(artifact_path))
    stdlib_modules = frozenset(getattr(sys, "stdlib_module_names", ()))
    unsupported_imports: set[str] = set()

    for node in ast.walk(module_ast):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top_level = alias.name.split(".", 1)[0]
                if top_level != "__future__" and top_level not in stdlib_modules:
                    unsupported_imports.add(top_level)
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                unsupported_imports.add("relative import")
                continue
            top_level = (node.module or "").split(".", 1)[0]
            if top_level and top_level != "__future__" and top_level not in stdlib_modules:
                unsupported_imports.add(top_level)

    return sorted(unsupported_imports)


def _missing_symbols_from_validation_error(validation_error: str) -> list[str]:
    missing_symbols: list[str] = []
    if "calculate_budget_balance()" in validation_error:
        missing_symbols.append("calculate_budget_balance")
    if "main()" in validation_error:
        missing_symbols.append("main")
    return missing_symbols


def _has_expected_function_signature(function: object, expected_parameter_names: tuple[str, ...]) -> bool:
    if not callable(function):
        return False

    signature = inspect.signature(function)
    parameters = list(signature.parameters.values())
    if len(parameters) != len(expected_parameter_names):
        return False

    for parameter, expected_name in zip(parameters, expected_parameter_names, strict=True):
        if parameter.name != expected_name:
            return False
        if parameter.kind not in {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD}:
            return False
        if parameter.default is not inspect.Parameter.empty:
            return False

    return True


def _public_validation_error_message(error: Exception, artifact_path: Path | None) -> str:
    message = str(error)
    if artifact_path is not None:
        message = message.replace(str(artifact_path), _public_path_label(str(artifact_path)))
    return message


def _artifact_validation_failure_evaluation(
    project: ProjectState,
    *,
    acceptance_policy: str,
    validation_error: str,
    artifact_path: Path | None,
) -> dict[str, object]:
    if acceptance_policy == "required_tasks":
        evaluated_tasks = [task for task in project.tasks if task.required_for_acceptance]
    else:
        evaluated_tasks = list(project.tasks)

    completed_task_ids = [task.id for task in evaluated_tasks if task.status == TaskStatus.DONE.value]
    failed_task_ids = [task.id for task in evaluated_tasks if task.status == TaskStatus.FAILED.value]
    skipped_task_ids = [task.id for task in evaluated_tasks if task.status == TaskStatus.SKIPPED.value]
    pending_task_ids = [
        task.id
        for task in evaluated_tasks
        if task.status not in {TaskStatus.DONE.value, TaskStatus.FAILED.value, TaskStatus.SKIPPED.value}
    ]

    return {
        "policy": acceptance_policy,
        "accepted": False,
        "reason": "artifact_validation_failed",
        "evaluated_task_ids": [task.id for task in evaluated_tasks],
        "required_task_ids": [task.id for task in project.tasks if task.required_for_acceptance],
        "completed_task_ids": completed_task_ids,
        "failed_task_ids": failed_task_ids,
        "skipped_task_ids": skipped_task_ids,
        "pending_task_ids": pending_task_ids,
        "artifact_validation": {
            "validated": False,
            "artifact_path": _public_path_label(str(artifact_path)) if artifact_path is not None else None,
            "required_symbols": ["calculate_budget_balance", "main"],
            "missing_symbols": _missing_symbols_from_validation_error(validation_error),
            "error": validation_error,
        },
    }


def _persist_validation_failure(
    project: ProjectState,
    *,
    acceptance_policy: str,
    validation_error: str,
    artifact_path: Path | None,
) -> None:
    project.mark_workflow_finished(
        "failed",
        acceptance_policy=acceptance_policy,
        terminal_outcome=WorkflowOutcome.FAILED.value,
        failure_category=FailureCategory.CODE_VALIDATION.value,
        acceptance_criteria_met=False,
        acceptance_evaluation=_artifact_validation_failure_evaluation(
            project,
            acceptance_policy=acceptance_policy,
            validation_error=validation_error,
            artifact_path=artifact_path,
        ),
    )
    project.save()


def _validate_generated_code(task: Task, output_dir: str, scenario_name: str = "baseline") -> tuple[float, str]:
    scenario = resolve_scenario(scenario_name)
    artifact_path = _code_artifact_path(task, output_dir)
    if artifact_path is None or not artifact_path.exists():
        raise RuntimeError("Generated code artifact was not found.")

    py_compile.compile(str(artifact_path), doraise=True)

    unsupported_imports = _unsupported_non_stdlib_imports(artifact_path)
    if unsupported_imports:
        raise RuntimeError(
            "Generated code used unsupported non-standard-library imports: "
            f"{', '.join(unsupported_imports)}."
        )

    spec = importlib.util.spec_from_file_location("release_user_smoke_generated", artifact_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(
            f"Could not load generated code artifact: {_public_path_label(str(artifact_path))}"
        )

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    calculate_budget_balance = getattr(module, "calculate_budget_balance", None)
    if not callable(calculate_budget_balance):
        raise RuntimeError("Generated code did not expose calculate_budget_balance().")
    if not _has_expected_function_signature(calculate_budget_balance, ("income", "expenses")):
        raise RuntimeError(
            "Generated code exposed calculate_budget_balance() with an incompatible signature. "
            "Expected calculate_budget_balance(income: float, expenses: list[float])."
        )

    main = getattr(module, "main", None)
    if not callable(main):
        raise RuntimeError("Generated code did not expose main().")
    if not _has_expected_function_signature(main, ()):
        raise RuntimeError("Generated code exposed main() with an incompatible signature. Expected main() -> None.")

    income = float(scenario["income"])
    expenses = list(scenario["expenses"])
    sample_balance = calculate_budget_balance(income, expenses)
    if not isinstance(sample_balance, (int, float)):
        raise RuntimeError("calculate_budget_balance() did not return a numeric balance.")

    return float(sample_balance), str(artifact_path)


def main() -> None:
    args = build_parser().parse_args()
    output_dir = args.output_dir or f"./output/release_user_smoke_{args.provider}"
    scenario_name = getattr(args, "scenario", "baseline")
    # Keep compatibility for mocked parsers used by tests while validating user input.
    resolve_scenario(scenario_name)

    config = build_config(args, output_dir)
    project = build_project(output_dir, args.provider, scenario_name)

    Orchestrator(config).execute_workflow(project)

    code_task = next((task for task in project.tasks if task.id == "code"), None)
    if code_task is None:
        raise SystemExit("Smoke workflow did not create a code task.")

    artifact_path = _code_artifact_path(code_task, output_dir)
    try:
        sample_balance, validated_artifact_path = _validate_generated_code(code_task, output_dir, scenario_name)
    except Exception as exc:
        public_validation_error = _public_validation_error_message(exc, artifact_path)
        _persist_validation_failure(
            project,
            acceptance_policy=project.acceptance_policy or config.workflow_acceptance_policy,
            validation_error=public_validation_error,
            artifact_path=artifact_path,
        )
        raise RuntimeError(public_validation_error) from exc

    print(f"provider={_presence_label(args.provider)}")
    print(f"model={_presence_label(config.llm_model)}")
    print(f"phase={project.phase}")
    print(f"terminal_outcome={project.terminal_outcome}")
    print(f"scenario={scenario_name}")
    print(f"repair_cycles_present={_presence_label(project.repair_cycle_count)}")
    print(f"output_dir={_public_path_label(output_dir)}")
    print()

    for task in project.tasks:
        print(f"task={task.id}")
        print(f"status={task.status}")
        artifact_paths = _artifact_paths(task)
        if artifact_paths:
            print("artifacts=")
            for path in artifact_paths:
                print(_public_path_label(path))
        print(f"output_present={_format_output_presence(task.output)}")
        print("---")

    print("artifact_validation=passed")
    print(f"validated_artifact={_public_path_label(validated_artifact_path)}")
    print(f"sample_balance={sample_balance:.2f}")


if __name__ == "__main__":
    main()
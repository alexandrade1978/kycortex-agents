import logging
from dataclasses import asdict
from typing import Dict, Any, Optional

from kycortex_agents.agents.registry import AgentRegistry, build_default_registry
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.exceptions import AgentExecutionError, WorkflowDefinitionError
from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.types import AgentInput, AgentOutput, TaskStatus

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")


class Orchestrator:
    def __init__(self, config: Optional[KYCortexConfig] = None, registry: Optional[AgentRegistry] = None):
        self.config = config or KYCortexConfig()
        self.registry = registry or build_default_registry(self.config)
        self.logger = logging.getLogger("Orchestrator")

    def run_task(self, task: Task, project: ProjectState) -> str:
        self.logger.info(f"Executing task {task.id}: {task.title}")
        agent = self.registry.get(task.assigned_to)
        agent_input = self._build_agent_input(task, project)
        project.start_task(task.id)
        try:
            output = self._execute_agent(agent, agent_input)
        except Exception as exc:
            project.fail_task(task.id, exc, provider_call=self._provider_call_metadata(agent))
            if project.should_retry_task(task.id):
                self.logger.warning("Task %s failed on attempt %s and will be retried.", task.id, task.attempts)
            else:
                self.logger.exception("Task %s failed.", task.id)
            raise
        normalized_output = self._normalize_agent_result(output)
        for decision in normalized_output.decisions:
            project.add_decision_record(decision)
        for artifact in normalized_output.artifacts:
            project.add_artifact_record(artifact)
        project.complete_task(task.id, normalized_output, provider_call=self._provider_call_metadata(agent, normalized_output))
        self.logger.info(f"Task {task.id} completed.")
        return normalized_output.raw_content

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
        for prev_task in project.tasks:
            if prev_task.status == TaskStatus.DONE.value and prev_task.output:
                ctx[prev_task.id] = prev_task.output
                ctx["completed_tasks"][prev_task.id] = prev_task.output
                semantic_key = self._semantic_output_key(prev_task)
                if semantic_key:
                    ctx[semantic_key] = prev_task.output
        return ctx

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
        if "doc" in title_key:
            return "documentation"
        if "legal" in title_key or "license" in title_key:
            return "legal"
        return None

    def execute_workflow(self, project: ProjectState):
        self.logger.info(f"Starting workflow for project: {project.project_name}")
        project.execution_plan()
        resumed_task_ids = project.resume_interrupted_tasks()
        if self.config.workflow_resume_policy == "resume_failed":
            resumed_task_ids.extend(project.resume_failed_tasks())
        if resumed_task_ids:
            self.logger.info("Resuming interrupted tasks: %s", ", ".join(resumed_task_ids))
            project.save()
        project.mark_workflow_running()
        while True:
            pending = project.pending_tasks()
            if not pending:
                project.mark_workflow_finished("completed")
                project.save()
                self.logger.info("All tasks completed.")
                break
            try:
                runnable = project.runnable_tasks()
            except WorkflowDefinitionError:
                project.mark_workflow_finished("failed")
                raise
            if not runnable:
                blocked_task_ids = ", ".join(task.id for task in project.blocked_tasks())
                project.mark_workflow_finished("failed")
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
                            self.logger.warning(
                                "Skipping dependent tasks after %s failed: %s",
                                task.id,
                                ", ".join(skipped),
                            )
                        continue
                    project.mark_workflow_finished("failed")
                    raise
                project.save()
        self.logger.info(f"Project {project.project_name} finished.")

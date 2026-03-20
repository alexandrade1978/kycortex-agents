import logging
from typing import List, Dict, Any, Optional
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.memory.project_state import ProjectState, Task
from kycortex_agents.agents.architect import ArchitectAgent
from kycortex_agents.agents.code_engineer import CodeEngineerAgent
from kycortex_agents.agents.code_reviewer import CodeReviewerAgent
from kycortex_agents.agents.qa_tester import QATesterAgent
from kycortex_agents.agents.docs_writer import DocsWriterAgent
from kycortex_agents.agents.legal_advisor import LegalAdvisorAgent

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

class Orchestrator:
    def __init__(self, config: Optional[KYCortexConfig] = None):
        self.config = config or KYCortexConfig()
        self.agents = {
            "architect": ArchitectAgent(self.config),
            "code_engineer": CodeEngineerAgent(self.config),
            "code_reviewer": CodeReviewerAgent(self.config),
            "qa_tester": QATesterAgent(self.config),
            "docs_writer": DocsWriterAgent(self.config),
            "legal_advisor": LegalAdvisorAgent(self.config)
        }
        self.logger = logging.getLogger("Orchestrator")

    def run_task(self, task: Task, project: ProjectState) -> str:
        self.logger.info(f"Executing task {task.id}: {task.title}")
        agent_key = task.assigned_to.lower().replace(" ", "_")
        if agent_key not in self.agents:
            raise ValueError(f"Unknown agent: {task.assigned_to}")
        agent = self.agents[agent_key]
        context = self._build_context(task, project)
        output = agent.run(task.description, context)
        project.complete_task(task.id, output)
        self.logger.info(f"Task {task.id} completed.")
        return output

    def _build_context(self, task: Task, project: ProjectState) -> Dict[str, Any]:
        ctx = {"goal": project.goal, "project_name": project.project_name, "phase": project.phase}
        for prev_task in project.tasks:
            if prev_task.status == "done" and prev_task.output:
                ctx[prev_task.id] = prev_task.output
        return ctx

    def execute_workflow(self, project: ProjectState):
        self.logger.info(f"Starting workflow for project: {project.project_name}")
        while True:
            pending = project.pending_tasks()
            if not pending:
                self.logger.info("All tasks completed.")
                break
            for task in pending:
                self.run_task(task, project)
                project.save()
        self.logger.info(f"Project {project.project_name} finished.")

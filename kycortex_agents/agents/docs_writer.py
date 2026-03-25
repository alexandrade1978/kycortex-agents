from kycortex_agents.agents.base_agent import BaseAgent
from kycortex_agents.config import KYCortexConfig
from kycortex_agents.types import AgentInput, ArtifactType

SYSTEM_PROMPT = """You are a Technical Documentation Writer at KYCortex AI Software House.
You write clear, complete documentation: README files, API docs, architecture docs,
getting-started guides, and tutorials.
Always include: installation, usage examples, configuration reference, contributing guide.
Use Markdown. Be concise but thorough.
Document only the actual generated artifact and module that were provided.
Do not invent extra files, package layouts, CLIs, API endpoints, or components that are not present in the generated code.
If an exact run command is provided, use that exact command. If no entrypoint is provided, do not invent one."""

class DocsWriterAgent(BaseAgent):
    output_artifact_type = ArtifactType.DOCUMENT
    output_artifact_name = "documentation"

    def __init__(self, config: KYCortexConfig):
        super().__init__("DocsWriter", "Technical Documentation", config)

    def run_with_input(self, agent_input: AgentInput) -> str:
        architecture = agent_input.context.get("architecture", "")
        code_summary = agent_input.context.get("code_summary", agent_input.context.get("code", ""))
        module_name = agent_input.context.get("module_name", "module")
        module_filename = agent_input.context.get("module_filename", f"{module_name}.py")
        dependency_manifest = agent_input.context.get("dependency_manifest", "")
        dependency_manifest_path = agent_input.context.get("dependency_manifest_path", "")
        dependency_validation_summary = agent_input.context.get("dependency_validation_summary", "")
        code_public_api = agent_input.context.get("code_public_api", "")
        module_run_command = agent_input.context.get("module_run_command", "")
        test_validation_summary = agent_input.context.get("test_validation_summary", "")
        code = agent_input.context.get("code", "")
        user_msg = f"""Project: {agent_input.project_name}
Goal: {agent_input.project_goal}
    Actual module: {module_filename}
    Exact run command: {module_run_command or 'No CLI entrypoint detected'}
    Dependency manifest: {dependency_manifest_path or 'Not provided'}
Architecture: {architecture}
Code summary: {code_summary}
    Runtime dependencies:
    {dependency_manifest}
    Dependency validation summary:
    {dependency_validation_summary}
    Public API contract:
    {code_public_api}
    Test validation summary:
    {test_validation_summary}
    Generated code:
    ```python
    {code}
    ```

Task: {agent_input.task_description}

    Write complete documentation in Markdown for this actual generated module.
    Do not mention files or components that are not present in `{module_filename}`.
    If no CLI entrypoint is detected, do not tell the reader to run `main.py` or any other invented command."""
        return self.chat(SYSTEM_PROMPT, user_msg)

    def run(self, task_description: str, context: dict) -> str:
        project_name = context.get("project_name", "KYCortex")
        architecture = context.get("architecture", "")
        code_summary = context.get("code_summary", "")
        module_name = context.get("module_name", "module")
        module_filename = context.get("module_filename", f"{module_name}.py")
        dependency_manifest = context.get("dependency_manifest", "")
        dependency_manifest_path = context.get("dependency_manifest_path", "")
        dependency_validation_summary = context.get("dependency_validation_summary", "")
        code_public_api = context.get("code_public_api", "")
        module_run_command = context.get("module_run_command", "")
        test_validation_summary = context.get("test_validation_summary", "")
        code = context.get("code", "")
        user_msg = f"""Project: {project_name}
    Actual module: {module_filename}
    Exact run command: {module_run_command or 'No CLI entrypoint detected'}
    Dependency manifest: {dependency_manifest_path or 'Not provided'}
Architecture: {architecture}
Code summary: {code_summary}
    Runtime dependencies:
    {dependency_manifest}
    Dependency validation summary:
    {dependency_validation_summary}
    Public API contract:
    {code_public_api}
    Test validation summary:
    {test_validation_summary}
    Generated code:
    ```python
    {code}
    ```

Task: {task_description}

    Write complete documentation in Markdown for this actual generated module.
    Do not mention files or components that are not present in `{module_filename}`.
    If no CLI entrypoint is detected, do not tell the reader to run `main.py` or any other invented command."""
        return self.chat(SYSTEM_PROMPT, user_msg)

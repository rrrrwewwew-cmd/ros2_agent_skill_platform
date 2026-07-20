"""Official FastMCP protocol adapter for governed diagnosis tools."""

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .tools import DiagnosisToolService


_READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
_ARTIFACT_WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)


def create_server(service: DiagnosisToolService):
    """Bind one configured service to five structured MCP tools."""
    server = FastMCP(
        name='robot-experiment-diagnosis',
        instructions=(
            'Use only verified experiment run IDs. Inspect before analysis; '
            'treat candidate mechanisms as hypotheses, never causal proof. '
            'Knowledge without citations or an abstained retrieval cannot '
            'support a factual claim.'
        ),
        json_response=True,
    )

    @server.tool(
        name='list_experiment_runs',
        description='List hash-verified experiment runs under the allowlisted root.',
        annotations=_READ_ONLY,
        structured_output=True,
    )
    def list_experiment_runs() -> dict[str, Any]:
        return service.list_experiment_runs()

    @server.tool(
        name='inspect_experiment_run',
        description='Verify one run manifest, source hashes, time base and frame.',
        annotations=_READ_ONLY,
        structured_output=True,
    )
    def inspect_experiment_run(run_id: str) -> dict[str, Any]:
        return service.inspect_experiment_run(run_id)

    @server.tool(
        name='analyze_experiment_run',
        description=(
            'Compute the bounded distance matrix, anomaly windows, command '
            'correlation and non-causal mechanism candidates.'
        ),
        annotations=_READ_ONLY,
        structured_output=True,
    )
    def analyze_experiment_run(run_id: str) -> dict[str, Any]:
        return service.analyze_experiment_run(run_id)

    @server.tool(
        name='retrieve_robotics_knowledge',
        description=(
            'Retrieve version-filtered ROS/project knowledge with hash-bound '
            'citations; may abstain when evidence is insufficient.'
        ),
        annotations=_READ_ONLY,
        structured_output=True,
    )
    def retrieve_robotics_knowledge(
        query: str,
        distribution: str = 'jazzy',
        top_k: int = 3,
    ) -> dict[str, Any]:
        return service.retrieve_robotics_knowledge(
            query,
            distribution,
            top_k,
        )

    @server.tool(
        name='materialize_diagnosis_report',
        description=(
            'Generate an idempotent derived report under the configured '
            'artifact root; never modifies source experiment files.'
        ),
        annotations=_ARTIFACT_WRITE,
        structured_output=True,
    )
    def materialize_diagnosis_report(
        run_id: str,
        knowledge_queries: list[dict[str, str]],
    ) -> dict[str, Any]:
        return service.materialize_diagnosis_report(
            run_id,
            knowledge_queries,
        )

    return server

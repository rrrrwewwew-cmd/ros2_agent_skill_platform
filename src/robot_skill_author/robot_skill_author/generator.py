"""MiMo Gateway adapter for bounded structured Skill drafts."""

from robot_llm_gateway.contracts import canonical_json
from robot_llm_gateway.gateway import build_plan_request


class DraftGeneratorError(RuntimeError):
    """Report a failed or malformed model draft request."""


class GatewayDraftGenerator:
    """Ask one pinned Gateway for a structured renderer invocation."""

    def __init__(self, gateway, prompt, provider, model, timeout_sec=60.0):
        self.gateway = gateway
        self.prompt = prompt
        self.provider = provider
        self.model = model
        self.timeout_sec = float(timeout_sec)

    def generate(self, request, citations, diagnostics, attempt):
        """Return one Gateway result with no code execution capability."""
        context = {
            'request_id': request['request_id'],
            'attempt': attempt,
            'rag_citation_count': len(citations),
            'previous_gate_error': (diagnostics or '')[:1000],
        }
        user_request = (
            'Create a bounded ROS 2 Skill workflow from this exact request: '
            f'{canonical_json(request)}. Use only its allowed_dependencies.'
        )
        plan_request = build_plan_request(
            request_id=f"{request['request_id']}.author.{attempt}",
            provider=self.provider,
            model=self.model,
            prompt=self.prompt,
            user_request=user_request,
            context=context,
            max_output_tokens=2048,
            timeout_sec=self.timeout_sec,
        )
        result = self.gateway.plan(plan_request)
        if result['state'] != 'succeeded':
            error = result.get('error') or {}
            raise DraftGeneratorError(
                f"{error.get('code', 'gateway_failed')}: "
                f"{error.get('message', 'generation failed')}"
            )
        return result


class FixedDraftGenerator:
    """Return frozen plans for offline evaluation and CI."""

    def __init__(self, plans):
        self.plans = list(plans)
        self.calls = 0

    def generate(self, request, citations, diagnostics, attempt):
        """Return the matching frozen plan or repeat the final plan."""
        index = min(self.calls, len(self.plans) - 1)
        self.calls += 1
        return {
            'schema_version': 1,
            'state': 'succeeded',
            'plan': self.plans[index],
            'error': None,
        }

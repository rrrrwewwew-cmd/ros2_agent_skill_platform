"""Xiaomi MiMo transport and deterministic offline test provider."""

from dataclasses import dataclass
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ProviderError(RuntimeError):
    """Report a sanitized provider or transport failure."""


@dataclass(frozen=True)
class ProviderResponse:
    """Normalize provider output before local plan validation."""

    content: str
    request_id: str | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None


def _http_transport(url, headers, payload, timeout_sec):
    """POST JSON with the standard library and return one JSON object."""
    request = Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers=headers,
        method='POST',
    )
    try:
        with urlopen(request, timeout=timeout_sec) as response:
            body = response.read().decode('utf-8')
    except HTTPError as exc:
        raise ProviderError(f'MiMo HTTP status {exc.code}') from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ProviderError('MiMo transport unavailable') from exc
    try:
        value = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ProviderError('MiMo returned non-JSON response') from exc
    if not isinstance(value, dict):
        raise ProviderError('MiMo response must be a JSON object')
    return value


class MimoProvider:
    """Call Xiaomi MiMo Chat Completions without exposing credentials."""

    name = 'xiaomi_mimo'
    default_base_url = 'https://api.xiaomimimo.com/v1'
    default_model = 'mimo-v2.5-pro'

    def __init__(self, api_key, base_url=None, transport=None):
        """Configure MiMo with an injected transport for deterministic tests."""
        if not api_key or not api_key.strip():
            raise ProviderError('MIMO_API_KEY is required')
        self._api_key = api_key.strip()
        self.base_url = (
            base_url or self.default_base_url
        ).rstrip('/')
        self._transport = transport or _http_transport

    @classmethod
    def from_environment(cls, transport=None):
        """Load credentials and optional endpoint override from environment."""
        return cls(
            api_key=os.environ.get('MIMO_API_KEY', ''),
            base_url=os.environ.get('MIMO_BASE_URL'),
            transport=transport,
        )

    def complete(
        self,
        model,
        messages,
        max_output_tokens,
        temperature,
        timeout_sec,
    ):
        """Request one non-streaming JSON planning response from MiMo."""
        payload = {
            'model': model,
            'messages': messages,
            'max_completion_tokens': max_output_tokens,
            'temperature': temperature,
            'stream': False,
            'thinking': {'type': 'disabled'},
            'response_format': {'type': 'json_object'},
        }
        headers = {
            'Authorization': f'Bearer {self._api_key}',
            'Content-Type': 'application/json',
        }
        response = self._transport(
            f'{self.base_url}/chat/completions',
            headers,
            payload,
            timeout_sec,
        )
        try:
            content = response['choices'][0]['message']['content']
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError('MiMo response has no assistant content') from exc
        if not isinstance(content, str) or not content.strip():
            raise ProviderError('MiMo returned empty assistant content')
        usage = response.get('usage') or {}
        return ProviderResponse(
            content=content,
            request_id=_optional_string(response.get('id')),
            input_tokens=_optional_int(usage.get('prompt_tokens')),
            output_tokens=_optional_int(usage.get('completion_tokens')),
            total_tokens=_optional_int(usage.get('total_tokens')),
        )


class FakeProvider:
    """Return a deterministic response for offline CI; never call a network."""

    name = 'fake'

    def __init__(self, plan):
        """Store the exact plan returned by every fake completion."""
        self.plan = plan
        self.call_count = 0

    def complete(
        self,
        model,
        messages,
        max_output_tokens,
        temperature,
        timeout_sec,
    ):
        """Return canonical JSON while recording that one call occurred."""
        del model, messages, max_output_tokens, temperature, timeout_sec
        self.call_count += 1
        return ProviderResponse(
            content=json.dumps(self.plan, ensure_ascii=False),
            request_id='fake-request-001',
            input_tokens=10,
            output_tokens=20,
            total_tokens=30,
        )


def _optional_int(value):
    """Accept non-negative integer usage counters only."""
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _optional_string(value):
    """Accept non-empty string request identifiers only."""
    if isinstance(value, str) and value:
        return value
    return None

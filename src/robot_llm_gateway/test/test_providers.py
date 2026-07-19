"""Tests for the Xiaomi MiMo provider boundary."""

import pytest

from robot_llm_gateway.providers import MimoProvider, ProviderError


def test_mimo_request_matches_official_chat_completion_shape():
    """The MiMo request uses bounded non-streaming JSON-mode parameters."""
    captured = {}

    def transport(url, headers, payload, timeout_sec):
        captured.update({
            'url': url,
            'headers': headers,
            'payload': payload,
            'timeout_sec': timeout_sec,
        })
        return {
            'id': 'mimo-request-123',
            'choices': [{'message': {'content': '{"ok":true}'}}],
            'usage': {
                'prompt_tokens': 11,
                'completion_tokens': 7,
                'total_tokens': 18,
            },
        }

    provider = MimoProvider('test-secret', transport=transport)
    response = provider.complete(
        model='mimo-v2.5-pro',
        messages=[{'role': 'user', 'content': 'json only'}],
        max_output_tokens=512,
        temperature=0.0,
        timeout_sec=12.5,
    )
    assert captured['url'] == (
        'https://api.xiaomimimo.com/v1/chat/completions'
    )
    assert captured['headers']['Authorization'] == 'Bearer test-secret'
    assert captured['payload']['max_completion_tokens'] == 512
    assert captured['payload']['stream'] is False
    assert captured['payload']['thinking'] == {'type': 'disabled'}
    assert captured['payload']['response_format'] == {'type': 'json_object'}
    assert captured['timeout_sec'] == 12.5
    assert response.request_id == 'mimo-request-123'
    assert response.total_tokens == 18


def test_mimo_base_url_can_be_overridden_for_token_plan_accounts():
    """Deployment may select a MiMo account-specific endpoint."""
    captured = {}

    def transport(url, headers, payload, timeout_sec):
        del headers, payload, timeout_sec
        captured['url'] = url
        return {
            'choices': [{'message': {'content': '{"ok":true}'}}],
        }

    provider = MimoProvider(
        'secret',
        base_url='https://account-endpoint.example/v1/',
        transport=transport,
    )
    provider.complete('model', [], 128, 0.0, 1.0)
    assert captured['url'] == (
        'https://account-endpoint.example/v1/chat/completions'
    )


def test_mimo_empty_content_fails_closed_without_secret_in_error():
    """Empty provider output never becomes an executable plan."""
    provider = MimoProvider(
        'do-not-leak-this',
        transport=lambda *args: {
            'choices': [{'message': {'content': ''}}],
        },
    )
    with pytest.raises(ProviderError) as captured:
        provider.complete('model', [], 128, 0.0, 1.0)
    assert 'do-not-leak-this' not in str(captured.value)


def test_missing_mimo_key_is_rejected_before_network_access():
    """A missing credential reports configuration failure locally."""
    with pytest.raises(ProviderError, match='MIMO_API_KEY'):
        MimoProvider('')


def test_token_plan_key_is_rejected_before_network_access():
    """Token Plan credentials cannot fund a custom Agent backend."""
    with pytest.raises(ProviderError, match='Token Plan'):
        MimoProvider('tp-not-for-custom-backends')

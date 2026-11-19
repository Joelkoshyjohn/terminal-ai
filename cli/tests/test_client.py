import json

import httpx
import pytest

from aiterminal.client import AITerminalClient, ChatResponse, DEFAULT_API_URL, ServiceError


def client_for(handler):
    transport = httpx.MockTransport(handler)
    return AITerminalClient("https://example.netlify.app", transport=transport)


def test_chat_sends_question_and_history_without_authentication():
    seen = []

    def handler(request):
        seen.append(request)
        assert request.url.path == "/.netlify/functions/chat"
        assert "authorization" not in request.headers
        assert json.loads(request.read()) == {
            "message": "Follow up",
            "history": [{"role": "user", "content": "Earlier"}],
        }
        return httpx.Response(200, json={"answer": "A response"})

    with client_for(handler) as client:
        assert client.ask("Follow up", [{"role": "user", "content": "Earlier"}]) == "A response"

    assert len(seen) == 1


def test_chat_returns_a_structured_proposal_separately_from_the_answer():
    with client_for(
        lambda _request: httpx.Response(
            200,
            json={
                "answer": "I can check that for you.",
                "proposal": {"action": "python_version", "arguments": {}},
            },
        )
    ) as client:
        assert client.ask_with_proposal("Check Python", []) == ChatResponse(
            "I can check that for you.",
            {"action": "python_version", "arguments": {}},
        )
        assert client.ask("Check Python", []) == "I can check that for you."


def test_rate_limit_and_server_errors_are_reported():
    with client_for(lambda _request: httpx.Response(429, json={"error": "Request limit reached."})) as client:
        with pytest.raises(ServiceError, match="Request limit reached"):
            client.ask("hello", [])

    with client_for(lambda _request: httpx.Response(503, json={"error": "Shared rate limiting unavailable."})) as client:
        with pytest.raises(ServiceError, match="Shared rate limiting unavailable"):
            client.ask("hello", [])


def test_network_timeout_and_invalid_response_errors_are_reported():
    def network_error(_request):
        raise httpx.ConnectError("private connection detail")

    with client_for(network_error) as client:
        with pytest.raises(ServiceError, match="Could not connect"):
            client.ask("hello", [])

    def timeout(_request):
        raise httpx.ReadTimeout("private timeout detail")

    with client_for(timeout) as client:
        with pytest.raises(ServiceError, match="timed out"):
            client.ask("hello", [])

    with client_for(lambda _request: httpx.Response(200, json={"unexpected": True})) as client:
        with pytest.raises(ServiceError, match="invalid response"):
            client.ask("hello", [])


def test_https_is_required_outside_local_development():
    with pytest.raises(ValueError, match="HTTPS"):
        AITerminalClient("http://api.example.com")
    with pytest.raises(ValueError, match="credentials"):
        AITerminalClient("https://user:password@example.com")
    with AITerminalClient("http://localhost:8888"):
        pass


def test_default_backend_url_is_used_without_configuration(monkeypatch):
    monkeypatch.delenv("AIT_TERMINAL_API_URL", raising=False)
    seen = []

    def handler(request):
        seen.append(request)
        assert request.url == f"{DEFAULT_API_URL}/.netlify/functions/chat"
        assert "authorization" not in request.headers
        return httpx.Response(200, json={"answer": "connected"})

    with AITerminalClient(transport=httpx.MockTransport(handler)) as client:
        assert client.base_url == "https://aiterminal-cloud.netlify.app"
        assert client.ask("hello", []) == "connected"
    assert len(seen) == 1

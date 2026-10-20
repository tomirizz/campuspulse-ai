import asyncio
from types import SimpleNamespace

import httpx
import pytest
from google.genai.errors import ClientError, ServerError

from campuspulse import provider_requests


SECRET = "private-request-content-never-log"


def sdk_error(status):
    return (ServerError if status >= 500 else ClientError)(status, {
        "error": {"code": status, "message": SECRET, "status": "FAILED"}})


class Clock:
    """Virtual requests and timeouts; no sleeping, provider or network access."""

    def __init__(self, monkeypatch):
        self.now = 100.0
        self.sleeps = []
        self.timeouts = []
        monkeypatch.setattr(provider_requests, "monotonic", lambda: self.now)
        monkeypatch.setattr(provider_requests, "sleep", self.sleep)
        monkeypatch.setattr(provider_requests, "wait_for", self.wait_for)

    async def sleep(self, delay):
        self.sleeps.append(delay)
        self.now += delay

    async def wait_for(self, awaitable, timeout):
        self.timeouts.append(timeout)
        start = self.now
        try:
            result = await awaitable
        except Exception:
            if self.now - start >= timeout:
                self.now = start + timeout
                raise TimeoutError("virtual total deadline") from None
            raise
        if self.now - start >= timeout:
            self.now = start + timeout
            raise TimeoutError("virtual total deadline")
        return result

    def client(self, outcomes):
        calls = []

        async def generate_content(**kwargs):
            calls.append(kwargs)
            duration, outcome = outcomes[len(calls) - 1]
            self.now += duration
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

        return SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))), calls


@pytest.mark.asyncio
async def test_success_is_same_sdk_response_and_input_is_unchanged(monkeypatch):
    clock = Clock(monkeypatch)
    response = SimpleNamespace(text="real SDK shape")
    client, calls = clock.client([(2, response)])
    contents = [{"text": "unchanged student input"}]
    result = await provider_requests.generate_content(client, model="chosen-model", contents=contents)
    assert result is response
    assert len(calls) == 1 and calls[0]["contents"] is contents
    assert contents == [{"text": "unchanged student input"}]
    assert calls[0]["model"] == "chosen-model"
    assert clock.timeouts == [45] and not clock.sleeps


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [500, 502, 503])
async def test_one_retry_uses_remaining_total_budget_without_model_change(monkeypatch, status):
    clock = Clock(monkeypatch)
    response = object()
    client, calls = clock.client([(2, sdk_error(status)), (3, response)])
    result = await provider_requests.generate_content(client, model="same-model", contents=SECRET)
    assert result is response and len(calls) == 2
    assert calls[0] == calls[1] == {"model": "same-model", "contents": SECRET}
    assert clock.sleeps == [1] and clock.timeouts == [45, 42]
    assert clock.now == 106


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 404, 408, 429, 501, 504])
async def test_no_retry_for_auth_quota_timeout_or_other_statuses(monkeypatch, status, capsys):
    clock = Clock(monkeypatch)
    failure = sdk_error(status)
    client, calls = clock.client([(0, failure)])
    with pytest.raises(type(failure)) as caught:
        await provider_requests.generate_content(client, model="chosen-model")
    assert caught.value is failure
    assert len(calls) == 1 and not clock.sleeps
    captured = capsys.readouterr()
    assert not captured.out and not captured.err


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [TimeoutError(SECRET), httpx.ReadTimeout(SECRET),
                                     httpx.ConnectError(SECRET), ValueError(SECRET)])
async def test_no_retry_after_timeout_or_unknown_exception(monkeypatch, failure):
    clock = Clock(monkeypatch)
    client, calls = clock.client([(1, failure)])
    with pytest.raises(type(failure)) as caught:
        await provider_requests.generate_content(client)
    assert caught.value is failure and len(calls) == 1 and not clock.sleeps


@pytest.mark.asyncio
async def test_two_failures_propagate_last_error_and_never_make_third_call(monkeypatch):
    clock = Clock(monkeypatch)
    final_failure = sdk_error(503)
    client, calls = clock.client([(1, sdk_error(500)), (1, final_failure)])
    with pytest.raises(ServerError) as caught:
        await provider_requests.generate_content(client)
    assert caught.value is final_failure and len(calls) == 2 and clock.sleeps == [1]


@pytest.mark.asyncio
async def test_less_than_five_seconds_remaining_does_not_retry(monkeypatch):
    clock = Clock(monkeypatch)
    failure = sdk_error(503)
    client, calls = clock.client([(40.1, failure)])
    with pytest.raises(ServerError) as caught:
        await provider_requests.generate_content(client)
    assert caught.value is failure and len(calls) == 1 and not clock.sleeps


@pytest.mark.asyncio
async def test_exact_five_seconds_remaining_allows_only_remaining_four_after_pause(monkeypatch):
    clock = Clock(monkeypatch)
    response = object()
    client, calls = clock.client([(40, sdk_error(503)), (1, response)])
    assert await provider_requests.generate_content(client) is response
    assert clock.timeouts == [45, 4] and len(calls) == 2


@pytest.mark.asyncio
async def test_second_call_cannot_extend_original_deadline(monkeypatch):
    clock = Clock(monkeypatch)
    client, calls = clock.client([(36, sdk_error(503)), (20, object())])
    with pytest.raises(TimeoutError):
        await provider_requests.generate_content(client)
    assert clock.timeouts == [45, 8] and len(calls) == 2
    assert clock.now == 145  # 36s first call + 1s pause + at most 8s second.


@pytest.mark.asyncio
async def test_first_call_exhausting_budget_is_not_retried(monkeypatch):
    clock = Clock(monkeypatch)
    client, calls = clock.client([(50, sdk_error(503))])
    with pytest.raises(TimeoutError):
        await provider_requests.generate_content(client)
    assert clock.now == 145 and len(calls) == 1 and not clock.sleeps


@pytest.mark.asyncio
async def test_scheduler_delay_cannot_start_a_call_after_deadline(monkeypatch):
    clock = Clock(monkeypatch)
    client, calls = clock.client([(2, sdk_error(503))])

    async def delayed_sleep(delay):
        clock.now += 50

    monkeypatch.setattr(provider_requests, "sleep", delayed_sleep)
    with pytest.raises(TimeoutError):
        await provider_requests.generate_content(client)
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout,expected", [(12, 12), (120, 45)])
async def test_requested_timeout_is_honored_but_never_above_45(monkeypatch, timeout, expected):
    clock = Clock(monkeypatch)
    client, _ = clock.client([(0, object())])
    await provider_requests.generate_content(client, timeout=timeout)
    assert clock.timeouts == [expected]


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout", [0, -1, True, "invalid", None, float("inf"), float("nan")])
async def test_invalid_timeout_never_calls_sdk(monkeypatch, timeout):
    clock = Clock(monkeypatch)
    client, calls = clock.client([])
    with pytest.raises(ValueError, match="positive number"):
        await provider_requests.generate_content(client, timeout=timeout)
    assert not calls


@pytest.mark.asyncio
async def test_task_cancellation_is_propagated_without_retry(monkeypatch):
    clock = Clock(monkeypatch)
    client, calls = clock.client([(0, asyncio.CancelledError())])
    with pytest.raises(asyncio.CancelledError):
        await provider_requests.generate_content(client)
    assert len(calls) == 1 and not clock.sleeps

"""Bounded subprocess hosting the optional official Copilot SDK, with no tools."""

import asyncio
import importlib
import logging
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

from token_maxxxer.json_io import load_unique_json
from token_maxxxer.models import UsageObservation, utc_now
from token_maxxxer.provider_errors import classify_failure
from token_maxxxer.results import GenerationResult


async def generate(payload: dict[str, Any]) -> GenerationResult:
    started = time.monotonic()
    try:
        sdk = importlib.import_module("copilot")
    except ImportError:
        return GenerationResult(status="auth_error", error_code="copilot_sdk_required")
    credential = payload["credential"]
    client = sdk.CopilotClient(
        working_directory=str(Path.cwd()),
        log_level="error",
        mode="empty",
        github_token=credential or None,
        use_logged_in_user=not bool(credential),
    )
    failure: GenerationResult | None = None
    usage = None

    def observe(event: Any) -> None:
        nonlocal failure, usage
        if getattr(event, "agent_id", None):
            failure = GenerationResult(
                status="invalid_output", error_code="copilot_unexpected_agent"
            )
        kind = getattr(event.type, "value", event.type)
        if kind == "session.error":
            status, code = classify_failure(
                getattr(event.data, "error_code", None) or getattr(event.data, "error_type", None),
                getattr(event.data, "message", ""),
                getattr(event.data, "status_code", None),
            )
            failure = GenerationResult(status=status, error_code=code)
        elif kind == "tool.execution_start":
            failure = GenerationResult(
                status="invalid_output", error_code="copilot_unexpected_tool"
            )
        elif kind == "assistant.usage":
            usage = UsageObservation(
                observed_at=utc_now(),
                source="copilot_sdk",
                input_tokens=getattr(event.data, "input_tokens", None),
                output_tokens=getattr(event.data, "output_tokens", None),
            )

    def deny_permission(*args: Any, **kwargs: Any) -> object:
        permissions = importlib.import_module("copilot.session")
        return permissions.PermissionDecisionUserNotAvailable()

    try:
        async with asyncio.timeout(payload["timeout_seconds"]):
            await client.start()
            session = await client.create_session(
                model=payload["model"],
                available_tools=[],
                on_permission_request=deny_permission,
                working_directory=str(Path.cwd()),
                enable_config_discovery=False,
                skip_custom_instructions=True,
                enable_skills=False,
                enable_file_hooks=False,
                enable_host_git_operations=False,
                enable_session_store=False,
                mcp_servers={},
                on_event=observe,
                interactive_user=False,
            )
            reply = await session.send_and_wait(
                payload["prompt"], timeout=payload["timeout_seconds"]
            )
            if failure is not None:
                return failure.model_copy(update={"duration_seconds": time.monotonic() - started})
            data = getattr(reply, "data", None)
            content = getattr(data, "content", None)
            if (
                not isinstance(content, str)
                or not content.strip()
                or getattr(data, "tool_requests", None)
            ):
                return GenerationResult(
                    status="invalid_output", error_code="copilot_incomplete_turn"
                )
            return GenerationResult(
                status="success",
                text=content,
                usage=usage,
                response_id=getattr(data, "message_id", None),
                provider="copilot",
                model=payload["model"],
                duration_seconds=time.monotonic() - started,
            )
    except TimeoutError:
        return GenerationResult(status="timeout", error_code="copilot_timeout")
    except Exception as error:
        # Session errors can arrive before send_and_wait raises. Never expose its text.
        if failure is not None:
            return failure
        status, code = classify_failure(
            getattr(error, "code", None), str(error), getattr(error, "status_code", None)
        )
        return GenerationResult(status=status, error_code=code)
    finally:
        with suppress(Exception):
            await asyncio.wait_for(client.force_stop(), timeout=3)


def main() -> None:
    logging.disable(logging.CRITICAL)
    try:
        payload = load_unique_json(sys.stdin.read(8_388_609))
        if not isinstance(payload, dict):
            raise ValueError("invalid request")
        result = asyncio.run(generate(payload))
    except Exception:
        result = GenerationResult(status="invalid_output", error_code="copilot_worker_failed")
    print(result.model_dump_json())


if __name__ == "__main__":
    main()

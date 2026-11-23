import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult, InitializeResult, TextContent

from .config import Registration
from .unity import MEMBER_OPERATION, WORKLOAD_TYPE


class ReaError(RuntimeError):
    pass


@dataclass(frozen=True)
class ToolAvailability:
    name: str
    available: bool
    reason: str | None


@dataclass(frozen=True)
class ProviderAvailability:
    name: str
    status: str
    reason: str | None


@dataclass(frozen=True)
class SessionReport:
    server: str
    version: str
    protocol_version: str
    target_open: bool
    tools: tuple[ToolAvailability, ...]
    providers: tuple[ProviderAvailability, ...]
    session_capabilities: tuple[str, ...]


def _parse_reply(reply: CallToolResult, tool: str) -> dict[str, Any]:
    if reply.isError:
        detail = next((part.text for part in reply.content if isinstance(part, TextContent)), "")
        raise ReaError(f"REA {tool} returned an error: {detail[:500]}")
    payload = reply.structuredContent
    if payload is None:
        try:
            payload = json.loads(next(part.text for part in reply.content if isinstance(part, TextContent)))
        except (StopIteration, json.JSONDecodeError) as error:
            raise ReaError(f"REA {tool} returned no readable JSON") from error
    if not isinstance(payload, dict):
        raise ReaError(f"REA {tool} returned an unexpected format")
    return payload


async def _list_tools(session: ClientSession, timeout: float) -> set[str]:
    advertised: set[str] = set()
    seen_cursors: set[str] = set()
    cursor = None
    try:
        async with asyncio.timeout(timeout):
            while True:
                page = await session.list_tools(cursor=cursor)
                advertised.update(tool.name for tool in page.tools)
                cursor = page.nextCursor
                if cursor is None:
                    break
                if cursor in seen_cursors:
                    raise ReaError("REA returned a repeated tool catalog cursor")
                seen_cursors.add(cursor)
    except TimeoutError as error:
        raise ReaError("Timed out discovering REA tools") from error
    return advertised


async def _call(
    session: ClientSession, timeout: float, advertised: set[str], tool: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    if tool not in advertised:
        raise ReaError(f"REA did not advertise {tool}")
    try:
        async with asyncio.timeout(timeout):
            return _parse_reply(await session.call_tool(tool, arguments=arguments), tool)
    except TimeoutError as error:
        raise ReaError(f"Timed out calling REA {tool}") from error


def _session_report(hello: InitializeResult, advertised: set[str], status: Any) -> SessionReport:
    if not isinstance(status, dict) or type(status.get("open")) is not bool:
        raise ReaError("REA binary_session returned an unexpected status format")

    try:
        availability = {
            name: ToolAvailability(name, group["available"], group.get("reason"))
            for group in status["tool_availability"]["groups"]
            for name in group["names"]
        }
        providers = tuple(
            ProviderAvailability(
                candidate["provider"]["name"], candidate["availability"]["status"],
                candidate["availability"].get("reason"),
            )
            for candidate in status["analysis_provider_candidates"]
        )
        capabilities = tuple(item["provider"]["name"] for item in status["capabilities"])
    except (KeyError, TypeError, AttributeError) as error:
        raise ReaError("REA binary_session returned an unexpected capability inventory") from error
    return SessionReport(
        hello.serverInfo.name, hello.serverInfo.version, hello.protocolVersion, status["open"],
        tuple(
            availability.get(name, ToolAvailability(name, False, "availability_not_reported"))
            for name in sorted(advertised)
        ),
        providers, capabilities,
    )


@asynccontextmanager
async def _connect(registration: Registration) -> AsyncIterator[tuple[ClientSession, InitializeResult]]:
    params = StdioServerParameters(
        command=registration.command, args=list(registration.args),
        env=registration.env, cwd=registration.cwd,
    )
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                try:
                    async with asyncio.timeout(registration.startup_timeout):
                        hello = await session.initialize()
                except TimeoutError as error:
                    raise ReaError("Timed out initializing the REA MCP session") from error
                if hello.serverInfo.name != "rea":
                    raise ReaError("The registered subprocess did not identify itself as REA")
                yield session, hello
    except ReaError:
        raise
    except Exception as error:
        cause = error
        while isinstance(cause, ExceptionGroup):
            cause = cause.exceptions[0]
        if isinstance(cause, ReaError):
            raise cause from error
        raise ReaError(f"REA MCP connection failed: {cause}") from error


async def check_rea(registration: Registration) -> SessionReport:
    async with _connect(registration) as (session, hello):
        advertised = await _list_tools(session, registration.tool_timeout)
        payload = await _call(session, registration.tool_timeout, advertised, "binary_session", {})
        return _session_report(hello, advertised, payload.get("result"))


async def inspect_directory(registration: Registration, root: Path) -> dict[str, Any]:
    root = root.resolve()
    if not root.is_dir():
        raise ReaError(f"Expected a local JavaScript application directory: {root}")
    async with _connect(registration) as (session, _hello):
        advertised = await _list_tools(session, registration.tool_timeout)
        evidence = await _call(
            session, registration.tool_timeout, advertised, "analyze_javascript_application",
            {"input_path": str(root), "format": "directory", "detail": "summary"},
        )
        view = evidence.get("normalized_result")
        if not isinstance(view, dict) or view.get("kind") != "summary":
            raise ReaError("REA did not return the expected JavaScript inspection summary")
        return evidence


async def inspect_unity_assembly(registration: Registration, path: Path) -> dict[str, Any]:
    path = path.resolve()
    if path.suffix.lower() != ".dll" or not path.is_file():
        raise ReaError(f"Expected a local managed Unity DLL: {path}")
    with path.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise ReaError(f"Expected a PE/CLI assembly: {path}")
    async with _connect(registration) as (session, _hello):
        advertised = await _list_tools(session, registration.tool_timeout)
        evidence = await _call(
            session, registration.tool_timeout, advertised, MEMBER_OPERATION,
            {"path": str(path), "detail": "summary", "type_names": [WORKLOAD_TYPE]},
        )
        view = evidence.get("normalized_result")
        if (
            not isinstance(view, dict) or view.get("kind") != "summary"
            or view.get("parent_operation") != MEMBER_OPERATION
        ):
            raise ReaError("REA did not return the expected managed member summary")
        return evidence

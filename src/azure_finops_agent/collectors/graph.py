"""Resource Graph queries with full pagination (``skip_token``)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Any, Protocol

from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions

from .errors import AzureDataError
from .retry import RetryPolicy, call_with_retry

MAX_PAGE_SIZE = 1000  # Resource Graph hard limit per page


class GraphClient(Protocol):
    def resources(self, query: QueryRequest, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class GraphResult:
    rows: list[dict[str, Any]]
    truncated: bool  # True if we stopped early; caller must add a limitation


def query_all(
    client: GraphClient,
    subscription_id: str,
    query: str,
    *,
    page_size: int = MAX_PAGE_SIZE,
    max_rows: int = 50_000,
    max_pages: int = 100,
    policy: RetryPolicy = RetryPolicy(),  # noqa: B008
    sleep: Callable[[float], None] | None = None,
) -> GraphResult:
    if not 1 <= page_size <= MAX_PAGE_SIZE:
        raise ValueError(f"page_size must be 1..{MAX_PAGE_SIZE}")
    if not query.strip():
        raise ValueError("query must not be empty")

    rows: list[dict[str, Any]] = []
    token: str | None = None
    seen_tokens: set[str] = set()

    for _ in range(max_pages):
        options = QueryRequestOptions(top=page_size, skip_token=token, result_format="objectArray")
        request = QueryRequest(subscriptions=[subscription_id], query=query, options=options)
        kwargs: dict[str, Any] = {"operation": "resource-graph query"}
        if sleep is not None:
            kwargs["sleep"] = sleep
        try:
            resp = call_with_retry(partial(client.resources, request), policy, **kwargs)
        except Exception as exc:
            raise AzureDataError(
                "resource-graph query",
                type(exc).__name__,
                status_code=getattr(exc, "status_code", None),
            ) from exc

        rows.extend(resp.data or [])
        token = getattr(resp, "skip_token", None) or None

        if len(rows) >= max_rows:
            return GraphResult(rows[:max_rows], truncated=bool(token) or len(rows) > max_rows)
        if not token:
            truncated = str(getattr(resp, "result_truncated", "false")).lower() == "true"
            return GraphResult(rows, truncated=truncated)
        if token in seen_tokens:
            raise AzureDataError("resource-graph query", "repeated skip_token (paging loop)")
        seen_tokens.add(token)

    return GraphResult(rows, truncated=True)  # hit max_pages

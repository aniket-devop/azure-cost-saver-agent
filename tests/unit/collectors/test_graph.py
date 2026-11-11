from types import SimpleNamespace as NS

import pytest

from azure_finops_agent.collectors.errors import AzureDataError
from azure_finops_agent.collectors.graph import query_all
from azure_finops_agent.collectors.retry import RetryPolicy

SUB = "11111111-1111-1111-1111-111111111111"
FAST = RetryPolicy(max_attempts=2, base_delay=0, jitter=0)


class FakeGraph:
    def __init__(self, pages):
        self.pages = list(pages)
        self.requests = []

    def resources(self, request):
        self.requests.append(request)
        page = self.pages.pop(0)
        if isinstance(page, Exception):
            raise page
        return page


def page(n, token=None, truncated="false"):
    return NS(
        data=[{"id": f"r{i}"} for i in range(n)], skip_token=token, result_truncated=truncated
    )


def test_follows_skip_token_across_pages():
    g = FakeGraph([page(3, "t1"), page(3, "t2"), page(2)])
    res = query_all(g, SUB, "Resources", page_size=3)
    assert len(res.rows) == 8 and not res.truncated
    tokens = [r.options.skip_token for r in g.requests]
    assert tokens == [None, "t1", "t2"]
    assert all(r.options.top == 3 for r in g.requests)
    assert all(r.subscriptions == [SUB] for r in g.requests)


def test_single_page():
    res = query_all(FakeGraph([page(2)]), SUB, "Resources")
    assert len(res.rows) == 2 and not res.truncated


def test_empty_result():
    res = query_all(FakeGraph([NS(data=None, skip_token=None, result_truncated="false")]), SUB, "Q")
    assert res.rows == [] and not res.truncated


def test_max_rows_marks_truncated():
    g = FakeGraph([page(5, "t1"), page(5, "t2")])
    res = query_all(g, SUB, "Resources", page_size=5, max_rows=7)
    assert len(res.rows) == 7 and res.truncated


def test_result_truncated_without_token_is_reported():
    res = query_all(FakeGraph([page(2, None, "true")]), SUB, "Resources")
    assert res.truncated


def test_max_pages_marks_truncated():
    g = FakeGraph([page(1, "a"), page(1, "b"), page(1, "c")])
    res = query_all(g, SUB, "Resources", max_pages=2)
    assert res.truncated and len(res.rows) == 2


def test_repeated_token_is_a_loop_error():
    g = FakeGraph([page(1, "same"), page(1, "same")])
    with pytest.raises(AzureDataError, match="paging loop"):
        query_all(g, SUB, "Resources")


def test_transient_error_is_retried_then_succeeds():
    err = RuntimeError("x")
    err.status_code = 429
    g = FakeGraph([err, page(2)])
    res = query_all(g, SUB, "Resources", policy=FAST, sleep=lambda s: None)
    assert len(res.rows) == 2 and len(g.requests) == 2


def test_permanent_error_becomes_azure_data_error():
    err = RuntimeError("secret-looking detail")
    err.status_code = 403
    with pytest.raises(AzureDataError) as ei:
        query_all(FakeGraph([err]), SUB, "Resources", policy=FAST)
    assert ei.value.status_code == 403
    assert "secret-looking detail" not in str(ei.value)


@pytest.mark.parametrize("size", [0, 1001])
def test_invalid_page_size(size):
    with pytest.raises(ValueError):
        query_all(FakeGraph([]), SUB, "Resources", page_size=size)


def test_empty_query_rejected():
    with pytest.raises(ValueError):
        query_all(FakeGraph([]), SUB, "  ")

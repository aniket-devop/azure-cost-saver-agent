import pytest

from azure_finops_agent.config import ConfigError, load_settings

SUB = "11111111-1111-1111-1111-111111111111"


def test_defaults():
    s = load_settings({"AZURE_SUBSCRIPTION_ID": SUB})
    assert s.lookback_days == 7
    assert s.cpu_idle_threshold_pct == 5.0
    assert s.cpu_max_threshold_pct == 30.0
    assert s.teams_webhook_url is None


def test_missing_subscription():
    with pytest.raises(ConfigError, match="AZURE_SUBSCRIPTION_ID is required"):
        load_settings({})


def test_bad_subscription():
    with pytest.raises(ConfigError, match="GUID"):
        load_settings({"AZURE_SUBSCRIPTION_ID": "not-a-guid"})


@pytest.mark.parametrize("days", ["0", "91", "abc"])
def test_bad_lookback(days):
    with pytest.raises(ConfigError, match="lookback_days"):
        load_settings({"AZURE_SUBSCRIPTION_ID": SUB, "LOOKBACK_DAYS": days})


def test_webhook_is_redacted():
    url = "https://example.invalid/hook?sig=SECRET123"
    s = load_settings({"AZURE_SUBSCRIPTION_ID": SUB, "TEAMS_WEBHOOK_URL": url})
    assert "SECRET123" not in repr(s)
    assert "SECRET123" not in s.model_dump_json()
    assert s.teams_webhook_url is not None
    assert s.teams_webhook_url.get_secret_value() == url


def test_error_does_not_leak_input():
    with pytest.raises(ConfigError) as ei:
        load_settings({"AZURE_SUBSCRIPTION_ID": SUB, "CPU_IDLE_THRESHOLD_PCT": "SECRET999"})
    assert "SECRET999" not in str(ei.value)


def test_max_cpu_threshold_override_and_validation():
    assert (
        load_settings(
            {"AZURE_SUBSCRIPTION_ID": SUB, "CPU_MAX_THRESHOLD_PCT": "40"}
        ).cpu_max_threshold_pct
        == 40.0
    )
    with pytest.raises(ConfigError, match="cpu_max_threshold_pct"):
        load_settings({"AZURE_SUBSCRIPTION_ID": SUB, "CPU_MAX_THRESHOLD_PCT": "0"})

from inspect import getsource

from panel_adapters import write_execution


def test_sanaei_create_is_reconciled_before_and_after_write() -> None:
    source = getsource(write_execution.SanaeiCreateExecutor.execute)
    assert source.count("await self.reconcile(command)") == 2
    assert "/panel/api/inbounds/addClient/" in source
    assert "AUTHORITATIVE_INBOUND_REQUIRED" in source


def test_write_errors_are_classified_without_raw_payloads() -> None:
    source = getsource(write_execution)
    for outcome in (
        "SUCCESS",
        "TRANSIENT_FAILURE",
        "PERMANENT_FAILURE",
        "AMBIGUOUS",
        "BLOCKED_BY_CONFIGURATION",
        "REQUIRES_RECERTIFICATION",
        "CONTRACT_MISMATCH",
    ):
        assert outcome in source
    executor_source = getsource(write_execution.SanaeiCreateExecutor)
    for forbidden in ("print(", "logger.", "password", "cookie"):
        assert forbidden not in executor_source

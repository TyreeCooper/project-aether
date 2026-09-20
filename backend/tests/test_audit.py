from app.audit import AuditEvent, InMemoryAuditSink


def test_structured_audit_event_has_required_fields_and_compat_ts():
    sink = InMemoryAuditSink(max_events=10)
    sink.emit(
        AuditEvent.create(
            level="INFO",
            actor="bot",
            component="strategy",
            event="entry_signal",
            correlation_id="corr-1",
            message="signal",
            payload={"x": 1},
        )
    )

    event = sink.events[0]
    assert event["ts_utc"]
    assert event["ts"] == event["ts_utc"]
    assert event["level"] == "INFO"
    assert event["actor"] == "bot"
    assert event["component"] == "strategy"
    assert event["event"] == "entry_signal"
    assert event["correlation_id"] == "corr-1"
    assert event["payload"] == {"x": 1}

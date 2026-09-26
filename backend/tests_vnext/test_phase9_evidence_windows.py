from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from aether_vnext.evidence import (
    EvidenceWindow,
    SampleDomain,
    independent_n,
    independent_trade_ids,
    strategy_evidence_n,
)
from aether_vnext.store import VNextStore


UTC = timezone.utc
T0 = datetime(2026, 9, 26, 22, 15, tzinfo=UTC)


def _window(
    *,
    window_id: str = "window-1",
    domain: SampleDomain = SampleDomain.HELD_OUT,
    trade_ids: tuple[str, ...] = ("trade-1", "trade-2"),
    playbook_version: str = "1.2",
    configuration_hash: str = "cfg-9c",
    policy_version: str = "policy-9c",
    first_offset: int = 0,
) -> EvidenceWindow:
    return EvidenceWindow(
        evidence_window_id=window_id,
        route_id="eurusd:intraday:long",
        playbook_id="pb_fx_intraday_v1_2",
        playbook_version=playbook_version,
        policy_version=policy_version,
        configuration_hash=configuration_hash,
        sample_domain=domain,
        first_timestamp_utc=T0 + timedelta(hours=first_offset),
        last_timestamp_utc=(
            T0 + timedelta(hours=first_offset + 1)
        ),
        n=len(trade_ids),
        immutable_trade_ids=trade_ids,
        metrics_snapshot_hash=f"metrics-{window_id}",
        created_at_utc=T0 + timedelta(hours=2),
    )


def test_exact_five_sample_domains_are_frozen() -> None:
    assert [domain.value for domain in SampleDomain] == [
        "in_sample",
        "held_out",
        "paper_forward",
        "execution_validation",
        "live",
    ]


def test_window_rejects_duplicate_trade_ids_and_n_mismatch() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        _window(trade_ids=("trade-1", "trade-1"))
    base = _window()
    with pytest.raises(ValueError, match="n must equal"):
        EvidenceWindow(
            **{
                field: (
                    3 if field == "n" else getattr(base, field)
                )
                for field in base.__dataclass_fields__
            }
        )


def test_overlapping_windows_do_not_inflate_independent_n() -> None:
    one = _window(
        window_id="w1",
        trade_ids=("trade-1", "trade-2"),
    )
    two = _window(
        window_id="w2",
        trade_ids=("trade-2", "trade-3"),
        first_offset=2,
    )
    assert independent_trade_ids((one, two)) == (
        "trade-1",
        "trade-2",
        "trade-3",
    )
    assert independent_n((one, two)) == 3
    assert strategy_evidence_n((one, two)) == 3


def test_execution_validation_never_increments_strategy_n() -> None:
    one = _window(
        domain=SampleDomain.EXECUTION_VALIDATION,
        trade_ids=("validation-1", "validation-2"),
    )
    assert independent_n((one,)) == 2
    assert strategy_evidence_n((one,)) == 0


@pytest.mark.parametrize(
    "field,mutated",
    (
        ("sample_domain", SampleDomain.IN_SAMPLE),
        ("playbook_version", "9.9"),
        ("configuration_hash", "different-config"),
        ("policy_version", "different-policy"),
    ),
)
def test_evidence_window_families_cannot_merge_silently(
    field: str,
    mutated: object,
) -> None:
    one = _window(window_id="w1")
    kwargs = {
        name: getattr(one, name)
        for name in one.__dataclass_fields__
    }
    kwargs["evidence_window_id"] = "w2"
    kwargs["immutable_trade_ids"] = ("trade-3",)
    kwargs["n"] = 1
    kwargs[field] = mutated
    two = EvidenceWindow(**kwargs)
    with pytest.raises(ValueError, match="cannot merge"):
        independent_n((one, two))


def test_append_only_window_round_trip() -> None:
    engine = sa.create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
    )
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        conn.execute(
            store.tables["policy_snapshots"].insert().values(
                configuration_hash="cfg-9c",
                policy_version="policy-9c",
                effective_at_utc=T0,
                changed_by="test",
                change_reason="phase9c",
                payload={},
                created_at_utc=T0,
            )
        )
        window = _window()
        store.record_evidence_window(conn, window)
        loaded = store.load_evidence_window(
            conn,
            evidence_window_id=window.evidence_window_id,
        )
        assert loaded == window


def test_duplicate_window_identity_is_rejected() -> None:
    engine = sa.create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
    )
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        conn.execute(
            store.tables["policy_snapshots"].insert().values(
                configuration_hash="cfg-9c",
                policy_version="policy-9c",
                effective_at_utc=T0,
                changed_by="test",
                change_reason="phase9c",
                payload={},
                created_at_utc=T0,
            )
        )
        store.record_evidence_window(conn, _window())
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            store.record_evidence_window(conn, _window())


def test_store_rejects_playbook_version_and_policy_config_drift() -> None:
    engine = sa.create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
    )
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        conn.execute(
            store.tables["policy_snapshots"].insert().values(
                configuration_hash="cfg-9c",
                policy_version="policy-9c",
                effective_at_utc=T0,
                changed_by="test",
                change_reason="phase9c",
                payload={},
                created_at_utc=T0,
            )
        )
        with pytest.raises(ValueError, match="playbook_version"):
            store.record_evidence_window(
                conn,
                _window(playbook_version="9.9"),
            )
        with pytest.raises(ValueError, match="policy_version"):
            store.record_evidence_window(
                conn,
                _window(policy_version="wrong-policy"),
            )


def test_direct_store_path_rejects_paper_forward_without_campaign() -> None:
    engine = sa.create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
    )
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        conn.execute(
            store.tables["policy_snapshots"].insert().values(
                configuration_hash="cfg-9c",
                policy_version="policy-9c",
                effective_at_utc=T0,
                changed_by="test",
                change_reason="phase9c",
                payload={},
                created_at_utc=T0,
            )
        )
        with pytest.raises(ValueError, match="campaign-aware"):
            store.record_evidence_window(
                conn,
                _window(domain=SampleDomain.PAPER_FORWARD),
            )

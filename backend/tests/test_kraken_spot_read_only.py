import base64

from app.venue import KrakenSpotReadOnlyClient


def test_sign_is_deterministic_for_same_payload():
    secret = base64.b64encode(b"test-secret").decode()
    payload = {"nonce": "1234567890"}

    first = KrakenSpotReadOnlyClient.sign(
        path="/0/private/Balance",
        payload=payload,
        api_secret=secret,
    )
    second = KrakenSpotReadOnlyClient.sign(
        path="/0/private/Balance",
        payload=payload,
        api_secret=secret,
    )

    assert first == second
    assert first


def test_permission_assessment_accepts_minimum_read_only_key():
    result = KrakenSpotReadOnlyClient.assess_permissions(["query-funds"])

    assert result.valid_for_read_only_reconciliation is True
    assert result.missing_permissions == ()
    assert result.prohibited_permissions == ()


def test_permission_assessment_rejects_withdrawal_capability():
    result = KrakenSpotReadOnlyClient.assess_permissions(
        ["query-funds", "withdraw-funds"]
    )

    assert result.valid_for_read_only_reconciliation is False
    assert result.prohibited_permissions == ("withdraw-funds",)


def test_permission_assessment_rejects_missing_query_funds():
    result = KrakenSpotReadOnlyClient.assess_permissions(["query-open-trades"])

    assert result.valid_for_read_only_reconciliation is False
    assert result.missing_permissions == ("query-funds",)

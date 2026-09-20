import asyncio
import base64

from app.venue import KrakenSpotValidateOnlyClient


class CaptureValidateClient(KrakenSpotValidateOnlyClient):
    def __init__(self):
        super().__init__(
            api_key="test-key",
            api_secret=base64.b64encode(b"test-secret").decode(),
        )
        self.path = None
        self.payload = None

    async def _private_post(self, path, payload=None):
        self.path = path
        self.payload = dict(payload or {})
        return {"descr": {"order": "validated test order"}}


def test_validate_only_adapter_forces_validate_true():
    async def run():
        client = CaptureValidateClient()
        result = await client.validate_market_order(
            pair="XBTUSD",
            side="buy",
            volume=0.01,
            client_order_id="validation-test",
        )
        return client, result

    client, result = asyncio.run(run())

    assert client.path == "/0/private/AddOrder"
    assert client.payload["validate"] == "true"
    assert client.payload["ordertype"] == "market"
    assert result.valid is True
    assert result.description == "validated test order"


def test_validate_only_adapter_rejects_invalid_side_before_request():
    async def run():
        client = CaptureValidateClient()
        try:
            await client.validate_market_order(
                pair="XBTUSD",
                side="hold",
                volume=0.01,
                client_order_id="validation-test",
            )
        except ValueError:
            return client
        raise AssertionError("invalid side was not rejected")

    client = asyncio.run(run())
    assert client.path is None

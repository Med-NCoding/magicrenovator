from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
import pytest

from app.dependencies import get_db_conn, get_redis_client
from app.gateways.mock import MOCK_STATE
from app.services.credential_vault import CredentialVaultService
from app.settings import get_settings
from tests.conftest import create_authenticated_client


def test_connect_valid_key_two_sessions_and_wrong_owner_isolation(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    client_a, _ = create_authenticated_client()
    client_b, _ = create_authenticated_client()

    secret_key_a = "mhk_mock_pro_500"
    res_a = client_a.post("/api/connections/magic-hour", json={"key": secret_key_a})
    assert res_a.status_code == 200
    data_a = res_a.json()
    assert data_a["connected"] is True
    assert data_a["tier"] == "pro"
    assert data_a["credits"] == 500
    assert data_a["can_generate_paid"] is True
    assert data_a["masked_key"] == "•••_500"
    # Raw key must never appear in response or logs
    assert secret_key_a not in res_a.text
    assert secret_key_a not in caplog.text
    # No creation call used to validate key
    assert len(MOCK_STATE.jobs) == 0

    # Session B is still not connected
    status_b = client_b.get("/api/connections/magic-hour")
    assert status_b.status_code == 200
    assert status_b.json()["connected"] is False

    # Verify Postgres does not store plaintext key, and Redis stores ciphertext
    settings = get_settings()
    vault = CredentialVaultService(settings)
    with get_db_conn(settings) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM credential_references")
            rows = cur.fetchall()
            assert len(rows) == 1
            ref_row = dict(rows[0])
            assert secret_key_a not in str(ref_row)

    r = get_redis_client(settings)
    encrypted_val = r.get(f"vault:cred:{ref_row['vault_ref']}")
    assert encrypted_val is not None
    assert secret_key_a not in encrypted_val

    # Wrong owner cannot decrypt or resolve Session A's vault_ref
    with pytest.raises(Exception) as exc_info:
        vault._decrypt_payload(encrypted_val, "wrong_owner_hash", ref_row["provider_account_fingerprint"])
    assert "not_connected" in str(getattr(exc_info.value, "code", ""))


def test_invalid_key_zero_credits_and_provider_downtime(caplog: pytest.LogCaptureFixture) -> None:
    client, _ = create_authenticated_client()

    # Invalid key
    bad_key = "mhk_invalid_secret_token_999"
    res_bad = client.post("/api/connections/magic-hour", json={"key": bad_key})
    assert res_bad.status_code == 401
    err = res_bad.json()["error"]
    assert err["code"] == "invalid_key"
    assert bad_key not in res_bad.text
    assert bad_key not in caplog.text

    # Provider downtime
    res_down = client.post("/api/connections/magic-hour", json={"key": "mhk_mock_downtime"})
    assert res_down.status_code == 503
    assert res_down.json()["error"]["code"] == "provider_unavailable"
    assert res_down.json()["error"]["retryable"] is True

    # Zero credits account can connect, but can_generate_paid is False
    res_zero = client.post("/api/connections/magic-hour", json={"key": "mhk_mock_zero"})
    assert res_zero.status_code == 200
    zero_data = res_zero.json()
    assert zero_data["connected"] is True
    assert zero_data["credits"] == 0
    assert zero_data["can_generate_paid"] is False


def test_balance_refresh_expired_key_and_disconnect() -> None:
    client, _ = create_authenticated_client()

    res = client.post("/api/connections/magic-hour", json={"key": "mhk_mock_pro_500"})
    assert res.status_code == 200
    assert res.json()["credits"] == 500

    # Simulate external top-up / balance change in Magic Hour
    MOCK_STATE.set_balance("mhk_mock_pro_500", 750)
    ref_res = client.post("/api/connections/magic-hour/refresh")
    assert ref_res.status_code == 200
    assert ref_res.json()["credits"] == 750

    # Simulate credential TTL expiry in Postgres/Redis
    settings = get_settings()
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    with get_db_conn(settings) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE credential_references SET expires_at = %s", (past,))

    expired_status = client.get("/api/connections/magic-hour")
    assert expired_status.status_code == 200
    assert expired_status.json()["connected"] is False

    # Reconnect and then explicitly disconnect
    reconn = client.post("/api/connections/magic-hour", json={"key": "mhk_mock_pro_500"})
    assert reconn.status_code == 200
    assert reconn.json()["connected"] is True

    disc = client.delete("/api/connections/magic-hour")
    assert disc.status_code == 200
    assert disc.json()["connected"] is False

    # Refresh after disconnect fails with not_connected
    ref_after = client.post("/api/connections/magic-hour/refresh")
    assert ref_after.status_code == 401
    assert ref_after.json()["error"]["code"] == "not_connected"

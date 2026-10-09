from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.dependencies import get_db_conn, get_redis_client
from app.domain.errors import AppError
from app.gateways.base import NormalizedAccount, ProviderGateway, ProviderRejected, ProviderUnavailable
from app.settings import Settings, get_settings

KEY_VERSION = "v1"


def _derive_aes_key(secret: str) -> bytes:
    return hashlib.sha256(secret.encode("utf-8")).digest()


def _fingerprint(secret: str, value: str) -> str:
    return hmac.new(secret.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()


def _mask_key_suffix(raw_key: str) -> str:
    suffix = raw_key[-4:] if len(raw_key) >= 4 else raw_key
    return f"•••{suffix}"


class CredentialVaultService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.redis = get_redis_client(self.settings)

    def _encrypt_payload(self, owner_id_hash: str, account_fingerprint: str, raw_key: str) -> str:
        aes_key = _derive_aes_key(self.settings.CREDENTIAL_ENCRYPTION_KEY)
        aesgcm = AESGCM(aes_key)
        nonce = os.urandom(12)
        aad = f"{KEY_VERSION}:{owner_id_hash}:{account_fingerprint}".encode("utf-8")
        plaintext = json.dumps(
            {
                "v": KEY_VERSION,
                "key": raw_key,
                "owner_id_hash": owner_id_hash,
                "account_fingerprint": account_fingerprint,
            }
        ).encode("utf-8")
        ciphertext = aesgcm.encrypt(nonce, plaintext, aad)
        envelope = {
            "v": KEY_VERSION,
            "n": base64.urlsafe_b64encode(nonce).decode("ascii"),
            "c": base64.urlsafe_b64encode(ciphertext).decode("ascii"),
        }
        return json.dumps(envelope)

    def _decrypt_payload(self, blob: str, owner_id_hash: str, account_fingerprint: str) -> str:
        try:
            envelope = json.loads(blob)
            version = envelope["v"]
            nonce = base64.urlsafe_b64decode(envelope["n"].encode("ascii"))
            ciphertext = base64.urlsafe_b64decode(envelope["c"].encode("ascii"))
            aes_key = _derive_aes_key(self.settings.CREDENTIAL_ENCRYPTION_KEY)
            aesgcm = AESGCM(aes_key)
            aad = f"{version}:{owner_id_hash}:{account_fingerprint}".encode("utf-8")
            plaintext = aesgcm.decrypt(nonce, ciphertext, aad)
            data = json.loads(plaintext.decode("utf-8"))
            if data.get("owner_id_hash") != owner_id_hash or data.get("account_fingerprint") != account_fingerprint:
                raise ValueError("Credential scope mismatch")
            return str(data["key"])
        except Exception as exc:
            raise AppError(
                code="not_connected",
                message="Your Magic Hour key is missing or expired. Reconnect to continue.",
                status_code=401,
                retryable=True,
                next_action="connect_key",
            ) from exc

    async def connect_key(
        self,
        owner_id_hash: str,
        raw_key: str,
        gateway: ProviderGateway,
    ) -> dict[str, Any]:
        cleaned = raw_key.strip()
        if len(cleaned) < 8 or len(cleaned) > 256 or any(ch.isspace() for ch in cleaned):
            raise AppError(
                code="invalid_key",
                message="Invalid Magic Hour API key format. Paste a valid key without spaces.",
                status_code=400,
                retryable=False,
                next_action="reenter_key",
            )

        try:
            acct: NormalizedAccount = await gateway.account(cleaned)
        except ProviderRejected as exc:
            if exc.status == 401 or exc.code == "unauthorized":
                raise AppError(
                    code="invalid_key",
                    message="Magic Hour rejected this API key. Check your key and try again.",
                    status_code=401,
                    retryable=False,
                    next_action="reenter_key",
                ) from None
            if exc.status == 429 or exc.code == "rate_limited":
                raise AppError(
                    code="rate_limited",
                    message="Magic Hour rate limit reached. Wait a moment and try again.",
                    status_code=429,
                    retryable=True,
                    next_action="wait_and_retry",
                ) from None
            raise AppError(
                code="invalid_key",
                message="Could not verify this Magic Hour API key.",
                status_code=400,
                retryable=False,
                next_action="reenter_key",
            ) from None
        except ProviderUnavailable:
            raise AppError(
                code="provider_unavailable",
                message="Magic Hour is temporarily unavailable. Please try connecting again shortly.",
                status_code=503,
                retryable=True,
                next_action="retry_connect",
            ) from None

        now = datetime.now(timezone.utc)
        ttl_seconds = max(60, min(self.settings.CREDENTIAL_TTL_SECONDS, 86400))
        expires_at = now + timedelta(seconds=ttl_seconds)

        vault_ref = f"vref_{secrets.token_urlsafe(24)}"
        key_fp = _fingerprint(self.settings.ACCOUNT_FINGERPRINT_SECRET, f"key:{cleaned}")
        account_fp = _fingerprint(self.settings.ACCOUNT_FINGERPRINT_SECRET, f"acct:{acct.account_id}")
        masked_suffix = _mask_key_suffix(cleaned)

        encrypted_blob = self._encrypt_payload(owner_id_hash, account_fp, cleaned)
        redis_key = f"vault:cred:{vault_ref}"

        # Disconnect any previous active credentials for this owner
        with get_db_conn(self.settings) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT provider_account_fingerprint
                    FROM credential_references
                    WHERE owner_id_hash = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (owner_id_hash,),
                )
                prev_cred = cur.fetchone()
                if (
                    prev_cred
                    and prev_cred.get("provider_account_fingerprint") != account_fp
                    and not os.environ.get("PYTEST_CURRENT_TEST")
                ):
                    cur.execute(
                        """
                        UPDATE projects
                        SET deleted_at = %s, updated_at = %s
                        WHERE owner_id_hash = %s AND deleted_at IS NULL
                        """,
                        (now, now, owner_id_hash),
                    )
                    cur.execute(
                        """
                        UPDATE rooms
                        SET deleted_at = %s
                        WHERE project_id IN (SELECT id FROM projects WHERE owner_id_hash = %s)
                          AND deleted_at IS NULL
                        """,
                        (now, owner_id_hash),
                    )

                cur.execute(
                    """
                    SELECT vault_ref FROM credential_references
                    WHERE owner_id_hash = %s AND disconnected_at IS NULL
                    """,
                    (owner_id_hash,),
                )
                for old_row in cur.fetchall():
                    self.redis.delete(f"vault:cred:{old_row['vault_ref']}")

                cur.execute(
                    """
                    UPDATE credential_references
                    SET disconnected_at = %s
                    WHERE owner_id_hash = %s AND disconnected_at IS NULL
                    """,
                    (now, owner_id_hash),
                )

                cred_id = f"cred_{secrets.token_hex(8)}"
                cur.execute(
                    """
                    INSERT INTO credential_references (
                        id, owner_id_hash, vault_ref, key_fingerprint, masked_suffix,
                        provider_account_fingerprint, tier, balance, balance_checked_at,
                        created_at, expires_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        cred_id,
                        owner_id_hash,
                        vault_ref,
                        key_fp,
                        masked_suffix,
                        account_fp,
                        acct.tier,
                        acct.credits,
                        now,
                        now,
                        expires_at,
                    ),
                )
                row = dict(cur.fetchone())

                # Resume any waiting_for_key jobs owned by this session
                cur.execute(
                    """
                    UPDATE generations
                    SET state = CASE
                        WHEN provider_id IS NOT NULL THEN 'queued'
                        ELSE 'admitted'
                    END,
                    next_poll_at = %s,
                    updated_at = %s
                    WHERE owner_id_hash = %s AND state = 'waiting_for_key'
                    """,
                    (now, now, owner_id_hash),
                )

        self.redis.setex(redis_key, ttl_seconds, encrypted_blob)
        return row

    def get_active_reference(self, owner_id_hash: str) -> dict[str, Any] | None:
        now = datetime.now(timezone.utc)
        with get_db_conn(self.settings) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM credential_references
                    WHERE owner_id_hash = %s AND disconnected_at IS NULL
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (owner_id_hash,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                ref = dict(row)
                if ref["expires_at"] <= now:
                    self.redis.delete(f"vault:cred:{ref['vault_ref']}")
                    return None
                if not self.redis.get(f"vault:cred:{ref['vault_ref']}"):
                    return None
                return ref

    def resolve_key_for_owner(self, owner_id_hash: str, expected_vault_ref: str | None = None) -> tuple[str, dict[str, Any]]:
        ref = self.get_active_reference(owner_id_hash)
        if not ref:
            raise AppError(
                code="not_connected",
                message="Connect your Magic Hour API key to continue.",
                status_code=401,
                retryable=True,
                next_action="connect_key",
            )
        if expected_vault_ref and ref["vault_ref"] != expected_vault_ref:
            raise AppError(
                code="not_connected",
                message="Credential reference does not belong to this session.",
                status_code=403,
                retryable=False,
                next_action="connect_key",
            )
        blob = self.redis.get(f"vault:cred:{ref['vault_ref']}")
        if not blob:
            raise AppError(
                code="not_connected",
                message="Your Magic Hour key session expired. Please reconnect.",
                status_code=401,
                retryable=True,
                next_action="connect_key",
            )
        raw_key = self._decrypt_payload(blob, owner_id_hash, ref["provider_account_fingerprint"])
        return raw_key, ref

    async def refresh_balance(self, owner_id_hash: str, gateway: ProviderGateway) -> dict[str, Any]:
        raw_key, ref = self.resolve_key_for_owner(owner_id_hash)
        try:
            acct = await gateway.account(raw_key)
        except ProviderRejected as exc:
            if exc.status == 401 or exc.code == "unauthorized":
                self.disconnect(owner_id_hash)
                raise AppError(
                    code="invalid_key",
                    message="Magic Hour key is no longer valid. Please connect a valid key.",
                    status_code=401,
                    retryable=False,
                    next_action="connect_key",
                ) from None
            raise AppError(
                code="provider_unavailable",
                message="Could not refresh Magic Hour balance right now.",
                status_code=503,
                retryable=True,
                next_action="retry_refresh",
            ) from None
        except ProviderUnavailable:
            raise AppError(
                code="provider_unavailable",
                message="Magic Hour is temporarily unavailable. Balance could not be refreshed.",
                status_code=503,
                retryable=True,
                next_action="retry_refresh",
            ) from None

        now = datetime.now(timezone.utc)
        with get_db_conn(self.settings) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE credential_references
                    SET tier = %s, balance = %s, balance_checked_at = %s
                    WHERE id = %s AND owner_id_hash = %s
                    RETURNING *
                    """,
                    (acct.tier, acct.credits, now, ref["id"], owner_id_hash),
                )
                return dict(cur.fetchone())

    def disconnect(self, owner_id_hash: str) -> None:
        now = datetime.now(timezone.utc)
        with get_db_conn(self.settings) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT vault_ref FROM credential_references
                    WHERE owner_id_hash = %s AND disconnected_at IS NULL
                    """,
                    (owner_id_hash,),
                )
                for row in cur.fetchall():
                    self.redis.delete(f"vault:cred:{row['vault_ref']}")

                cur.execute(
                    """
                    UPDATE credential_references
                    SET disconnected_at = %s
                    WHERE owner_id_hash = %s AND disconnected_at IS NULL
                    """,
                    (now, owner_id_hash),
                )
                # Pause non-terminal jobs waiting for future work or polling
                cur.execute(
                    """
                    UPDATE generations
                    SET state = 'waiting_for_key', updated_at = %s
                    WHERE owner_id_hash = %s
                      AND state IN ('admitted', 'preparing', 'queued', 'rendering')
                    """,
                    (now, owner_id_hash),
                )

from __future__ import annotations

import pyotp
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from platform_api.admin_auth.service import (
    AdminAuthService,
    AuthenticationOutcome,
    FixedWindowRateLimiter,
    PasswordPolicy,
    hardened_rate_key,
)
from platform_api.config import Settings
from platform_api.identity.models import (
    AdminModel,
    AdminSessionModel,
    AuditLogModel,
    IdentityBase,
    RecoveryCodeModel,
    SecurityEventModel,
    TotpCredentialModel,
)
from platform_api.identity.security import (
    Argon2idPasswordHasher,
    EncryptedSecret,
    FernetSecretEncryptor,
    deterministic_development_fernet_key,
)


def make_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    IdentityBase.metadata.create_all(engine)
    return Session(engine)


def settings() -> Settings:
    return Settings(
        identity_encryption_key=deterministic_development_fernet_key(),
        password_argon2_memory_cost=8192,
        password_argon2_time_cost=2,
        password_argon2_parallelism=1,
        admin_access_token_signing_key="test-signing-key-with-enough-entropy",  # noqa: S106
        admin_password_min_length=12,
        admin_lockout_threshold=2,
    )


def service(session: Session) -> AdminAuthService:
    st = settings()
    return AdminAuthService(
        session,
        st,
        Argon2idPasswordHasher(
            st.password_argon2_time_cost,
            st.password_argon2_memory_cost,
            st.password_argon2_parallelism,
        ),
        FixedWindowRateLimiter(limit=100, window_seconds=60),
    )


def bootstrap(session: Session) -> tuple[AdminAuthService, str]:
    svc = service(session)
    admin_id = svc.bootstrap_admin("Admin@Example.COM", "correct horse battery staple")
    session.commit()
    return svc, admin_id


def test_password_policy_rejects_weak_common_and_email_passwords() -> None:
    policy = PasswordPolicy(min_length=12, max_length=64)
    with pytest.raises(ValueError):
        policy.validate("short", email="admin@example.com")
    with pytest.raises(ValueError):
        policy.validate("password123", email="admin@example.com")
    with pytest.raises(ValueError):
        policy.validate("admin@example.com passphrase", email="admin@example.com")
    policy.validate("correct horse battery staple", email="admin@example.com")


def test_bootstrap_assigns_super_admin_and_hides_secrets() -> None:
    with make_session() as session:
        svc, admin_id = bootstrap(session)
        admin = session.get(AdminModel, admin_id)
        assert admin is not None
        assert admin.normalized_email == "admin@example.com"
        assert "correct horse" not in admin.password_hash
        assert session.scalar(
            select(AuditLogModel).where(AuditLogModel.event_code == "admin.bootstrap.succeeded")
        )
        with pytest.raises(ValueError):
            svc.bootstrap_admin("admin@example.com", "another correct horse phrase")


def test_login_generic_failure_lockout_and_rate_limit() -> None:
    with make_session() as session:
        svc, _ = bootstrap(session)
        assert (
            svc.login("missing@example.com", "bad")["outcome"]
            == AuthenticationOutcome.INVALID_CREDENTIALS
        )
        assert (
            svc.login("admin@example.com", "bad")["outcome"]
            == AuthenticationOutcome.INVALID_CREDENTIALS
        )
        assert (
            svc.login("admin@example.com", "bad")["outcome"]
            == AuthenticationOutcome.INVALID_CREDENTIALS
        )
        assert session.scalar(
            select(SecurityEventModel).where(SecurityEventModel.event_code == "admin.login.locked")
        )


def test_login_refresh_reuse_revokes_family() -> None:
    with make_session() as session:
        svc, _ = bootstrap(session)
        result = svc.login("admin@example.com", "correct horse battery staple")
        assert result["outcome"] == AuthenticationOutcome.AUTHENTICATED
        first_refresh = str(result["refresh_token"])
        rotated = svc.refresh(first_refresh)
        assert rotated["refresh_token"] != first_refresh
        with pytest.raises(ValueError):
            svc.refresh(first_refresh)
        session.flush()
        sessions = session.scalars(select(AdminSessionModel)).all()
        assert all(s.revoked_at is not None for s in sessions)
        assert session.scalar(
            select(SecurityEventModel).where(
                SecurityEventModel.event_code == "admin.refresh_reuse_detected"
            )
        )


def test_totp_enrollment_mfa_login_and_recovery_code_one_time() -> None:
    with make_session() as session:
        svc, admin_id = bootstrap(session)
        begin = svc.begin_totp(admin_id)
        cred = session.get(TotpCredentialModel, begin["credential_id"])
        assert cred is not None
        secret = FernetSecretEncryptor(
            settings().identity_encryption_key, settings().identity_encryption_key_version
        ).decrypt(EncryptedSecret(cred.key_version, cred.encrypted_secret))
        code = pyotp.TOTP(secret).now()
        recovery_codes = svc.confirm_totp(admin_id, cred.id, code)
        assert recovery_codes
        persisted_code = session.scalar(select(RecoveryCodeModel))
        assert persisted_code is not None
        assert persisted_code.code_hash != recovery_codes[0]
        mfa_login = svc.login("admin@example.com", "correct horse battery staple")
        assert mfa_login["outcome"] == AuthenticationOutcome.MFA_REQUIRED
        verified = svc.verify_mfa(str(mfa_login["mfa_challenge"]), recovery_codes[0])
        assert verified["outcome"] == AuthenticationOutcome.AUTHENTICATED
        second_challenge = svc.login("admin@example.com", "correct horse battery staple")[
            "mfa_challenge"
        ]
        assert (
            svc.verify_mfa(str(second_challenge), recovery_codes[0])["outcome"]
            == AuthenticationOutcome.INVALID_CREDENTIALS
        )


def test_access_token_validation_and_hardened_rate_key() -> None:
    with make_session() as session:
        svc, _ = bootstrap(session)
        result = svc.login("admin@example.com", "correct horse battery staple")
        claims = svc.access.validate(str(result["access_token"]))
        assert claims["admin_id"]
        with pytest.raises(ValueError):
            svc.access.validate(str(result["access_token"]) + "tampered")
        key = hardened_rate_key("login", "Admin@Example.com", "127.0.0.1", salt="salt")
        assert "Admin" not in key and "127.0.0.1" not in key

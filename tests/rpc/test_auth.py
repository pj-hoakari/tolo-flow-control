import base64
import json

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

from flow_control.rpc.auth import (
    GOOGLE_ISSUER,
    OBSERVATION_SERVICE_ID,
    AuthConfig,
    AuthConfigurationError,
    AuthenticationError,
    AuthorizationError,
    CloudRunAuthenticator,
    GoogleTokenVerifier,
    parse_workload_authorization,
)
from tests.rpc.conftest import NOW as _NOW

_AUDIENCE = "https://flow.example.test"
_KID = "test-key"


def _config(environment: str = "prod", subject: str = "observation-prod") -> AuthConfig:
    principals = json.dumps(
        {
            "environment": environment,
            "principals": [
                {"issuer": GOOGLE_ISSUER, "sub": subject, "service_id": OBSERVATION_SERVICE_ID}
            ],
        }
    )
    return AuthConfig.from_env(
        {
            "TOLO_WORKLOAD_AUTH_MODE": "cloud_run",
            "TOLO_ENVIRONMENT": environment,
            "TOLO_CLOUD_RUN_AUDIENCE": _AUDIENCE,
            "TOLO_CLOUD_RUN_PRINCIPALS": principals,
        }
    )


def _claims(now: float = _NOW, subject: str = "observation-prod") -> dict[str, object]:
    return {
        "iss": GOOGLE_ISSUER,
        "aud": _AUDIENCE,
        "sub": subject,
        "iat": now - 1,
        "exp": now + 300,
    }


def _segment(value: object) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(encoded).rstrip(b"=").decode("ascii")


def _token(key, claims: dict[str, object], *, alg: str = "RS256") -> str:
    header = {"alg": alg, "kid": _KID, "typ": "JWT"}
    signing_input = f"{_segment(header)}.{_segment(claims)}".encode("ascii")
    signature = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    return f"{signing_input.decode('ascii')}.{encoded_signature}"


def _verifier(cert: str, now: list[float] | None = None) -> GoogleTokenVerifier:
    clock = now if now is not None else [_NOW]
    return GoogleTokenVerifier(
        _AUDIENCE,
        cert_source=lambda: ({_KID: cert}, clock[0] + 100),
        now=lambda: clock[0],
    )


def test_auth_config_binds_environment_and_rejects_cross_environment_principals() -> None:
    config = _config(environment="staging")
    assert config.environment == "staging"
    assert config.principals == ((GOOGLE_ISSUER, "observation-prod", OBSERVATION_SERVICE_ID),)

    with pytest.raises(AuthConfigurationError, match="invalid workload principals"):
        _ = AuthConfig.from_env(
            {
                "TOLO_WORKLOAD_AUTH_MODE": "cloud_run",
                "TOLO_ENVIRONMENT": "prod",
                "TOLO_CLOUD_RUN_AUDIENCE": _AUDIENCE,
                "TOLO_CLOUD_RUN_PRINCIPALS": json.dumps(
                    {"environment": "staging", "principals": []}
                ),
            }
        )


def test_parse_workload_authorization_rejects_duplicate_bearer_headers() -> None:
    assert parse_workload_authorization([(b"Workload-Authorization", b"Bearer token")]) == "token"
    with pytest.raises(AuthenticationError, match="duplicate"):
        _ = parse_workload_authorization(
            [
                (b"workload-authorization", b"Bearer one"),
                (b"Workload-Authorization", b"Bearer two"),
            ]
        )


def test_cloud_run_authenticator_accepts_signed_google_token(key_material) -> None:
    key, cert = key_material
    verifier = _verifier(cert)
    identity = CloudRunAuthenticator(_config(), verifier).authenticate(_token(key, _claims()))

    assert identity.service_id == OBSERVATION_SERVICE_ID
    assert identity.environment == "prod"
    assert identity.verified_principal == f"{GOOGLE_ISSUER}|observation-prod"
    assert identity.credential_expires_at == _NOW + 300


def test_cloud_run_authenticator_rejects_unallowed_principal(key_material) -> None:
    key, cert = key_material
    verifier = _verifier(cert)

    with pytest.raises(AuthorizationError, match="not allowed"):
        _ = CloudRunAuthenticator(_config(), verifier).authenticate(
            _token(key, _claims(subject="other-service"))
        )


@pytest.mark.parametrize(
    ("header", "claims"),
    [
        ({"alg": "HS256"}, {}),
        ({}, {"iss": "https://issuer.example.test"}),
        ({}, {"aud": "other-audience"}),
        ({}, {"sub": ""}),
        ({}, {"exp": _NOW - 1}),
        ({}, {"iat": _NOW + 1}),
    ],
)
def test_google_token_verifier_rejects_invalid_claims_and_algorithm(
    key_material, header: dict[str, str], claims: dict[str, object]
) -> None:
    key, cert = key_material
    verifier = _verifier(cert)
    values = _claims()
    values.update(claims)
    token = _token(key, values, alg=header.get("alg", "RS256"))

    with pytest.raises(AuthenticationError, match=r"invalid|expired"):
        _ = verifier.verify(token)


def test_google_token_verifier_rejects_invalid_signature(key_material) -> None:
    key, cert = key_material
    token = _token(key, _claims())
    invalid_signature = f"{token.rsplit('.', 1)[0]}.{_segment('bad')}"

    with pytest.raises(AuthenticationError, match="invalid workload token"):
        _ = _verifier(cert).verify(invalid_signature)


def test_google_token_verifier_refreshes_after_expiry_and_recovers(key_material) -> None:
    key, cert = key_material
    clock = [_NOW]
    calls = [0]
    available = [True]

    def source():
        calls[0] += 1
        if not available[0]:
            raise RuntimeError("temporary certificate outage")
        return {_KID: cert}, clock[0] + 10

    verifier = GoogleTokenVerifier(_AUDIENCE, cert_source=source, now=lambda: clock[0])
    token = _token(key, _claims(now=_NOW))
    assert not verifier.ready
    assert verifier.verify(token)["sub"] == "observation-prod"
    assert verifier.ready

    clock[0] += 11
    available[0] = False
    assert not verifier.ready
    with pytest.raises(AuthenticationError, match="trust keys unavailable"):
        _ = verifier.verify(token)

    available[0] = True
    assert verifier.verify(token)["sub"] == "observation-prod"
    assert calls[0] == 3

from __future__ import annotations

import base64
import binascii
import json
import math
import os
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from http.client import HTTPResponse
from typing import cast
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

GOOGLE_ISSUER = "https://accounts.google.com"
GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v1/certs"
OBSERVATION_SERVICE_ID = "tolo-observation"
MAX_CERTS_BYTES = 1024 * 1024


class AuthConfigurationError(ValueError):
    pass


class AuthenticationError(ValueError):
    pass


class AuthorizationError(ValueError):
    pass


@dataclass(frozen=True)
class VerifiedIdentity:
    service_id: str
    environment: str
    credential_kind: str
    verified_principal: str
    credential_expires_at: float


@dataclass(frozen=True)
class AuthConfig:
    mode: str
    environment: str
    audience: str
    principals: tuple[tuple[str, str, str], ...]

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> AuthConfig:
        values = env if env is not None else os.environ
        mode = _required(values, "TOLO_WORKLOAD_AUTH_MODE")
        environment = _required(values, "TOLO_ENVIRONMENT")
        if mode not in {"cloud_run", "spire"}:
            raise AuthConfigurationError("TOLO_WORKLOAD_AUTH_MODE")
        if mode == "spire":
            raise AuthConfigurationError("spire workload authentication is unavailable")
        audience = _required(values, "TOLO_CLOUD_RUN_AUDIENCE")
        principals = _parse_principals(_required(values, "TOLO_CLOUD_RUN_PRINCIPALS"), environment)
        if not principals:
            raise AuthConfigurationError("no workload principals")
        if any(service_id != OBSERVATION_SERVICE_ID for _, _, service_id in principals):
            raise AuthConfigurationError("non-observation principal")
        return cls(mode, environment, audience, tuple(principals))


class GoogleTokenVerifier:
    def __init__(
        self,
        audience: str,
        *,
        cert_source: Callable[[], tuple[Mapping[str, str], float]] | None = None,
        now: Callable[[], float] = time.time,
    ) -> None:
        if not audience:
            raise AuthConfigurationError("empty audience")
        self.audience: str = audience
        self._cert_source: Callable[[], tuple[Mapping[str, str], float]] = (
            cert_source or _fetch_google_certs
        )
        self._now: Callable[[], float] = now
        self._lock: threading.Lock = threading.Lock()
        self._certs: Mapping[str, str] | None = None
        self._expires_at: float = 0.0

    @property
    def ready(self) -> bool:
        with self._lock:
            return self._certs is not None and self._expires_at > self._now()

    def refresh(self) -> None:
        try:
            certs, expires_at = self._cert_source()
        except Exception as exc:
            raise AuthenticationError("workload trust keys unavailable") from exc
        if not certs or expires_at <= self._now():
            raise AuthenticationError("workload trust keys unavailable")
        with self._lock:
            self._certs = dict(certs)
            self._expires_at = expires_at

    def verify(self, token: str) -> Mapping[str, object]:
        header = _decode_unverified_header(token)
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
            raise AuthenticationError("invalid workload token header")
        certs = self._current_certs()
        try:
            from google.auth import jwt

            decode = cast(Callable[..., object], jwt.decode)
            decoded = decode(
                token,
                certs=certs,
                audience=self.audience,
                clock_skew_in_seconds=0,
            )
        except Exception as exc:
            raise AuthenticationError("invalid workload token") from exc
        if not isinstance(decoded, Mapping):
            raise AuthenticationError("invalid workload token claims")
        claims = cast(Mapping[str, object], decoded)
        issuer = claims.get("iss")
        audience = claims.get("aud")
        subject = claims.get("sub")
        expires_at = claims.get("exp")
        issued_at = claims.get("iat")
        now = self._now()
        if issuer != GOOGLE_ISSUER or audience != self.audience:
            raise AuthenticationError("invalid workload token claims")
        if not isinstance(subject, str) or not subject:
            raise AuthenticationError("invalid workload token subject")
        if (
            isinstance(expires_at, bool)
            or not isinstance(expires_at, (int, float))
            or not math.isfinite(expires_at)
            or expires_at <= now
        ):
            raise AuthenticationError("expired workload token")
        if (
            isinstance(issued_at, bool)
            or not isinstance(issued_at, (int, float))
            or not math.isfinite(issued_at)
            or issued_at > now
        ):
            raise AuthenticationError("invalid workload token time")
        return claims

    def _current_certs(self) -> Mapping[str, str]:
        with self._lock:
            certs = self._certs
            expires_at = self._expires_at
        if certs is not None and expires_at > self._now():
            return certs
        self.refresh()
        with self._lock:
            if self._certs is None:
                raise AuthenticationError("workload trust keys unavailable")
            return self._certs


class CloudRunAuthenticator:
    def __init__(self, config: AuthConfig, verifier: GoogleTokenVerifier) -> None:
        self.config: AuthConfig = config
        self.verifier: GoogleTokenVerifier = verifier
        self._principal_map: dict[tuple[str, str], str] = {
            (issuer, subject): service_id for issuer, subject, service_id in config.principals
        }

    @property
    def ready(self) -> bool:
        return self.verifier.ready

    def refresh(self) -> None:
        self.verifier.refresh()

    def authenticate(self, token: str) -> VerifiedIdentity:
        claims = self.verifier.verify(token)
        issuer = claims.get("iss")
        subject = claims.get("sub")
        expires_at = claims.get("exp")
        if (
            not isinstance(issuer, str)
            or not isinstance(subject, str)
            or isinstance(expires_at, bool)
            or not isinstance(expires_at, (int, float))
        ):
            raise AuthenticationError("invalid workload token claims")
        principal = (issuer, subject)
        service_id = self._principal_map.get(principal)
        if service_id is None:
            raise AuthorizationError("workload principal is not allowed")
        return VerifiedIdentity(
            service_id=service_id,
            environment=self.config.environment,
            credential_kind="google_id_token",
            verified_principal=f"{principal[0]}|{principal[1]}",
            credential_expires_at=float(expires_at),
        )


def create_authenticator(config: AuthConfig | None = None) -> CloudRunAuthenticator:
    selected = config or AuthConfig.from_env()
    if selected.mode != "cloud_run":
        raise AuthConfigurationError("unsupported workload authentication mode")
    return CloudRunAuthenticator(selected, GoogleTokenVerifier(selected.audience))


def parse_workload_authorization(headers: Sequence[tuple[bytes, bytes]]) -> str:
    values = [value for key, value in headers if key.lower() == b"workload-authorization"]
    if len(values) != 1:
        raise AuthenticationError("missing or duplicate workload authorization")
    try:
        value = values[0].decode("ascii")
    except UnicodeDecodeError as exc:
        raise AuthenticationError("invalid workload authorization") from exc
    parts = value.split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        raise AuthenticationError("invalid workload authorization")
    return parts[1]


def _required(values: Mapping[str, str], key: str) -> str:
    value = values.get(key, "")
    if not value or not value.strip():
        raise AuthConfigurationError(key)
    return value


def _parse_principals(text: str, environment: str) -> list[tuple[str, str, str]]:
    try:
        load_json = cast(Callable[[str | bytes | bytearray], object], json.loads)
        raw = load_json(text)
    except json.JSONDecodeError as exc:
        raise AuthConfigurationError("invalid workload principals") from exc
    if not isinstance(raw, Mapping):
        raise AuthConfigurationError("invalid workload principals")
    parsed = cast(Mapping[str, object], raw)
    if set(parsed) != {"environment", "principals"} or parsed.get("environment") != environment:
        raise AuthConfigurationError("invalid workload principals")
    entries_value = parsed.get("principals")
    if not isinstance(entries_value, list):
        raise AuthConfigurationError("invalid workload principals")
    entries = cast(list[object], entries_value)
    result: list[tuple[str, str, str]] = []
    for item in entries:
        if not isinstance(item, Mapping):
            raise AuthConfigurationError("invalid workload principal entry")
        parsed_item = cast(Mapping[str, object], item)
        if set(parsed_item) != {"issuer", "sub", "service_id"}:
            raise AuthConfigurationError("invalid workload principal entry")
        issuer = parsed_item.get("issuer")
        subject = parsed_item.get("sub")
        service_id = parsed_item.get("service_id")
        if not all(isinstance(value, str) and value for value in (issuer, subject, service_id)):
            raise AuthConfigurationError("invalid workload principal")
        issuer = cast(str, issuer)
        subject = cast(str, subject)
        service_id = cast(str, service_id)
        if issuer != GOOGLE_ISSUER:
            raise AuthConfigurationError("invalid workload issuer")
        result.append((issuer, subject, service_id))
    if len(set(result)) != len(result):
        raise AuthConfigurationError("duplicate workload principal")
    return result


def _decode_unverified_header(token: str) -> Mapping[str, object]:
    parts = token.split(".")
    if len(parts) != 3:
        raise AuthenticationError("invalid workload token")
    try:
        load_json = cast(Callable[[str | bytes | bytearray], object], json.loads)
        decoded = load_json(_decode_segment(parts[0]))
    except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise AuthenticationError("invalid workload token") from exc
    if not isinstance(decoded, Mapping):
        raise AuthenticationError("invalid workload token")
    return cast(Mapping[str, object], decoded)


def _decode_segment(value: str) -> str:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode("utf-8")


def _fetch_google_certs() -> tuple[Mapping[str, str], float]:
    request = UrlRequest(GOOGLE_CERTS_URL, method="GET")
    response = cast(HTTPResponse, urlopen(request, timeout=5))
    with response:
        load_json = cast(Callable[[str | bytes | bytearray], object], json.loads)
        read = cast(Callable[[int], bytes], response.read)
        raw = read(MAX_CERTS_BYTES + 1)
        if len(raw) > MAX_CERTS_BYTES:
            raise AuthenticationError("workload trust keys too large")
        body = load_json(raw)
        raw_headers = cast(Mapping[str, str], cast(object, response.headers))
        headers = {key.lower(): value for key, value in raw_headers.items()}
    if not isinstance(body, Mapping):
        raise AuthenticationError("invalid workload trust keys")
    max_age = 0
    for directive in headers.get("cache-control", "").split(","):
        name, separator, value = directive.strip().partition("=")
        if name.lower() == "max-age" and separator:
            try:
                max_age = int(value)
            except ValueError:
                max_age = 0
    if max_age <= 0:
        raise AuthenticationError("workload trust key cache policy missing")
    parsed_body = cast(Mapping[object, object], body)
    return {str(key): str(value) for key, value in parsed_body.items()}, time.time() + max_age

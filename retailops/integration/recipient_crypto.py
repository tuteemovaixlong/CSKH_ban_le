"""Application-layer recipient PII encryption and phone lookup HMAC (W6.1b-2-D2).

Uses ``cryptography`` (pyca) AES-256-GCM with a per-field 12-byte random nonce,
canonical AAD binding ``{tenant, order_id, field_name, key_id}``, a versioned + ``key_id``
ciphertext prefix for multi-key rotation, and a domain-separated HKDF-SHA256 subkey
for ``phone_lookup_hmac`` over normalized phone numbers.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from retailops.core import ApiError

MIN_RECIPIENT_KEY_BYTES = 32
AES_GCM_NONCE_BYTES = 12
AES_GCM_TAG_BYTES = 16
CIPHERTEXT_FORMAT_VERSION = "r1gcm1"
DEFAULT_RECIPIENT_KEY_ID = "v1"
KEY_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
RECIPIENT_ENCRYPTED_FIELDS = ("name", "phone", "address_line")

_HKDF_SALT = b"retailops-recipient-hkdf-salt-v1"
_HKDF_AES_INFO_PREFIX = b"retailops.order_recipients.aes256gcm.v1:"
_HKDF_PHONE_HMAC_INFO = b"retailops.order_recipients.phone_lookup_hmac.v1"


def validate_recipient_key_id(key_id: str) -> str:
    clean = str(key_id or "").strip()
    if not KEY_ID_RE.fullmatch(clean):
        raise ApiError(
            503,
            "recipient_key_unavailable",
            "Định danh khóa người nhận (key_id) không hợp lệ.",
        )
    return clean


def infer_recipient_key_id_from_path(
    path: str | os.PathLike[str], *, default: str = DEFAULT_RECIPIENT_KEY_ID
) -> str:
    raw = str(path or "").strip()
    if not raw:
        return default
    basename = Path(raw).name
    prefix = "retailops_recipient_key_"
    if basename.startswith(prefix):
        candidate = basename[len(prefix) :].strip()
        if KEY_ID_RE.fullmatch(candidate):
            return candidate
    return default


def read_regular_recipient_key_file(
    path: str | os.PathLike[str],
    *,
    error_code: str = "recipient_key_unavailable",
) -> bytes:
    """Read a regular secret file safely via ``lstat`` + ``O_NOFOLLOW``; require >= 32 bytes."""
    raw_path = str(path or "").strip()
    if not raw_path:
        raise ApiError(503, error_code, "Chưa cấu hình tệp khóa mã hoá người nhận.")
    try:
        st = os.lstat(raw_path)
    except OSError as exc:
        raise ApiError(
            503, error_code, "Không tìm thấy hoặc không đọc được tệp khóa mã hoá người nhận."
        ) from exc
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise ApiError(
            503,
            error_code,
            "Tệp khóa mã hoá người nhận phải là tệp thường (không chấp nhận symlink/thư mục).",
        )
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(raw_path, flags)
    except OSError as exc:
        raise ApiError(503, error_code, "Không mở được tệp khóa mã hoá người nhận.") from exc
    try:
        fst = os.fstat(fd)
        if not stat.S_ISREG(fst.st_mode):
            raise ApiError(503, error_code, "Tệp khóa mã hoá người nhận không phải tệp thường.")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 4096)
            if not chunk:
                break
            chunks.append(chunk)
        secret_bytes = b"".join(chunks).strip(b"\r\n")
    finally:
        os.close(fd)
    if len(secret_bytes) < MIN_RECIPIENT_KEY_BYTES:
        raise ApiError(503, error_code, "Khóa mã hoá người nhận quá ngắn (tối thiểu 32 byte).")
    return secret_bytes


def _derive_aes256_subkey(master_key: bytes, key_id: str) -> bytes:
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_HKDF_SALT,
        info=_HKDF_AES_INFO_PREFIX + key_id.encode("utf-8"),
    )
    return hkdf.derive(bytes(master_key))


def _derive_phone_hmac_subkey(master_key: bytes) -> bytes:
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_HKDF_SALT,
        info=_HKDF_PHONE_HMAC_INFO,
    )
    return hkdf.derive(bytes(master_key))


def build_recipient_aad(
    *, tenant_id: str, order_id: str, field_name: str, key_id: str
) -> bytes:
    """Canonical AAD bytes binding ``{tenant, order_id, field_name, key_id}`` (W6.1b-2-D2)."""
    t_clean = str(tenant_id or "").strip()
    o_clean = str(order_id or "").strip()
    f_clean = str(field_name or "").strip()
    k_clean = str(key_id or "").strip()
    if not t_clean or not o_clean or not f_clean or not k_clean:
        raise ValueError("Recipient AAD requires non-empty tenant_id, order_id, field_name, and key_id.")
    return json.dumps(
        {
            "field_name": f_clean,
            "key_id": k_clean,
            "order_id": o_clean,
            "tenant": t_clean,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def normalize_recipient_phone(phone: str) -> str:
    """Normalize a phone string for deterministic lookup HMAC and masking."""
    raw = str(phone or "").strip()
    if not raw:
        raise ValueError("Recipient phone must not be empty.")
    compact = re.sub(r"[\s.\-()]+", "", raw)
    if compact.startswith("+84") and len(compact) > 3 and compact[3:].isdigit():
        return "0" + compact[3:]
    if compact.startswith("84") and len(compact) in (11, 12) and compact.isdigit():
        return "0" + compact[2:]
    if compact.startswith("+") and len(compact) > 1 and compact[1:].isdigit():
        return "+" + compact[1:]
    digits = "".join(ch for ch in compact if ch.isdigit())
    if not digits:
        raise ValueError("Recipient phone must contain digits.")
    return digits


def mask_recipient_phone(phone: str) -> str:
    """Mask a phone string into safe display form (e.g. ``0123.xxx.558``) without full digits."""
    normalized = normalize_recipient_phone(phone)
    digits = normalized.lstrip("+")
    if len(digits) >= 7:
        return f"{digits[:4]}.xxx.{digits[-3:]}"
    if len(digits) > 3:
        return f"xxx.{digits[-3:]}"
    return "xxx"


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(token: str) -> bytes:
    padded = token + ("=" * ((4 - len(token) % 4) % 4))
    return base64.urlsafe_b64decode(padded.encode("ascii"))


class RecipientKeyring:
    """Keyring supporting one active write key and ``{key_id: key}`` decryption map (W6.1b-2-D2)."""

    def __init__(
        self,
        keys: Mapping[str, bytes],
        *,
        active_key_id: str = DEFAULT_RECIPIENT_KEY_ID,
        hmac_key_id: str | None = None,
    ) -> None:
        if not keys:
            raise ApiError(
                503,
                "recipient_key_unavailable",
                "Bản đồ khóa người nhận không được rỗng.",
            )
        clean_active = validate_recipient_key_id(active_key_id)
        aes_map: dict[str, AESGCM] = {}
        raw_map: dict[str, bytes] = {}
        for raw_kid, raw_secret in keys.items():
            kid = validate_recipient_key_id(raw_kid)
            if not isinstance(raw_secret, (bytes, bytearray)) or len(raw_secret) < MIN_RECIPIENT_KEY_BYTES:
                raise ApiError(
                    503,
                    "recipient_key_unavailable",
                    f"Khóa người nhận '{kid}' ngắn hơn {MIN_RECIPIENT_KEY_BYTES} byte.",
                )
            sec_bytes = bytes(raw_secret)
            raw_map[kid] = sec_bytes
            aes_map[kid] = AESGCM(_derive_aes256_subkey(sec_bytes, kid))
        if clean_active not in aes_map:
            raise ApiError(
                503,
                "recipient_key_unavailable",
                f"Khóa hiện hành '{clean_active}' không nằm trong bản đồ khóa.",
            )
        chosen_hmac_kid = validate_recipient_key_id(hmac_key_id) if hmac_key_id else clean_active
        if chosen_hmac_kid not in raw_map:
            raise ApiError(
                503,
                "recipient_key_unavailable",
                f"Khóa HMAC tra cứu '{chosen_hmac_kid}' không nằm trong bản đồ khóa.",
            )
        self.active_key_id = clean_active
        self._aes_map = aes_map
        self._phone_hmac_subkey = _derive_phone_hmac_subkey(raw_map[chosen_hmac_kid])

    @property
    def key_ids(self) -> tuple[str, ...]:
        return tuple(self._aes_map.keys())

    def encrypt_field(
        self,
        plaintext: str,
        *,
        tenant_id: str,
        order_id: str,
        field_name: str,
    ) -> str:
        if field_name not in RECIPIENT_ENCRYPTED_FIELDS:
            raise ValueError(f"Unsupported recipient encrypted field: {field_name!r}")
        kid = self.active_key_id
        aad = build_recipient_aad(
            tenant_id=tenant_id,
            order_id=order_id,
            field_name=field_name,
            key_id=kid,
        )
        nonce = os.urandom(AES_GCM_NONCE_BYTES)
        ct_and_tag = self._aes_map[kid].encrypt(
            nonce, str(plaintext).encode("utf-8"), aad
        )
        return f"{CIPHERTEXT_FORMAT_VERSION}:{kid}:{_b64url_encode(nonce + ct_and_tag)}"

    def decrypt_field(
        self,
        token: str,
        *,
        tenant_id: str,
        order_id: str,
        field_name: str,
    ) -> str:
        if field_name not in RECIPIENT_ENCRYPTED_FIELDS:
            raise ValueError(f"Unsupported recipient encrypted field: {field_name!r}")
        raw_token = str(token or "")
        parts = raw_token.split(":", 2)
        if len(parts) != 3:
            raise ApiError(
                500,
                "recipient_decrypt_failed",
                "Định dạng bản mã người nhận không hợp lệ.",
            )
        version, kid, b64_payload = parts
        if version != CIPHERTEXT_FORMAT_VERSION or not KEY_ID_RE.fullmatch(kid) or not b64_payload:
            raise ApiError(
                500,
                "recipient_decrypt_failed",
                "Phiên bản hoặc tiền tố bản mã người nhận không hợp lệ.",
            )
        aesgcm = self._aes_map.get(kid)
        if aesgcm is None:
            raise ApiError(
                503,
                "recipient_key_unavailable",
                f"Không tìm thấy khóa giải mã cho key_id '{kid}'.",
            )
        try:
            blob = _b64url_decode(b64_payload)
        except Exception as exc:
            raise ApiError(
                500,
                "recipient_decrypt_failed",
                "Không giải mã được chuỗi base64 của bản mã người nhận.",
            ) from exc
        if len(blob) < AES_GCM_NONCE_BYTES + AES_GCM_TAG_BYTES:
            raise ApiError(
                500,
                "recipient_decrypt_failed",
                "Độ dài bản mã người nhận không hợp lệ.",
            )
        nonce = blob[:AES_GCM_NONCE_BYTES]
        ct_and_tag = blob[AES_GCM_NONCE_BYTES:]
        aad = build_recipient_aad(
            tenant_id=tenant_id,
            order_id=order_id,
            field_name=field_name,
            key_id=kid,
        )
        try:
            pt_bytes = aesgcm.decrypt(nonce, ct_and_tag, aad)
            return pt_bytes.decode("utf-8")
        except (InvalidTag, UnicodeDecodeError) as exc:
            raise ApiError(
                500,
                "recipient_decrypt_failed",
                "Xác thực AAD hoặc giải mã thông tin người nhận thất bại.",
            ) from exc

    def compute_phone_lookup_hmac(self, phone: str) -> str:
        normalized = normalize_recipient_phone(phone)
        return hmac.new(
            self._phone_hmac_subkey, normalized.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    def encrypt_recipient_record(
        self,
        recipient: Mapping[str, Any],
        *,
        tenant_id: str,
        order_id: str,
    ) -> dict[str, Any]:
        name_val = str(recipient.get("name") or "").strip()
        phone_val = str(recipient.get("phone") or "").strip()
        addr_val = str(recipient.get("address_line") or "").strip()
        if not name_val or not phone_val or not addr_val:
            raise ApiError(
                422,
                "invalid_recipient",
                "Thông tin người nhận thiếu tên, số điện thoại hoặc địa chỉ chi tiết.",
            )
        ward_raw = recipient.get("ward")
        ward_val = str(ward_raw).strip() if isinstance(ward_raw, str) and ward_raw.strip() else None
        district_val = str(recipient.get("district") or "").strip() or None
        province_val = str(recipient.get("province") or "").strip() or None
        return {
            "name_enc": self.encrypt_field(
                name_val, tenant_id=tenant_id, order_id=order_id, field_name="name"
            ),
            "phone_enc": self.encrypt_field(
                phone_val, tenant_id=tenant_id, order_id=order_id, field_name="phone"
            ),
            "address_line_enc": self.encrypt_field(
                addr_val, tenant_id=tenant_id, order_id=order_id, field_name="address_line"
            ),
            "phone_lookup_hmac": self.compute_phone_lookup_hmac(phone_val),
            "phone_masked": mask_recipient_phone(phone_val),
            "ward": ward_val,
            "district": district_val,
            "province": province_val,
        }

    def decrypt_recipient_row(
        self,
        row: Mapping[str, Any],
        *,
        tenant_id: str,
        order_id: str,
    ) -> dict[str, Any]:
        name_enc = row.get("name_enc")
        phone_enc = row.get("phone_enc")
        addr_enc = row.get("address_line_enc")
        is_purged = name_enc is None and phone_enc is None and addr_enc is None
        if is_purged:
            return {
                "order_id": str(order_id),
                "name": None,
                "phone": None,
                "address_line": None,
                "phone_masked": row.get("phone_masked"),
                "ward": row.get("ward"),
                "district": row.get("district"),
                "province": row.get("province"),
                "purged": True,
            }
        if not name_enc or not phone_enc or not addr_enc:
            raise ApiError(
                500,
                "recipient_decrypt_failed",
                "Bản ghi người nhận bị thiếu một phần dữ liệu mã hoá.",
            )
        return {
            "order_id": str(order_id),
            "name": self.decrypt_field(
                str(name_enc), tenant_id=tenant_id, order_id=order_id, field_name="name"
            ),
            "phone": self.decrypt_field(
                str(phone_enc), tenant_id=tenant_id, order_id=order_id, field_name="phone"
            ),
            "address_line": self.decrypt_field(
                str(addr_enc), tenant_id=tenant_id, order_id=order_id, field_name="address_line"
            ),
            "phone_masked": row.get("phone_masked"),
            "ward": row.get("ward"),
            "district": row.get("district"),
            "province": row.get("province"),
            "purged": False,
        }


def load_recipient_keyring(*, env: Mapping[str, str] | None = None) -> RecipientKeyring:
    """Load active recipient key + optional rotation read keys from ``RETAILOPS_RECIPIENT_KEY_FILE``."""
    environ = env if env is not None else os.environ
    key_file = str(environ.get("RETAILOPS_RECIPIENT_KEY_FILE", "") or "").strip()
    active_secret = read_regular_recipient_key_file(key_file, error_code="recipient_key_unavailable")
    explicit_kid = str(environ.get("RETAILOPS_RECIPIENT_KEY_ID", "") or "").strip()
    active_kid = (
        validate_recipient_key_id(explicit_kid)
        if explicit_kid
        else infer_recipient_key_id_from_path(key_file, default=DEFAULT_RECIPIENT_KEY_ID)
    )
    keys: dict[str, bytes] = {active_kid: active_secret}
    extra_spec = str(environ.get("RETAILOPS_RECIPIENT_EXTRA_KEY_FILES", "") or "").strip()
    if extra_spec:
        for entry in extra_spec.split(","):
            item = entry.strip()
            if not item:
                continue
            if "=" not in item:
                raise ApiError(
                    503,
                    "recipient_key_unavailable",
                    "Định dạng RETAILOPS_RECIPIENT_EXTRA_KEY_FILES phải là 'key_id=/duong/dan'.",
                )
            raw_id, raw_path = item.split("=", 1)
            kid = validate_recipient_key_id(raw_id)
            keys[kid] = read_regular_recipient_key_file(
                raw_path.strip(), error_code="recipient_key_unavailable"
            )
    hmac_kid_raw = str(environ.get("RETAILOPS_RECIPIENT_HMAC_KEY_ID", "") or "").strip()
    hmac_kid = validate_recipient_key_id(hmac_kid_raw) if hmac_kid_raw else None
    return RecipientKeyring(keys, active_key_id=active_kid, hmac_key_id=hmac_kid)

"""Image evidence validation, EXIF/GPS-free pixel re-encoding, and protected storage paths (W3-D4, W4-D6)."""
from __future__ import annotations

import base64
import binascii
import hashlib
import io
import os
import re
import uuid
from pathlib import Path

from PIL import Image, ImageOps

from retailops.core import EVIDENCE_MAX_BYTES, ROOT, ApiError, require

MAX_EVIDENCE_PIXELS = 25_000_000
MAX_EVIDENCE_DIMENSION = 12_000
MAX_MODEL_IMAGE_EDGE = 1024
MAX_MODEL_IMAGES = 3
SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
UNSAFE_FILENAME_CHARS_RE = re.compile(r"[\x00-\x1f\x7f/\\]+")


def sanitize_attachment_filename(name: str | None, *, default_name: str = "attachment") -> str:
    """Return a clean display filename without path traversal or control characters."""
    raw = str(name or "").strip()
    if raw:
        raw = raw.replace("\\", "/").split("/")[-1]
        raw = UNSAFE_FILENAME_CHARS_RE.sub("_", raw).strip(" .")
    if not raw or raw in (".", ".."):
        return default_name
    return raw[:120]


def decode_attachment_data_payload(data_str: str, *, max_raw_bytes: int = EVIDENCE_MAX_BYTES) -> bytes:
    """Decode a base64 or data-URL attachment string and enforce raw byte bounds."""
    require(isinstance(data_str, str) and len(data_str.strip()) > 0, 400, "empty_evidence", "Tệp đính kèm rỗng.")
    payload = data_str.strip()
    if payload.startswith("data:"):
        comma = payload.find(",")
        require(comma > 4, 400, "invalid_attachment", "Chuỗi data URL của tệp đính kèm không hợp lệ.")
        payload = payload[comma + 1 :]
    compact = re.sub(r"\s+", "", payload)
    # Reject obviously oversized base64 before allocating full decoded buffer
    max_b64_len = ((int(max_raw_bytes) + 2) // 3) * 4 + 64
    require(
        len(compact) <= max_b64_len,
        413,
        "evidence_too_large",
        "Kích thước tệp đính kèm vượt quá giới hạn cho phép.",
    )
    try:
        raw = base64.b64decode(compact, validate=True)
    except (binascii.Error, ValueError):
        raise ApiError(400, "invalid_attachment", "Dữ liệu base64 của tệp đính kèm không hợp lệ.") from None
    require(len(raw) > 0, 400, "empty_evidence", "Tệp đính kèm rỗng.")
    require(
        len(raw) <= max_raw_bytes,
        413,
        "evidence_too_large",
        "Kích thước tệp đính kèm vượt quá giới hạn cho phép.",
    )
    return raw


def encode_image_data_url(raw_bytes: bytes, mime_type: str = "image/jpeg") -> str:
    b64 = base64.b64encode(raw_bytes).decode("ascii")
    return f"data:{mime_type};base64,{b64}"


def _is_already_clean_small_image(src: Image.Image, src_fmt: str, max_edge: int) -> bool:
    w0, h0 = src.size
    if w0 <= 0 or h0 <= 0 or max(w0, h0) > max_edge:
        return False
    if len(src.getexif()) > 0:
        return False
    info_keys = set((src.info or {}).keys())
    if src_fmt == "JPEG":
        allowed = {"jfif", "jfif_version", "jfif_unit", "jfif_density", "progression"}
    elif src_fmt == "PNG":
        allowed = {"transparency", "interlace"}
    elif src_fmt == "WEBP":
        allowed = set()
    else:
        return False
    return info_keys.issubset(allowed)


def project_image_for_model(raw_bytes: bytes, *, max_edge: int = MAX_MODEL_IMAGE_EDGE) -> dict:
    """Project sanitized image bytes for model input: long edge <=1024 px and zero EXIF/metadata (W4-D3, W4-D7)."""
    require(type(max_edge) is int and 64 <= max_edge <= MAX_MODEL_IMAGE_EDGE, 500, "invalid_projection_bound", "Giới hạn cạnh ảnh gửi model không hợp lệ.")
    prev_max = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = MAX_EVIDENCE_PIXELS
    try:
        with Image.open(io.BytesIO(raw_bytes)) as src:
            src_fmt = (src.format or "JPEG").upper()
            src.load()
            if _is_already_clean_small_image(src, src_fmt, max_edge):
                w0, h0 = src.size
                mime_map = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
                out_mime = mime_map[src_fmt]
                return {
                    "bytes": bytes(raw_bytes),
                    "mime_type": out_mime,
                    "width": int(w0),
                    "height": int(h0),
                    "data_url": encode_image_data_url(bytes(raw_bytes), out_mime),
                }
            oriented = ImageOps.exif_transpose(src)
            has_alpha = oriented.mode in ("RGBA", "LA") or ("transparency" in oriented.info or oriented.mode in ("P", "PA"))
            target_mode = "RGBA" if (has_alpha and src_fmt in ("PNG", "WEBP")) else "RGB"
            converted = oriented if oriented.mode == target_mode else oriented.convert(target_mode)
            w, h = converted.size
            if max(w, h) > max_edge:
                scale = max_edge / float(max(w, h))
                new_w = max(1, min(max_edge, int(round(w * scale))))
                new_h = max(1, min(max_edge, int(round(h * scale))))
                converted = converted.resize((new_w, new_h), Image.Resampling.LANCZOS)
                w, h = converted.size
            raw_pixels = converted.tobytes()
    finally:
        Image.MAX_IMAGE_PIXELS = prev_max

    clean = Image.frombytes(target_mode, (w, h), raw_pixels)
    out = io.BytesIO()
    if target_mode == "RGBA" and src_fmt == "PNG":
        out_mime = "image/png"
        clean.save(out, format="PNG", optimize=True)
    elif src_fmt == "PNG":
        out_mime = "image/png"
        clean.save(out, format="PNG", optimize=True)
    elif src_fmt == "WEBP":
        out_mime = "image/webp"
        clean.save(out, format="WEBP", quality=85)
    else:
        out_mime = "image/jpeg"
        clean.save(out, format="JPEG", quality=85, optimize=True)
    projected_bytes = out.getvalue()
    return {
        "bytes": projected_bytes,
        "mime_type": out_mime,
        "width": int(w),
        "height": int(h),
        "data_url": encode_image_data_url(projected_bytes, out_mime),
    }


def detect_evidence_magic(raw: bytes) -> tuple[str, str]:
    """Inspect magic bytes and return (pil_format, mime_type). Rejects PDF and unknown formats."""
    require(isinstance(raw, (bytes, bytearray)) and len(raw) > 0, 400, "empty_evidence", "Tệp bằng chứng rỗng.")
    require(
        len(raw) <= EVIDENCE_MAX_BYTES,
        413,
        "evidence_too_large",
        "Ảnh bằng chứng vượt quá giới hạn 10 MB.",
    )
    head = bytes(raw[:1024])
    if head.startswith(b"%PDF-") or b"%PDF-" in head[:64]:
        raise ApiError(
            415,
            "pdf_evidence_deferred",
            "Tệp PDF chưa được hỗ trợ trong giai đoạn W3; vui lòng tải ảnh JPEG, PNG hoặc WebP.",
        )
    if len(raw) >= 3 and raw[:3] == b"\xff\xd8\xff":
        return "JPEG", "image/jpeg"
    if len(raw) >= 8 and raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "PNG", "image/png"
    if len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "WEBP", "image/webp"
    raise ApiError(
        415,
        "unsupported_evidence_type",
        "Chỉ chấp nhận ảnh bằng chứng định dạng JPEG, PNG hoặc WebP (kiểm tra theo magic bytes).",
    )


def inspect_and_reencode_evidence(raw: bytes) -> dict:
    """Validate magic bytes, decode image, apply orientation, strip ALL EXIF/GPS/metadata, and re-encode."""
    expected_fmt, mime_type = detect_evidence_magic(raw)
    prev_max = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = MAX_EVIDENCE_PIXELS
    try:
        try:
            with Image.open(io.BytesIO(raw)) as src:
                actual_fmt = (src.format or "").upper()
                if actual_fmt != expected_fmt:
                    raise ApiError(
                        415,
                        "unsupported_evidence_type",
                        "Định dạng nội dung ảnh không khớp với magic bytes.",
                    )
                w0, h0 = src.size
                if (
                    w0 <= 0
                    or h0 <= 0
                    or w0 > MAX_EVIDENCE_DIMENSION
                    or h0 > MAX_EVIDENCE_DIMENSION
                    or (w0 * h0) > MAX_EVIDENCE_PIXELS
                ):
                    raise ApiError(
                        400,
                        "invalid_evidence_dimensions",
                        "Kích thước điểm ảnh của tệp bằng chứng vượt ngưỡng an toàn.",
                    )
                src.load()
                oriented = ImageOps.exif_transpose(src)
                if expected_fmt == "JPEG":
                    target_mode = "L" if oriented.mode == "L" else "RGB"
                else:
                    if oriented.mode in ("RGB", "RGBA", "L", "LA"):
                        target_mode = oriented.mode
                    elif "transparency" in oriented.info or oriented.mode in ("P", "PA"):
                        target_mode = "RGBA"
                    else:
                        target_mode = "RGB"
                converted = oriented if oriented.mode == target_mode else oriented.convert(target_mode)
                width, height = converted.size
                raw_pixels = converted.tobytes()
        except ApiError:
            raise
        except Exception:
            raise ApiError(
                400,
                "invalid_evidence_image",
                "Tệp ảnh bằng chứng bị hỏng hoặc không thể giải mã an toàn.",
            ) from None
    finally:
        Image.MAX_IMAGE_PIXELS = prev_max

    clean = Image.frombytes(target_mode, (width, height), raw_pixels)
    out = io.BytesIO()
    if expected_fmt == "JPEG":
        clean.save(out, format="JPEG", quality=88, optimize=True)
    elif expected_fmt == "PNG":
        clean.save(out, format="PNG", optimize=True)
    else:
        clean.save(out, format="WEBP", quality=88)

    clean_bytes = out.getvalue()
    require(
        0 < len(clean_bytes) <= EVIDENCE_MAX_BYTES,
        413,
        "evidence_too_large",
        "Ảnh bằng chứng sau khi mã hóa lại vượt quá giới hạn 10 MB.",
    )
    return {
        "bytes": clean_bytes,
        "mime_type": mime_type,
        "byte_size": len(clean_bytes),
        "width": int(width),
        "height": int(height),
        "sha256": hashlib.sha256(clean_bytes).hexdigest(),
    }


def sanitize_tenant_segment(tenant_id: str | None) -> str:
    raw = str(tenant_id or "default").strip() or "default"
    if SAFE_SEGMENT_RE.fullmatch(raw) and raw not in (".", ".."):
        return raw
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return f"tenant_{digest}"


def resolve_protected_subdir(data_root: Path, category: str, tenant_id: str | None) -> tuple[str, Path, Path]:
    """Resolve <data_root>/<category>/<safe_tenant> outside web root and guard against traversal."""
    require(category in ("evidence", "integration"), 500, "invalid_storage_category", "Danh mục lưu trữ không hợp lệ.")
    base_root = Path(data_root).resolve()
    web_root = (ROOT / "web").resolve()
    require(
        base_root != web_root and not base_root.is_relative_to(web_root),
        500,
        "unsafe_storage_root",
        "Thư mục dữ liệu không được nằm trong web root công khai.",
    )
    safe_tid = sanitize_tenant_segment(tenant_id)
    target_dir = (base_root / category / safe_tid).resolve()
    require(
        target_dir.is_relative_to(base_root) and not target_dir.is_relative_to(web_root),
        500,
        "unsafe_storage_path",
        "Đường dẫn lưu trữ nội bộ không hợp lệ.",
    )
    return safe_tid, base_root, target_dir


def atomic_write_bytes(target_dir: Path, filename: str, payload: bytes) -> Path:
    require(
        bool(SAFE_SEGMENT_RE.fullmatch(filename)) and filename not in (".", ".."),
        500,
        "unsafe_storage_filename",
        "Tên tệp lưu trữ nội bộ không hợp lệ.",
    )
    target_dir.mkdir(parents=True, exist_ok=True)
    final_path = (target_dir / filename).resolve()
    require(final_path.parent == target_dir.resolve(), 500, "unsafe_storage_path", "Đường dẫn tệp không hợp lệ.")
    tmp_path = target_dir / f".tmp_{uuid.uuid4().hex}"
    try:
        with open(tmp_path, "wb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, final_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    return final_path

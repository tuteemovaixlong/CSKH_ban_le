"""Image evidence validation, EXIF/GPS-free pixel re-encoding, and protected storage paths (W3-D4)."""
from __future__ import annotations

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
SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


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

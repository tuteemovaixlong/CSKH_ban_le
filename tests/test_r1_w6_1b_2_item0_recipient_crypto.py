"""Phase R1 W6.1b-2 Item 0 tests: recipient AES-256-GCM encryption, HKDF phone HMAC, key rotation, and connector check."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from retailops.core import ApiError
from retailops.identity.persistent import PersistentSessions
from retailops.integration.connectors import ConnectorManager
from retailops.integration.recipient_crypto import (
    AES_GCM_NONCE_BYTES,
    CIPHERTEXT_FORMAT_VERSION,
    RecipientKeyring,
    _b64url_decode,
    _derive_aes256_subkey,
    _derive_phone_hmac_subkey,
    load_recipient_keyring,
    mask_recipient_phone,
    normalize_recipient_phone,
)


class TestRecipientCryptoItem0(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_encrypt_decrypt_roundtrip_random_nonce_and_aad_binding(self) -> None:
        key_v1 = b"recipient-master-key-v1-at-least-32-bytes!!"
        kr = RecipientKeyring({"v1": key_v1}, active_key_id="v1")

        c1 = kr.encrypt_field(
            "Nguyễn Minh Châu",
            tenant_id="shop-a",
            order_id="ord_101",
            field_name="name",
        )
        c2 = kr.encrypt_field(
            "Nguyễn Minh Châu",
            tenant_id="shop-a",
            order_id="ord_101",
            field_name="name",
        )
        self.assertNotEqual(c1, c2, "Each encryption must use a fresh 12-byte random nonce")
        self.assertTrue(c1.startswith(f"{CIPHERTEXT_FORMAT_VERSION}:v1:"))

        raw_blob_1 = _b64url_decode(c1.split(":", 2)[2])
        raw_blob_2 = _b64url_decode(c2.split(":", 2)[2])
        self.assertNotEqual(
            raw_blob_1[:AES_GCM_NONCE_BYTES], raw_blob_2[:AES_GCM_NONCE_BYTES]
        )

        self.assertEqual(
            kr.decrypt_field(c1, tenant_id="shop-a", order_id="ord_101", field_name="name"),
            "Nguyễn Minh Châu",
        )

        # Wrong order_id fails AAD authentication
        with self.assertRaises(ApiError) as err_order:
            kr.decrypt_field(c1, tenant_id="shop-a", order_id="ord_999", field_name="name")
        self.assertEqual(
            (err_order.exception.status, err_order.exception.code),
            (500, "recipient_decrypt_failed"),
        )

        # Wrong tenant_id fails AAD authentication
        with self.assertRaises(ApiError) as err_tenant:
            kr.decrypt_field(c1, tenant_id="shop-b", order_id="ord_101", field_name="name")
        self.assertEqual(
            (err_tenant.exception.status, err_tenant.exception.code),
            (500, "recipient_decrypt_failed"),
        )

        # Swapping field_name (e.g. putting name_enc into phone_enc) fails AAD authentication
        with self.assertRaises(ApiError) as err_field:
            kr.decrypt_field(c1, tenant_id="shop-a", order_id="ord_101", field_name="phone")
        self.assertEqual(
            (err_field.exception.status, err_field.exception.code),
            (500, "recipient_decrypt_failed"),
        )

    def test_key_rotation_decrypts_v1_and_writes_v2(self) -> None:
        f_v1 = self.root / "retailops_recipient_key_v1"
        f_v2 = self.root / "retailops_recipient_key_v2"
        f_v1.write_bytes(b"rotation-secret-key-v1-0123456789abcdef")
        f_v2.write_bytes(b"rotation-secret-key-v2-fedcba9876543210")

        kr_v1 = load_recipient_keyring(env={"RETAILOPS_RECIPIENT_KEY_FILE": str(f_v1)})
        self.assertEqual(kr_v1.active_key_id, "v1")
        enc_old = kr_v1.encrypt_recipient_record(
            {
                "name": "Trần Thu Hà",
                "phone": "0903 123 418",
                "address_line": "Số 12 Đường Cộng Hòa",
                "ward": "Phường 13",
                "district": "Quận Tân Bình",
                "province": "TP. Hồ Chí Minh",
            },
            tenant_id="shop-demo",
            order_id="ord_rot_1",
        )
        self.assertTrue(enc_old["name_enc"].startswith(f"{CIPHERTEXT_FORMAT_VERSION}:v1:"))

        # Rotate active key to v2 while keeping v1 in extra read keys
        kr_v2 = load_recipient_keyring(
            env={
                "RETAILOPS_RECIPIENT_KEY_FILE": str(f_v2),
                "RETAILOPS_RECIPIENT_EXTRA_KEY_FILES": f"v1={f_v1}",
            }
        )
        self.assertEqual(kr_v2.active_key_id, "v2")
        dec_old = kr_v2.decrypt_recipient_row(
            enc_old, tenant_id="shop-demo", order_id="ord_rot_1"
        )
        self.assertEqual(dec_old["name"], "Trần Thu Hà")
        self.assertEqual(dec_old["phone"], "0903 123 418")
        self.assertEqual(dec_old["address_line"], "Số 12 Đường Cộng Hòa")
        self.assertFalse(dec_old["purged"])

        enc_new = kr_v2.encrypt_field(
            "Lê Hoàng Nam",
            tenant_id="shop-demo",
            order_id="ord_rot_2",
            field_name="name",
        )
        self.assertTrue(enc_new.startswith(f"{CIPHERTEXT_FORMAT_VERSION}:v2:"))

        # Keyring without v1 rejects v1 ciphertext with 503 recipient_key_unavailable
        kr_only_v2 = load_recipient_keyring(env={"RETAILOPS_RECIPIENT_KEY_FILE": str(f_v2)})
        with self.assertRaises(ApiError) as missing_kid:
            kr_only_v2.decrypt_recipient_row(
                enc_old, tenant_id="shop-demo", order_id="ord_rot_1"
            )
        self.assertEqual(
            (missing_kid.exception.status, missing_kid.exception.code),
            (503, "recipient_key_unavailable"),
        )

    def test_phone_lookup_hmac_domain_separated_and_normalized(self) -> None:
        master = b"master-recipient-secret-32-bytes-ok!!"
        self.assertNotEqual(
            _derive_aes256_subkey(master, "v1"),
            _derive_phone_hmac_subkey(master),
            "AES-256-GCM subkey and phone lookup HMAC subkey must be domain-separated",
        )
        kr = RecipientKeyring({"v1": master}, active_key_id="v1")
        variants = (
            "0903123418",
            "0903 123 418",
            "0903.123.418",
            "0903-123-418",
            "+84 903 123 418",
            "+84903123418",
        )
        normalized_set = {normalize_recipient_phone(v) for v in variants}
        self.assertEqual(normalized_set, {"0903123418"})
        hmac_set = {kr.compute_phone_lookup_hmac(v) for v in variants}
        self.assertEqual(len(hmac_set), 1)
        self.assertEqual(mask_recipient_phone("+84 903-123-418"), "0903.xxx.418")

        kr_other = RecipientKeyring(
            {"v1": b"different-master-recipient-secret-32b!!"}, active_key_id="v1"
        )
        self.assertNotEqual(
            kr.compute_phone_lookup_hmac("0903123418"),
            kr_other.compute_phone_lookup_hmac("0903123418"),
        )

    def test_recipient_key_file_rejects_missing_short_dir_and_symlink(self) -> None:
        with self.assertRaises(ApiError) as e_unset:
            load_recipient_keyring(env={"RETAILOPS_RECIPIENT_KEY_FILE": ""})
        self.assertEqual(
            (e_unset.exception.status, e_unset.exception.code),
            (503, "recipient_key_unavailable"),
        )

        missing_path = self.root / "missing_key"
        with self.assertRaises(ApiError) as e_missing:
            load_recipient_keyring(env={"RETAILOPS_RECIPIENT_KEY_FILE": str(missing_path)})
        self.assertEqual(
            (e_missing.exception.status, e_missing.exception.code),
            (503, "recipient_key_unavailable"),
        )

        short_path = self.root / "short_key"
        short_path.write_bytes(b"only-31-bytes-0123456789abcdef!")
        with self.assertRaises(ApiError) as e_short:
            load_recipient_keyring(env={"RETAILOPS_RECIPIENT_KEY_FILE": str(short_path)})
        self.assertEqual(
            (e_short.exception.status, e_short.exception.code),
            (503, "recipient_key_unavailable"),
        )

        dir_path = self.root / "dir_key"
        dir_path.mkdir()
        with self.assertRaises(ApiError) as e_dir:
            load_recipient_keyring(env={"RETAILOPS_RECIPIENT_KEY_FILE": str(dir_path)})
        self.assertEqual(
            (e_dir.exception.status, e_dir.exception.code),
            (503, "recipient_key_unavailable"),
        )

        real_key = self.root / "retailops_recipient_key_v1"
        real_key.write_bytes(b"valid-regular-recipient-key-32-bytes!!")
        sym_path = self.root / "sym_recipient_key"
        symlink_created = False
        try:
            os.symlink(real_key, sym_path)
            symlink_created = True
        except (OSError, NotImplementedError):
            symlink_created = False
        if symlink_created:
            with self.assertRaises(ApiError) as e_sym:
                load_recipient_keyring(env={"RETAILOPS_RECIPIENT_KEY_FILE": str(sym_path)})
            self.assertEqual(
                (e_sym.exception.status, e_sym.exception.code),
                (503, "recipient_key_unavailable"),
            )
        else:
            fake_lstat = SimpleNamespace(st_mode=0o120777)
            with patch("retailops.integration.recipient_crypto.os.lstat", return_value=fake_lstat):
                with self.assertRaises(ApiError) as e_sym2:
                    load_recipient_keyring(env={"RETAILOPS_RECIPIENT_KEY_FILE": str(real_key)})
                self.assertEqual(
                    (e_sym2.exception.status, e_sym2.exception.code),
                    (503, "recipient_key_unavailable"),
                )

    def test_connector_check_reports_recipient_key_status(self) -> None:
        out_dir = self.root / "data"
        secrets_dir = self.root / "secrets"
        secrets_dir.mkdir(parents=True, exist_ok=True)
        sessions = PersistentSessions(out_dir / "persistent")
        sessions.provision_tenant("shop-demo", "Shop Demo")

        conn_secret = "SECRET_CONN_32_BYTES_0123456789ABCDEF"
        digest_secret = "SECRET_DIGEST_32_BYTES_0123456789ABCD"
        recip_secret = "SECRET_RECIP_32_BYTES_0123456789ABCDE"
        (secrets_dir / "retailops_connector_marketplace_sim").write_text(
            conn_secret + "\n", encoding="utf-8"
        )
        digest_file = secrets_dir / "retailops_event_digest_key"
        recip_file = secrets_dir / "retailops_recipient_key_v1"
        digest_file.write_text(digest_secret + "\n", encoding="utf-8")

        base_env = {
            **os.environ,
            "PYTHONIOENCODING": "utf-8",
            "RETAILOPS_OUTPUT": str(out_dir),
            "RETAILOPS_STORAGE_BACKEND": "sqlite",
            "RETAILOPS_CONNECTOR_SECRETS_DIR": str(secrets_dir),
            "RETAILOPS_EVENT_DIGEST_KEY_FILE": str(digest_file),
            "RETAILOPS_RECIPIENT_KEY_FILE": str(recip_file),
        }
        mgr = ConnectorManager(sessions, env=base_env)
        mgr.add_connector("shop-demo", source_system="marketplace_sim")

        # Missing recipient key -> check fails with recipient_key scope
        bad_report = mgr.check_connectors()
        self.assertFalse(bad_report["ok"])
        self.assertEqual(bad_report["digest_key_status"], "ok")
        self.assertEqual(bad_report["recipient_key_status"], "missing_file")
        self.assertTrue(
            any(
                i["scope"] == "recipient_key" and i["reason"] == "missing_file"
                for i in bad_report["issues"]
            )
        )

        # Write valid recipient key -> check succeeds via CLI without leaking secret bytes
        recip_file.write_text(recip_secret + "\n", encoding="utf-8")
        repo_root = Path(__file__).resolve().parents[1]
        proc = subprocess.run(
            [sys.executable, "-m", "retailops", "connector", "--output", str(out_dir), "check"],
            cwd=str(repo_root),
            env=base_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["result"], "CONNECTOR_CHECK_OK")
        self.assertEqual(payload["recipient_key_status"], "ok")
        self.assertNotIn(recip_secret, proc.stdout)
        self.assertNotIn(recip_secret, proc.stderr)


if __name__ == "__main__":
    unittest.main()

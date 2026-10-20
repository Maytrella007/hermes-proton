"""Tests for downloading and decrypting attachments."""

from __future__ import annotations

import os
import unittest
import warnings

warnings.simplefilter("ignore")

import pgpy  # noqa: E402
from pgpy.constants import (  # noqa: E402
    CompressionAlgorithm,
    HashAlgorithm,
    KeyFlags,
    PubKeyAlgorithm,
    SymmetricKeyAlgorithm,
)

import proton_tools as tools  # noqa: E402
from protonlite import crypto, send  # noqa: E402
from protonlite.crypto import KeyBundle  # noqa: E402


def _key(email: str = "att@proton.me") -> "pgpy.PGPKey":
    key = pgpy.PGPKey.new(PubKeyAlgorithm.RSAEncryptOrSign, 2048)
    key.add_uid(
        pgpy.PGPUID.new("Att", email=email),
        usage={KeyFlags.Sign, KeyFlags.EncryptCommunications},
        hashes=[HashAlgorithm.SHA256],
        ciphers=[SymmetricKeyAlgorithm.AES256],
        compression=[CompressionAlgorithm.Uncompressed],
    )
    return key


class AttachmentCrypto(unittest.TestCase):
    def test_round_trip_binary(self) -> None:
        key = _key()
        data = bytes(range(256)) * 8 + b"end \xff\x00 bytes"
        session_key = os.urandom(send.SESSION_KEY_BYTES)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            msg = pgpy.PGPMessage.new(
                data, format="b", compression=CompressionAlgorithm.Uncompressed
            )
        enc = send._encrypt_with(str(key.pubkey), msg, session_key)
        blob = bytes(enc)
        key_packets = send._take(blob, (send.TAG_PKESK,))
        data_packet = send._take(blob, (send.TAG_SEIPD, send.TAG_SED))
        bundle = KeyBundle(id="a", armored=str(key), passphrase=b"")
        self.assertEqual(crypto.decrypt_attachment(key_packets, data_packet, [bundle]), data)


class SendAttachment(unittest.TestCase):
    def test_build_attachment_round_trips_and_signs(self) -> None:
        key = _key("sender@proton.me")
        bundle = KeyBundle(id="s", armored=str(key), passphrase=b"")
        data = b"report body \xff\x00 bytes and caf\xc3\xa9"
        amat = send.build_attachment(data, str(key.pubkey), signer=bundle)
        out = crypto.decrypt_attachment(amat.key_packets, amat.data_packet, [bundle])
        self.assertEqual(out, data)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            sig = pgpy.PGPSignature.from_blob(amat.signature)
            self.assertTrue(bool(key.pubkey.verify(data, sig)))


class AttachmentTool(unittest.TestCase):
    def test_registered(self) -> None:
        self.assertIn("proton_get_attachment", [n for n, *_ in tools.TOOLS])

    def test_requires_message_id(self) -> None:
        self.assertEqual(
            tools.PROTON_GET_ATTACHMENT_SCHEMA["parameters"]["required"], ["message_id"]
        )
        self.assertEqual(
            tools.handle_get_attachment({}),
            "A message id is required (from proton_unread or proton_list).",
        )

    def test_send_reports_a_missing_attachment_file(self) -> None:
        import os
        saved = os.environ.get(tools.ALLOWLIST_ENV)
        os.environ[tools.ALLOWLIST_ENV] = "a@b.com"
        try:
            out = tools.handle_send(
                {"to": ["a@b.com"], "subject": "s", "body": "b", "attachments": ["/no/such/file.pdf"]}
            )
            self.assertIn("Attachment not found", out)
        finally:
            if saved is None:
                os.environ.pop(tools.ALLOWLIST_ENV, None)
            else:
                os.environ[tools.ALLOWLIST_ENV] = saved

    def test_safe_name_strips_paths(self) -> None:
        self.assertEqual(tools._safe_name("../../etc/passwd"), "passwd")
        self.assertEqual(tools._safe_name("a b/c.txt"), "c.txt")
        self.assertEqual(tools._safe_name(""), "attachment")
        self.assertEqual(tools._safe_name("/abs/../x"), "x")


if __name__ == "__main__":
    unittest.main()

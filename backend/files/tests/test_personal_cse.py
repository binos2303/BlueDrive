from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4
import struct

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, override_settings

from files import cse


def sign(key, payload):
    r, s = utils.decode_dss_signature(key.sign(payload, ec.ECDSA(hashes.SHA256())))
    return (r.to_bytes(32) + s.to_bytes(32)).hex()


def public(key):
    return key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint,
    ).hex()


class PersonalManifestTests(SimpleTestCase):
    def setUp(self):
        self.tenant = SimpleNamespace(pk=uuid4())
        self.workspace = SimpleNamespace(pk=uuid4())
        self.device, self.recovery, self.file, self.version = (str(uuid4()) for _ in range(4))
        self.proof_key = ec.generate_private_key(ec.SECP256R1())
        self.recovery_key = ec.generate_private_key(ec.SECP256R1())
        self.state = {
            "tenant": str(self.tenant.pk), "workspace": str(self.workspace.pk),
            "devices": {self.device: {"sign": public(self.proof_key), "epoch": 1, "status": "active"}},
            "recovery": {"sign": public(self.recovery_key), "key_id": self.recovery, "generation": 1},
        }

    def manifest(self, size):
        count = (size + cse.CHUNK - 1) // cse.CHUNK
        prefix = (b"BLUDCSE1" + struct.pack(">HHI", 1, 104, 0)
                  + self.tenant.pk.bytes + self.workspace.pk.bytes
                  + cse.uuid_bytes(self.file) + cse.uuid_bytes(self.version)
                  + struct.pack(">QII", size, cse.CHUNK, count) + bytes(56))
        wire = len(prefix) + size + 16 * count
        digest = sha256(prefix).hexdigest()
        meta = {"format": "cse_v1", "file": self.file, "version": self.version, "logical_size": size,
                "prefix": prefix.hex(), "producer": self.device, "epoch": 1,
                "signature": sign(self.proof_key, b"BlueDrive/CSE/sign/v1\0" + cse.uuid_bytes(self.device)
                                  + prefix + bytes.fromhex(digest))}
        meta["recovery_proof"] = sign(self.recovery_key, cse.message(
            "BlueDrive/personal-cse/recovery-check/v1", str(self.tenant.pk), str(self.workspace.pk), self.recovery, 1))
        fields = ("kind", "key_id", "epoch", "suite", "enc", "ct")
        for field, kind, identifier in (("device", "device", self.device), ("recovery", "personal", self.recovery)):
            meta[field] = dict(zip(fields, [kind, identifier, 1, "0010:0001:0002", public(self.proof_key), "00" * 48]))
        meta["manifest_signature"] = sign(self.proof_key, cse.message(
            "BlueDrive/personal-cse/manifest/v1", str(self.tenant.pk), str(self.workspace.pk), self.file, self.version,
            size, wire, digest, self.device, 1, list(meta["device"].values()), list(meta["recovery"].values())))
        return meta, wire, digest

    def validate(self, meta, size, digest, *, write=True):
        return cse.validate_manifest(meta, self.state, self.tenant, self.workspace, size, digest, write=write)

    def test_logical_sizes_use_exact_ciphertext_size_including_empty_files(self):
        for size in (0, 1, cse.CHUNK, cse.MAX_UPLOAD_SIZE):
            with self.subTest(size=size):
                self.assertEqual(len(self.validate(*self.manifest(size))), cse.PREFIX)

    def test_missing_recovery_proof_and_unsigned_device_replacement_are_denied(self):
        metadata, size, digest = self.manifest(1)
        with self.assertRaises(ValidationError):
            self.validate({**metadata, "recovery_proof": "00" * 64}, size, digest)
        with self.assertRaises(ValidationError):
            self.validate({**metadata, "device": {**metadata["device"], "ct": "01" * 48}}, size, digest)

    def test_signed_manifest_cannot_cross_scope_or_change_size(self):
        metadata, size, digest = self.manifest(1)
        with self.assertRaises(ValidationError):
            self.validate(metadata, size + 1, digest)
        with self.assertRaises(ValidationError):
            self.validate({**metadata, "version": str(uuid4())}, size, digest)
        self.tenant.pk = uuid4()
        with self.assertRaises(ValidationError):
            self.validate(metadata, size, digest)

    def test_revoked_producer_cannot_publish_but_signature_remains_verifiable(self):
        metadata, size, digest = self.manifest(1)
        self.state["devices"][self.device]["status"] = "revoked"
        with self.assertRaises(ValidationError):
            self.validate(metadata, size, digest)
        self.assertEqual(len(self.validate(metadata, size, digest, write=False)), cse.PREFIX)

    @override_settings(CSE_FIXTURE={"writer": True})
    def test_runtime_settings_cannot_enable_cse_with_fixture_values(self):
        self.assertFalse(cse.enabled())

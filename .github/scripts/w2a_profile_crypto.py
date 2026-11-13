#!/usr/bin/env python3
"""Encrypt/decrypt the Chrome profile using an EXISTING GitHub Actions secret.

No new password is requested. Only the encrypted archive becomes an artifact.
The original Chrome profile must remain on the ephemeral Actions runner.
"""
import io
import os
import pathlib
import secrets
import sys
import tarfile

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"W2APROF2"
PASSWORD = os.environ.get("FREEMOA_GOOGLE_PASSWORD", "").encode()
if not PASSWORD:
    raise SystemExit("MISSING_EXISTING_GOOGLE_SECRET_FOR_SESSION_ENCRYPTION")


def derive(salt):
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(PASSWORD)


def filtered(member):
    parts = pathlib.PurePosixPath(member.name).parts
    if any(p in {"Cache", "Code Cache", "GPUCache", "ShaderCache", "Crashpad"} for p in parts):
        return None
    if member.name.rsplit("/", 1)[-1].startswith("Singleton"):
        return None
    return member


def encrypt(profile, archive):
    profile = pathlib.Path(profile)
    archive = pathlib.Path(archive)
    if not profile.is_dir():
        raise SystemExit("CHROME_PROFILE_MISSING")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(profile, arcname="chrome-profile", filter=filtered)
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    ciphertext = AESGCM(derive(salt)).encrypt(nonce, buf.getvalue(), MAGIC)
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_bytes(MAGIC + salt + nonce + ciphertext)
    archive.chmod(0o600)
    print("PASS_ENCRYPTED_PROFILE_SAVED_NO_PLAINTEXT_ARTIFACT", flush=True)


def decrypt(archive, workdir):
    raw = pathlib.Path(archive).read_bytes()
    if not raw.startswith(MAGIC) or len(raw) < len(MAGIC) + 28:
        raise SystemExit("INVALID_ENCRYPTED_PROFILE_HEADER")
    pos = len(MAGIC)
    salt, nonce, ciphertext = raw[pos:pos+16], raw[pos+16:pos+28], raw[pos+28:]
    data = AESGCM(derive(salt)).decrypt(nonce, ciphertext, MAGIC)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for m in tar.getmembers():
            if not (m.name == "chrome-profile" or m.name.startswith("chrome-profile/")):
                raise SystemExit("UNSAFE_PROFILE_ARCHIVE_PATH")
            if m.issym() or m.islnk():
                raise SystemExit("UNSAFE_PROFILE_ARCHIVE_LINK")
        tar.extractall(path=workdir, filter="data")
    print("PASS_ENCRYPTED_CHROME_SESSION_RESTORED", flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] not in {"save", "restore"}:
        raise SystemExit("usage: w2a_profile_crypto.py save|restore SOURCE DEST")
    if sys.argv[1] == "save":
        encrypt(sys.argv[2], sys.argv[3])
    else:
        decrypt(sys.argv[2], sys.argv[3])

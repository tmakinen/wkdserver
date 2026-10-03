#!/usr/bin/env python3

import hashlib
import logging
import os
import re
import socket
import ssl
import tempfile

import gnupg
import ldap

# valkey not available in rhel10 so use redis
import redis as valkey

VALKEY_URL = os.environ.get("VALKEY_URL", f"{valkey.__name__}://localhost:6379")
Z_BASE32_ALPHABET = b"ybndrfg8ejkmcpqxot1uwisza345h769"


logger = logging.getLogger(__name__)


def get_keys():
    ssldir = os.path.dirname(ssl.get_default_verify_paths().openssl_cafile)
    ldap.set_option(
        ldap.OPT_X_TLS_CERTFILE,
        os.path.join(ssldir, "certs", f"{socket.gethostname()}.crt"),
    )
    ldap.set_option(
        ldap.OPT_X_TLS_KEYFILE,
        os.path.join(ssldir, "private", f"{socket.gethostname()}.key"),
    )
    conn = ldap.initialize(ldap.get_option(ldap.OPT_URI))
    conn.sasl_external_bind_s()

    result = conn.search_s(
        ldap.get_option(ldap.OPT_DEFBASE),
        ldap.SCOPE_SUBTREE,
        "(&(mail=*)(pgpPublicKey=*))",
        ["mail", "pgpPublicKey"],
    )
    for dn, entry in result:
        yield (
            dn,
            [m.decode("utf-8") for m in entry["mail"]],
            [k.decode("utf-8") for k in entry["pgpPublicKey"]],
        )


def verify_user_pgpkeys(gpg, dn, emails, pgpkeys):
    valid_keys = {}
    for i in range(len(pgpkeys)):
        results = gpg.import_keys(pgpkeys[i])
        if not results or not results.fingerprints:
            logger.warning(f"Failed to read PGP key for user {dn} with index {i}")
            continue

        for fingerprint in results.fingerprints:
            key = gpg.list_keys(keys=[fingerprint])[0]
            algo = key.get("algo")
            curve = key.get("curve", "").lower()
            if algo != "22":
                logger.warning(
                    f"Ignoring invalid PGP key for user {dn} ({fingerprint}) type {algo}"
                )
                continue
            elif curve != "ed25519":
                logger.warning(
                    f"Ignoring invalid PGP key for user {dn} ({fingerprint}) curve {curve}"
                )
            for uid in key.get("uids", []):
                for addr in emails:
                    if re.search(f"<{addr}>$", uid):
                        if addr not in valid_keys:
                            valid_keys[addr] = []
                        valid_keys[addr].append(
                            gpg.export_keys(fingerprint, armor=False)
                        )
            gpg.delete_keys(fingerprint, secret=False)
    return valid_keys


def encode_zbase32(digest):
    result = bytearray()
    bits = 0
    buffer = 0
    for byte in digest:
        buffer = (buffer << 8) | byte
        bits += 8
        while bits >= 5:
            bits -= 5
            index = (buffer >> bits) & 0x1F
            result.append(Z_BASE32_ALPHABET[index])
    if bits > 0:
        index = (buffer << (5 - bits)) & 0x1F
        result.append(Z_BASE32_ALPHABET[index])
    return result.decode("ascii")


def get_wkd_hash(email):
    email = email.strip().lower()
    local_part, domain = email.split("@")
    hasher = hashlib.sha1()
    hasher.update(local_part.encode("utf-8"))
    zbase32_hash = encode_zbase32(hasher.digest())
    return domain, zbase32_hash


def save_key(conn, addr, pgpkeys):
    domain, wkd_hash = get_wkd_hash(addr)
    storage_key = f"wkd:{domain}:hu:{wkd_hash}"

    key_bytes = bytearray()
    for key in pgpkeys:
        key_bytes.extend(key)
    conn.setex(storage_key, 25 * 3600, bytes(key_bytes))


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(filename)s [%(levelname)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    valkey_conn = valkey.from_url(VALKEY_URL)

    with tempfile.TemporaryDirectory() as gpg_home:
        os.chmod(gpg_home, 0o700)
        gpg = gnupg.GPG(gnupghome=gpg_home)
        for dn, emails, pgpkeys in get_keys():
            pgpkeys = verify_user_pgpkeys(gpg, dn, emails, pgpkeys)
            for addr in pgpkeys:
                save_key(valkey_conn, addr, pgpkeys[addr])


if __name__ == "__main__":
    main()

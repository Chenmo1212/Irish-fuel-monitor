#!/usr/bin/env python3
"""
Generate VAPID keys for Web Push.
Run once: python web/gen_vapid.py
Paste the output lines into your .env file.
"""
import base64

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from py_vapid import Vapid


def main():
    v = Vapid()
    v.generate_keys()
    priv_num = v._private_key.private_numbers().private_value
    priv_bytes = priv_num.to_bytes(32, "big")
    priv = base64.urlsafe_b64encode(priv_bytes).rstrip(b"=").decode()
    pub_raw = v._public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    pub = base64.urlsafe_b64encode(pub_raw).rstrip(b"=").decode()
    print("# Add these to your .env file:")
    print(f"VAPID_PUBLIC_KEY={pub}")
    print(f"VAPID_PRIVATE_KEY={priv}")
    print("VAPID_EMAIL=mailto:you@example.com")


if __name__ == "__main__":
    main()

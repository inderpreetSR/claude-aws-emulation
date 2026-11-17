"""Connection helper for AWS Emulator, shared by the notebook, the dashboard and the CLI scripts.

A running emulator writes three files to ~/.aws/emulator/<port>/ :
    config                 endpoint_url, region and ca_bundle
    ca.pem                 its self-signed TLS certificate
    emulator_credentials   the access key for this run (Linux/macOS, when --auth is on)

This module reads them, so nothing has to be copied by hand. When those files are not
visible to this process (for example the emulator runs in Docker), set instead:
    EMULATOR_ENDPOINT        e.g. https://127.0.0.1:9297
    EMULATOR_CA_BUNDLE       path to a copy of ca.pem   (or EMULATOR_INSECURE=1 to skip TLS checks)
    AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY           (any value when --auth off)
"""
from __future__ import annotations

import configparser
import os
from pathlib import Path

import boto3
from botocore.config import Config

PORT = int(os.environ.get("EMULATOR_DATA_PORT", "9297"))
REGION = "us-east-1"


def _home() -> Path:
    return Path(os.environ.get("EMULATOR_HOME", Path.home() / ".aws" / "emulator")) / str(PORT)


def settings() -> dict:
    """Endpoint, TLS and credential settings for the running emulator."""
    home = _home()
    out = {
        "endpoint_url": f"https://127.0.0.1:{PORT}",
        "verify": True,
        "region_name": REGION,
        "aws_access_key_id": os.environ.get("AWS_ACCESS_KEY_ID", "emulator"),
        "aws_secret_access_key": os.environ.get("AWS_SECRET_ACCESS_KEY", "emulator"),
        "source": "defaults",
    }
    cfg = home / "config"
    if cfg.exists():
        cp = configparser.ConfigParser()
        cp.read(cfg)
        sec = cp["default"]
        out["endpoint_url"] = sec.get("endpoint_url", out["endpoint_url"])
        out["region_name"] = sec.get("region", REGION)
        if sec.get("ca_bundle"):
            out["verify"] = sec["ca_bundle"]
        out["source"] = str(home)
    creds = home / "emulator_credentials"
    if creds.exists():
        cp = configparser.ConfigParser()
        cp.read(creds)
        out["aws_access_key_id"] = cp["default"]["aws_access_key_id"]
        out["aws_secret_access_key"] = cp["default"]["aws_secret_access_key"]
    # Explicit overrides win (Docker, remote host).
    if os.environ.get("EMULATOR_ENDPOINT"):
        out["endpoint_url"] = os.environ["EMULATOR_ENDPOINT"]
    if os.environ.get("EMULATOR_CA_BUNDLE"):
        out["verify"] = os.environ["EMULATOR_CA_BUNDLE"]
    if os.environ.get("EMULATOR_INSECURE") == "1":
        out["verify"] = False
    return out


def client(service: str, **kwargs):
    """A boto3 client for `service` that talks to the emulator, never to AWS."""
    s = settings()
    cfg = Config(
        retries={"max_attempts": 2, "mode": "standard"},
        connect_timeout=5,
        read_timeout=30,
        s3={"addressing_style": "path"},
    )
    return boto3.client(
        service,
        endpoint_url=s["endpoint_url"],
        verify=s["verify"],
        region_name=s["region_name"],
        aws_access_key_id=s["aws_access_key_id"],
        aws_secret_access_key=s["aws_secret_access_key"],
        config=cfg,
        **kwargs,
    )


def health() -> bool:
    """True when the emulator answers GET /__admin/health with 200."""
    import urllib.request
    import ssl

    s = settings()
    if s["verify"] is False:
        ctx = ssl._create_unverified_context()
    elif s["verify"] is True:
        ctx = ssl.create_default_context()
    else:
        ctx = ssl.create_default_context(cafile=s["verify"])
    try:
        with urllib.request.urlopen(s["endpoint_url"] + "/__admin/health", context=ctx, timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


if __name__ == "__main__":
    # `python emu.py` prints what a desktop tool needs to connect.
    s = settings()
    print(f"Emulator healthy : {health()}")
    print(f"Settings read from: {s['source']}")
    print(f"Endpoint URL     : {s['endpoint_url']}")
    print(f"Region           : {s['region_name']}")
    print(f"CA certificate   : {s['verify']}")
    print(f"Access key ID    : {s['aws_access_key_id']}")
    print(f"Secret access key: {s['aws_secret_access_key']}")

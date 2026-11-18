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


def client(service: str, credentials: dict | None = None, who: str | None = None, **kwargs):
    """A boto3 client for `service` that talks to the emulator, never to AWS.

    credentials: sign as someone else, e.g. the AccessKey that iam.create_access_key returned,
                 or the Credentials that sts.assume_role returned. Default: the emulator's admin key.
    who:         a label for the activity monitor, such as "ds-user-1". Default: "admin".
    """
    s = settings()
    cfg = Config(
        retries={"max_attempts": 2, "mode": "standard"},
        connect_timeout=5,
        read_timeout=30,
        s3={"addressing_style": "path"},
    )
    creds = credentials or {"AccessKeyId": s["aws_access_key_id"], "SecretAccessKey": s["aws_secret_access_key"]}
    c = boto3.client(
        service,
        endpoint_url=s["endpoint_url"],
        verify=s["verify"],
        region_name=s["region_name"],
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds.get("SessionToken"),
        config=cfg,
        **kwargs,
    )
    if _watching:
        _attach_monitor(c, who or ("admin" if credentials is None else "other"))
    return c


# ---------------------------------------------------------------- activity monitor
# Scripts call emu.watch() to record every AWS call they make, and emu.step() / emu.say()
# to narrate. The dashboard's "Activity monitor" shows the record live, like a terminal.
# Secrets in requests and responses are replaced before anything is written.

ACTIVITY_LOG = Path(os.environ.get("EMULATOR_ACTIVITY_LOG", Path.home() / ".aws" / "emulator" / "activity.jsonl"))
_watching = False
_SECRET_WORDS = ("secret", "password", "sessiontoken", "privatekey")
_CLI_NAMES = {"s3": "s3api", "cloudwatch logs": "logs", "sfn": "stepfunctions"}


def watch(reset: bool = True):
    """Start recording AWS calls made through emu.client() for the activity monitor."""
    global _watching
    _watching = True
    ACTIVITY_LOG.parent.mkdir(parents=True, exist_ok=True)
    if reset:
        ACTIVITY_LOG.write_text("")


def _write(entry: dict):
    import datetime as _dt
    import json as _json
    entry = {"time": _dt.datetime.now().strftime("%H:%M:%S"), **entry}
    with ACTIVITY_LOG.open("a") as f:
        f.write(_json.dumps(entry, default=str) + "\n")


def step(title: str, explanation: str = ""):
    """A numbered heading in the monitor and the terminal."""
    print(f"\n=== {title} ===" + (f"\n{explanation}" if explanation else ""))
    if _watching:
        _write({"kind": "step", "text": title, "detail": explanation})
    pause = float(os.environ.get("STEP_PAUSE", "0"))   # slow down so you can watch live
    if pause:
        import time as _time
        _time.sleep(pause)


def say(text: str):
    """A plain line of narration."""
    print(text)
    if _watching:
        _write({"kind": "info", "text": text})


def _redact(value, key: str = ""):
    if any(w in key.lower() for w in _SECRET_WORDS):
        return "***redacted***"
    if isinstance(value, dict):
        return {k: _redact(v, k) for k, v in value.items() if k != "ResponseMetadata"}
    if isinstance(value, list):
        return [_redact(v) for v in value[:20]]
    if isinstance(value, (bytes, bytearray)):
        return f"<{len(value)} bytes>"
    if hasattr(value, "read"):            # a streaming body: never read it here
        return "<stream>"
    return value


def _cli(service_id: str, operation: str, params: dict) -> str:
    """The equivalent AWS CLI command, so you can learn the CLI alongside Python."""
    import json as _json
    import re as _re
    kebab = lambda s: _re.sub(r"(?<!^)(?=[A-Z])", "-", s).lower()
    cmd = ["aws", _CLI_NAMES.get(service_id.lower(), service_id.lower().replace(" ", "-")), kebab(operation)]
    for k, v in params.items():
        if isinstance(v, (dict, list)):
            v = "'" + _json.dumps(v, separators=(",", ":"), default=str) + "'"
        elif isinstance(v, str) and (" " in v or "{" in v):
            v = "'" + v + "'"
        cmd += [f"--{kebab(k)}", str(v)]
    return " ".join(cmd)


def _attach_monitor(c, who: str):
    service_id = c.meta.service_model.service_id

    def remember(params, context, model, **_):
        context["monitor_params"] = _redact(params)

    def record(http_response, parsed, model, context, **_):
        params = context.get("monitor_params", {})
        entry = {"who": who, "service": service_id, "operation": model.name, "cli": _cli(service_id, model.name, params),
                 "status": getattr(http_response, "status_code", None)}
        err = parsed.get("Error") if isinstance(parsed, dict) else None
        if err:
            entry.update(kind="denied" if "denied" in str(err.get("Code", "")).lower() or "unauthorized" in str(err.get("Code", "")).lower()
                         else "error", code=err.get("Code"), message=err.get("Message", ""))
        else:
            entry.update(kind="call", result=_redact(parsed))
        _write(entry)

    c.meta.events.register("before-parameter-build.*.*", remember)
    c.meta.events.register("after-call.*.*", record)


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

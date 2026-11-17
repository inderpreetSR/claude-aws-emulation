# Setup 2: third-party GUI tools

AWS Emulator has no interface of its own, but any tool that lets you set a custom AWS endpoint can browse it. Every tool needs the same five values. Print them for your running emulator with:

```bash
python emu.py
```

| Value | Where it comes from |
|---|---|
| Endpoint URL | `https://127.0.0.1:9297` by default |
| Region | `us-east-1` |
| Access key ID and secret | `~/.aws/emulator/9297/emulator_credentials`, rewritten on every emulator start |
| CA certificate | `~/.aws/emulator/9297/ca.pem`, the emulator's self-signed certificate |
| S3 addressing | Path style (`https://127.0.0.1:9297/bucket/key`) |

Two things trip up most tools:

- **The certificate is self-signed.** Either point the tool at `ca.pem` or accept the certificate when the tool asks.
- **The access key changes on each start.** To avoid re-entering it, start the emulator with `--auth off`; it then accepts any key.

## DynamoDB: dynamodb-admin (tested)

A free, open-source web interface for browsing tables and editing items. It needs Node.js.

```bash
./desktop-tools/dynamodb-admin.sh
```

Then open http://127.0.0.1:8001. The script reads the endpoint, key and certificate from the running emulator, so there is nothing to type.

## S3: Cyberduck (not tested here)

Cyberduck is a free desktop file browser for macOS and Windows. I could not run a desktop app in the build sandbox, so treat these steps as a starting point.

1. In Preferences → Profiles, enable **S3 (Deprecated path style requests)**. The default S3 profile uses virtual-host addressing, which will not resolve against `127.0.0.1`.
2. Open Connection and choose that profile.
3. Server `127.0.0.1`, port `9297`.
4. Paste the access key ID and secret from `python emu.py`.
5. Accept the certificate prompt on first connect.

## Everything else: the AWS CLI

Not a GUI, but it is the quickest way to check what any GUI shows you. The emulator writes a ready-made CLI config:

```bash
source ./env.sh
```

```bash
aws s3 ls
```

## What does not work

- **The AWS web console** only talks to real AWS and cannot be pointed at the emulator.
- **NoSQL Workbench** (AWS's DynamoDB desktop app) connects to local endpoints over plain HTTP. The emulator serves HTTPS only, so I expect it to fail; I have not tested it.

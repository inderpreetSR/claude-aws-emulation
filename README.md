# claude-aws-emulation

Hands-on labs for learning data and AI work on AWS without an AWS account, using [AWS Emulator](https://github.com/aws/aws-emulator). Every lab runs against the emulator on your own machine, so nothing is billed.

All labs share one scenario: a synthetic retail-loan book for a bank (generated data, no real customers).

## Branches

`main` holds the shared foundation. Each learning track lives on its own branch, built on `main`, and adds one lab under `labs/`.

| Branch | Track | Services | What you practise |
|---|---|---|---|
| `main` | Foundation | all | Connection helper, dashboard, GUI tools |
| `data-analytics` | Data analytics | S3, Glue, Athena, Kinesis | Building a data lake, SQL analysis, streaming |
| `data-science` | Data science | Athena, S3, DynamoDB | Exploration, model training, online scoring |
| `mlops` | MLOps | SageMaker, Step Functions, IAM | Job and endpoint APIs, a pipeline with a quality gate |
| `ai-genai` | AI | Bedrock | Prompts, streaming, tool use, token budgeting |
| `aiops` | AIOps | CloudWatch, CloudWatch Logs | Drift metrics, alarms, log search |

Suggested order: `data-analytics`, `data-science`, `mlops`, then `ai-genai` and `aiops` in either order. Each lab sets up its own data, so any branch also works on its own.

```bash
git switch data-analytics
```

## Getting started

1. Install and start the emulator, following the [official guide](https://docs.aws.amazon.com/emulator/latest/userguide/getting-started.html):

```bash
aws-emulator --telemetry off
```

2. Install the Python libraries:

```bash
pip install -r requirements.txt
```

3. Check the connection. You should see `Emulator healthy : True`:

```bash
python emu.py
```

4. Switch to a track branch and open its lab:

```bash
jupyter lab labs/
```

## Seeing what is inside the emulator

AWS Emulator has no interface of its own. `main` provides three:

- **Notebooks:** each lab shows results as tables and charts.
- **Dashboard:** `python dashboard/server.py`, then open http://127.0.0.1:8800. It browses S3, Glue, DynamoDB, SageMaker, Step Functions and CloudWatch, and has an Athena SQL console.
- **Third-party tools:** see `desktop-tools/README.md` for a DynamoDB web browser, Cyberduck settings and the AWS CLI.

## What is on main

| Path | Purpose |
|---|---|
| `emu.py` | Reads the running emulator's endpoint, certificate and keys; gives you boto3 clients |
| `lab_common.py` | Shared lab helpers: build the data lake, run Athena SQL, create an IAM role, train the model |
| `make_data.py` | Generates the synthetic loan book |
| `env.sh` | Points the AWS CLI and SDKs in your shell at the emulator |
| `dashboard/` | Local web console |
| `desktop-tools/` | Third-party GUI set-up |

## Limits to keep in mind

- **No models run.** SageMaker accepts training jobs and endpoints but trains and serves nothing. Bedrock returns a placeholder reply with real token counts. The labs train models locally with scikit-learn.
- **State is in memory.** Restarting the emulator wipes it; re-running a lab rebuilds what it needs.
- **Fidelity varies by service.** Check the scores on the emulator's releases page when a call behaves unexpectedly.
- **If the emulator runs in Docker,** set `EMULATOR_ENDPOINT` and either `EMULATOR_CA_BUNDLE` or `EMULATOR_INSECURE=1`; see the notes at the top of `emu.py`. This route is untested.

## How the labs were tested

Each notebook was run end to end against an emulator built from source at the 17 November 2026 commit, trimmed to the services the labs use. The saved outputs in the notebooks are from those runs.

# AWS basics track

Start here. Covers the foundations every other track sits on, using the network and access set-up of a bank's lending platform:

1. **Account, region and ARNs:** who you are and how AWS names things.
2. **IAM:** users, groups, policies, the policy simulator, signing in as a restricted user, explicit Deny, and roles with temporary credentials.
3. **VPC:** CIDR ranges, public and private subnets across two availability zones, internet and NAT gateways, route tables and an S3 gateway endpoint.
4. **Inbound and outbound traffic:** security groups (stateful) against network ACLs (stateless), with traffic scenarios that explain each allow or block.
5. **Compute:** launching instances into public and private subnets.
6. **Data protection:** blocking public access, a TLS-only bucket policy, KMS encryption and why it needs `kms:Decrypt`.

Start the emulator, then from the repository root:

```bash
jupyter lab labs/aws-basics/lab.ipynb
```

The notebook removes what a previous run built, so you can re-run it as often as you like. Its saved outputs come from a tested run.

`netcheck.py` contains the traffic evaluator used in part 4. The emulator stores security group and network ACL rules exactly as AWS does but does not move packets, so this module applies AWS's documented evaluation rules to the stored rules. Read it alongside the notebook.

## Data-science team, step by step

`data_science_group.py` builds an IAM group for a data-science team, with a comment on every line:

1. A SageMaker execution role the team may hand to training jobs, and a second role it may not.
2. A managed policy: read curated loan data, own a sandbox prefix, query with Athena, train with SageMaker, pass only the execution role.
3. Guard rails as explicit Deny: never delete source data, never touch personal data, never deploy endpoints.
4. Two users in the group, a policy-simulator review, then ten real attempts signed in as one of the users.

Watch it in the dashboard's Activity monitor. Each call shows as the equivalent AWS CLI command and its result, with secrets redacted:

```bash
python dashboard/server.py
```

```bash
STEP_PAUSE=2 python labs/aws-basics/data_science_group.py
```

`STEP_PAUSE` waits that many seconds at each step so you can follow along. Use the same pattern in your own scripts: call `emu.watch()` once, then `emu.step()` and `emu.say()` to narrate.

## DS Workbench

`ds_workbench.ipynb` is a working notebook for data-science and analytics work, signed in as `ds-user-1` rather than the admin. It reads loan data from S3, queries it with Athena, trains a credit-default model, registers it in SageMaker, follows a training job, batch-scores the loan book and checks the team's guard rails. Run `data_science_group.py` first. Copy it next to your `claude-aws-emulation` folder or open it where it is: it finds `emu.py` either way.

## Emulator gaps to know

- **SageMaker does not check the caller's IAM permissions** in this emulator build (it does only for lineage reads). The script labels those two results as emulator gaps and shows the policy simulator's verdict, which is what real AWS would decide.

- When a role's trust policy names the whole account (`arn:aws:iam::ACCOUNT:root`), real AWS also requires the caller to hold `sts:AssumeRole` in an identity policy. The emulator skips that check.
- No virtual machines boot and no packets flow. Instances stay `pending`, and gateways and routes exist as configuration only.

Browse what the lab creates with `python dashboard/server.py`; the Network and IAM sections show it.

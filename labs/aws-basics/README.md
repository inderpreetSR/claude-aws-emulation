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

## Emulator gaps to know

- When a role's trust policy names the whole account (`arn:aws:iam::ACCOUNT:root`), real AWS also requires the caller to hold `sts:AssumeRole` in an identity policy. The emulator skips that check.
- No virtual machines boot and no packets flow. Instances stay `pending`, and gateways and routes exist as configuration only.

Browse what the lab creates with `python dashboard/server.py`; the Network and IAM sections show it.

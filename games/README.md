# Learning games

Three browser games that teach AWS security and networking concepts, one step at a time. Each level matches a real call you can then run in Jupyter, and the answers shown are real output from AWS Emulator.

| Game | Concept | Levels |
|---|---|---|
| `sts-ticket-hall.html` | STS: who am I, assuming roles, trust policies, expiring credentials | 4 |
| `iam-vault.html` | IAM decisions: explicit Deny, Allow, default deny, conditions | 5 |
| `vpc-gatehouse.html` | Inbound and outbound traffic: security groups against network ACLs | 5 |

Open any file in your browser by double-clicking it. The 3D scenes load Three.js from the internet; without a connection, the levels, quizzes and code still work.

Suggested order: STS, then IAM, then VPC. The IAM and STS games use the `data-science` group, so run `labs/aws-basics/data_science_group.py` first if you want to try the Jupyter code. The VPC game's code runs inside `labs/aws-basics/lab.ipynb`.

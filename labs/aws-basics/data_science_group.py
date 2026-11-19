"""Create a data-science team in IAM, step by step, and prove what it can and cannot do.

Run from the repository root, with the emulator started:

    python labs/aws-basics/data_science_group.py

Then watch every call in the dashboard's Activity monitor (python dashboard/server.py).
To slow it down so you can follow along live:

    STEP_PAUSE=2 python labs/aws-basics/data_science_group.py

What gets built
  * an IAM group "data-science" with one managed policy (what the team may do)
    and one inline guard-rail policy (what it must never do);
  * a SageMaker execution role the team may hand to training jobs, and nothing else;
  * two users in the group.
Then it signs in as one of those users and tries ten things: some allowed, some refused.
Re-running is safe: it removes what the previous run made first.
"""
import json                                        # policies are JSON documents
import sys                                         # to find emu.py at the repository root
import time                                        # a short wait after IAM changes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import emu                                         # our helper: clients that talk to the emulator
from lab_common import ensure_lake                  # creates the loan-data buckets and Athena table
from botocore.exceptions import ClientError        # the error boto3 raises when AWS says no

ACCOUNT = "000000000000"                           # the emulator's account number
LAKE = "bank-lake"                                 # bucket with the loan data (made by lab_common.ensure_lake)
RESULTS = "bank-athena-results"                    # where Athena writes query results
GROUP = "data-science"
USERS = ["ds-user-1", "ds-user-2"]
EXECUTION_ROLE = "ds-sagemaker-execution"
EXECUTION_ROLE_ARN = f"arn:aws:iam::{ACCOUNT}:role/{EXECUTION_ROLE}"
OTHER_ROLE = "mlops-deploy"                        # a role the team must NOT be able to use
OTHER_ROLE_ARN = f"arn:aws:iam::{ACCOUNT}:role/{OTHER_ROLE}"
IMAGE = "683313688378.dkr.ecr.us-east-1.amazonaws.com/sagemaker-scikit-learn:1.2-1-cpu-py3"
POLICY_NAME = "DataScienceAccess"
POLICY_ARN = f"arn:aws:iam::{ACCOUNT}:policy/{POLICY_NAME}"

ensure_lake()                                      # the data this team works on (safe to re-run)
emu.watch()                                        # start recording for the Activity monitor
iam = emu.client("iam")                            # IAM client, signed as the emulator's admin
s3 = emu.client("s3")

# ------------------------------------------------------------------------------------------
emu.step("Step 0. Who am I?",
         "Always check which identity you are using before changing permissions.")
me = emu.client("sts").get_caller_identity()
emu.say(f"Signed in as {me['Arn']}")


# ------------------------------------------------------------------------------------------
emu.step("Step 1. Remove the previous run",
         "IAM refuses to delete a group that still has members or policies, so undo in order.")


def remove_previous_run():
    for user in USERS:
        try:
            for key in iam.list_access_keys(UserName=user)["AccessKeyMetadata"]:
                iam.delete_access_key(UserName=user, AccessKeyId=key["AccessKeyId"])
            iam.remove_user_from_group(GroupName=GROUP, UserName=user)
            iam.delete_user(UserName=user)
        except ClientError:
            pass                                   # it did not exist: nothing to remove
    try:   # remove every policy on the group, including ones added later (such as in SageMaker lessons)
        for p in iam.list_attached_group_policies(GroupName=GROUP)["AttachedPolicies"]:
            iam.detach_group_policy(GroupName=GROUP, PolicyArn=p["PolicyArn"])
        for name in iam.list_group_policies(GroupName=GROUP)["PolicyNames"]:
            iam.delete_group_policy(GroupName=GROUP, PolicyName=name)
        for u in iam.get_group(GroupName=GROUP)["Users"]:       # members this script didn't create
            iam.remove_user_from_group(GroupName=GROUP, UserName=u["UserName"])
        iam.delete_group(GroupName=GROUP)
    except ClientError:
        pass
    try:
        for v in iam.list_policy_versions(PolicyArn=POLICY_ARN)["Versions"]:
            if not v["IsDefaultVersion"]:
                iam.delete_policy_version(PolicyArn=POLICY_ARN, VersionId=v["VersionId"])
        iam.delete_policy(PolicyArn=POLICY_ARN)
    except ClientError:
        pass
    for role in (EXECUTION_ROLE, OTHER_ROLE):
        try:
            for name in iam.list_role_policies(RoleName=role)["PolicyNames"]:
                iam.delete_role_policy(RoleName=role, PolicyName=name)
            iam.delete_role(RoleName=role)
        except ClientError:
            pass


remove_previous_run()
emu.say("Clean slate.")


# ------------------------------------------------------------------------------------------
emu.step("Step 2. Create the SageMaker execution role",
         "Training jobs run as a role, not as the person who started them. "
         "The trust policy lets only the SageMaker service assume it.")
trust_policy = {
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Principal": {"Service": "sagemaker.amazonaws.com"},   # who may assume the role
        "Action": "sts:AssumeRole",
    }],
}
iam.create_role(RoleName=EXECUTION_ROLE,
                AssumeRolePolicyDocument=json.dumps(trust_policy),
                Description="Runs data-science training jobs")
iam.create_role(RoleName=OTHER_ROLE,                          # same trust, but the team may not pass it
                AssumeRolePolicyDocument=json.dumps(trust_policy),
                Description="Used by MLOps to deploy models")
iam.put_role_policy(RoleName=EXECUTION_ROLE, PolicyName="ReadLakeWriteModels", PolicyDocument=json.dumps({
    "Version": "2012-10-17",
    "Statement": [
        {"Effect": "Allow", "Action": ["s3:GetObject", "s3:ListBucket"],
         "Resource": [f"arn:aws:s3:::{LAKE}", f"arn:aws:s3:::{LAKE}/loans/*"]},
        {"Effect": "Allow", "Action": "s3:PutObject",
         "Resource": f"arn:aws:s3:::{LAKE}/models/*"},
    ],
}))


# ------------------------------------------------------------------------------------------
emu.step("Step 3. Write the team's permissions as a managed policy",
         "One statement per job the team does. A managed policy can be reused and versioned.")
access_policy = {
    "Version": "2012-10-17",
    "Statement": [
        {   # read the curated loan data, but nothing else in the bucket
            "Sid": "ReadCuratedData",
            "Effect": "Allow",
            "Action": ["s3:GetObject", "s3:ListBucket"],
            "Resource": [f"arn:aws:s3:::{LAKE}", f"arn:aws:s3:::{LAKE}/loans/*"],
        },
        {   # a sandbox prefix the team fully owns
            "Sid": "OwnSandbox",
            "Effect": "Allow",
            "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
            "Resource": f"arn:aws:s3:::{LAKE}/sandbox/data-science/*",
        },
        {   # run SQL with Athena, read table definitions from Glue, write query results
            "Sid": "QueryWithAthena",
            "Effect": "Allow",
            "Action": ["athena:StartQueryExecution", "athena:GetQueryExecution", "athena:GetQueryResults",
                       "glue:GetDatabase", "glue:GetDatabases", "glue:GetTable", "glue:GetTables",
                       "s3:PutObject", "s3:GetBucketLocation"],
            "Resource": [f"arn:aws:athena:us-east-1:{ACCOUNT}:workgroup/primary",
                         f"arn:aws:glue:us-east-1:{ACCOUNT}:catalog",
                         f"arn:aws:glue:us-east-1:{ACCOUNT}:database/lending",
                         f"arn:aws:glue:us-east-1:{ACCOUNT}:table/lending/*",
                         f"arn:aws:s3:::{RESULTS}", f"arn:aws:s3:::{RESULTS}/*"],
        },
        {   # experiment with SageMaker training jobs and models
            "Sid": "TrainModels",
            "Effect": "Allow",
            "Action": ["sagemaker:CreateTrainingJob", "sagemaker:DescribeTrainingJob",
                       "sagemaker:ListTrainingJobs", "sagemaker:CreateModel", "sagemaker:DescribeModel"],
            "Resource": "*",
        },
        {   # hand ONLY the execution role to SageMaker, never any other role
            "Sid": "PassOnlyTheExecutionRole",
            "Effect": "Allow",
            "Action": "iam:PassRole",
            "Resource": EXECUTION_ROLE_ARN,
            "Condition": {"StringEquals": {"iam:PassedToService": "sagemaker.amazonaws.com"}},
        },
    ],
}
iam.create_policy(PolicyName=POLICY_NAME,
                  PolicyDocument=json.dumps(access_policy),
                  Description="What the data-science team may do")


# ------------------------------------------------------------------------------------------
emu.step("Step 4. Create the group and attach the policy",
         "Permissions go on the group, never on individual people.")
iam.create_group(GroupName=GROUP)
iam.attach_group_policy(GroupName=GROUP, PolicyArn=POLICY_ARN)


# ------------------------------------------------------------------------------------------
emu.step("Step 5. Add guard rails with explicit Deny",
         "A Deny beats every Allow. These hold even if someone later grants more by mistake.")
guardrails = {
    "Version": "2012-10-17",
    "Statement": [
        {"Sid": "NeverDeleteSourceData", "Effect": "Deny",
         "Action": "s3:DeleteObject", "Resource": f"arn:aws:s3:::{LAKE}/loans/*"},
        {"Sid": "NoPersonalData", "Effect": "Deny",
         "Action": "s3:*", "Resource": f"arn:aws:s3:::{LAKE}/pii/*"},
        {"Sid": "DeploymentIsForMLOps", "Effect": "Deny",
         "Action": ["sagemaker:CreateEndpoint", "sagemaker:UpdateEndpoint"], "Resource": "*"},
    ],
}
iam.put_group_policy(GroupName=GROUP, PolicyName="DataScienceGuardrails",
                     PolicyDocument=json.dumps(guardrails))


# ------------------------------------------------------------------------------------------
emu.step("Step 6. Create the users and add them to the group",
         "Tags record who owns what; they show up in audits and cost reports.")
for user in USERS:
    iam.create_user(UserName=user, Tags=[{"Key": "team", "Value": "data-science"}])
    iam.add_user_to_group(GroupName=GROUP, UserName=user)
members = [u["UserName"] for u in iam.get_group(GroupName=GROUP)["Users"]]
emu.say(f"Group {GROUP} now has: {', '.join(members)}")


# ------------------------------------------------------------------------------------------
emu.step("Step 7. Review with the policy simulator",
         "Ask IAM what it would decide, without making any real request.")
checks = [("s3:GetObject", f"arn:aws:s3:::{LAKE}/loans/loans.csv"),
          ("s3:DeleteObject", f"arn:aws:s3:::{LAKE}/loans/loans.csv"),
          ("s3:GetObject", f"arn:aws:s3:::{LAKE}/pii/customers.csv"),
          ("s3:PutObject", f"arn:aws:s3:::{LAKE}/sandbox/data-science/notes.txt"),
          ("sagemaker:CreateEndpoint", "*"),
          ("iam:PassRole", EXECUTION_ROLE_ARN),
          ("iam:PassRole", OTHER_ROLE_ARN)]
PASSED_TO_SAGEMAKER = [{"ContextKeyName": "iam:PassedToService", "ContextKeyType": "string",
                        "ContextKeyValues": ["sagemaker.amazonaws.com"]}]   # fills the policy's Condition


def simulate(action, resource):
    return iam.simulate_principal_policy(PolicySourceArn=f"arn:aws:iam::{ACCOUNT}:user/{USERS[0]}",
                                         ActionNames=[action], ResourceArns=[resource],
                                         ContextEntries=PASSED_TO_SAGEMAKER)["EvaluationResults"][0]["EvalDecision"]


for action, resource in checks:
    emu.say(f"  {simulate(action, resource):<13} {action} on {resource}")


# ------------------------------------------------------------------------------------------
emu.step(f"Step 8. Sign in as {USERS[0]}",
         "Give the user an access key and build clients that sign with it. "
         "From here, every call in the monitor is labelled with the user's name.")
s3.put_object(Bucket=LAKE, Key="pii/customers.csv", Body=b"customer_id,name\nC1,(synthetic)\n")  # admin seeds a PII file
admin_sm = emu.client("sagemaker")                            # admin prepares a real endpoint config, so the
try:                                                          # endpoint test below can only fail on permissions
    admin_sm.create_model(ModelName="ds-demo-model", ExecutionRoleArn=EXECUTION_ROLE_ARN,
                          PrimaryContainer={"Image": IMAGE, "ModelDataUrl": f"s3://{LAKE}/loans/loans.csv"})
    admin_sm.create_endpoint_config(EndpointConfigName="ds-demo-config", ProductionVariants=[{
        "VariantName": "primary", "ModelName": "ds-demo-model", "InstanceType": "ml.m5.large", "InitialInstanceCount": 1}])
except ClientError:
    pass                                                      # already there from an earlier run
key = iam.create_access_key(UserName=USERS[0])["AccessKey"]   # the secret is redacted in the monitor
time.sleep(1)                                                 # new keys take a moment, as in AWS
as_user = lambda service: emu.client(service, credentials=key, who=USERS[0])
user_s3, user_athena, user_sm = as_user("s3"), as_user("athena"), as_user("sagemaker")
emu.say(f"Now acting as {as_user('sts').get_caller_identity()['Arn']}")


# ------------------------------------------------------------------------------------------
emu.step("Step 9. Try ten things",
         "Expected result in brackets. Refusals are real IAM decisions made by the emulator. "
    "Where the emulator does not enforce IAM yet (SageMaker), the policy simulator gives AWS's answer.")


ACCESS_DENIED = ("AccessDenied", "AccessDeniedException", "UnauthorizedOperation")


def attempt(expected, description, call, check=None):
    """Try one action. Only a real permissions refusal counts as 'refused'.

    check: (action, resource) to ask the policy simulator about if the emulator's answer
           differs from AWS's. Some services in the emulator do not enforce IAM yet.
    """
    try:
        call()
        outcome = "allowed"
    except ClientError as e:
        code = e.response["Error"]["Code"]
        outcome = f"refused ({code})" if code in ACCESS_DENIED else f"failed for another reason ({code})"
    if outcome.startswith(expected):
        mark = "as expected"
    elif check:
        mark = f"EMULATOR GAP: real AWS refuses this; the policy simulator says {simulate(*check)}"
    else:
        mark = "UNEXPECTED"
    emu.say(f"  [{expected:>7}] {description}: {outcome}  -> {mark}")


def run_query():
    qid = user_athena.start_query_execution(
        QueryString="SELECT segment, COUNT(*) FROM loans GROUP BY segment",
        QueryExecutionContext={"Database": "lending"},
        ResultConfiguration={"OutputLocation": f"s3://{RESULTS}/"})["QueryExecutionId"]
    while user_athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]["State"] in ("QUEUED", "RUNNING"):
        time.sleep(0.5)


def training_job(role_arn):
    return lambda: user_sm.create_training_job(
        TrainingJobName=f"ds-experiment-{int(time.time() * 1000)}", RoleArn=role_arn,
        AlgorithmSpecification={"TrainingImage": IMAGE, "TrainingInputMode": "File"},
        InputDataConfig=[{"ChannelName": "train", "DataSource": {"S3DataSource": {
            "S3DataType": "S3Prefix", "S3Uri": f"s3://{LAKE}/loans/", "S3DataDistributionType": "FullyReplicated"}}}],
        OutputDataConfig={"S3OutputPath": f"s3://{LAKE}/models/"},
        ResourceConfig={"InstanceType": "ml.m5.large", "InstanceCount": 1, "VolumeSizeInGB": 5},
        StoppingCondition={"MaxRuntimeInSeconds": 600})


attempt("allowed", "read loans/loans.csv",
        lambda: user_s3.get_object(Bucket=LAKE, Key="loans/loans.csv")["Body"].read())
attempt("allowed", "write to the team sandbox",
        lambda: user_s3.put_object(Bucket=LAKE, Key="sandbox/data-science/notes.txt", Body=b"feature ideas"))
attempt("allowed", "run an Athena query on the loans table", run_query)
attempt("allowed", "start a training job with the execution role", training_job(EXECUTION_ROLE_ARN))
attempt("refused", "delete loans/loans.csv (guard rail)",
        lambda: user_s3.delete_object(Bucket=LAKE, Key="loans/loans.csv"))
attempt("refused", "read pii/customers.csv (guard rail)",
        lambda: user_s3.get_object(Bucket=LAKE, Key="pii/customers.csv"))
attempt("refused", "deploy a model endpoint (guard rail)",
        lambda: user_sm.create_endpoint(EndpointName=f"ds-shortcut-{int(time.time())}", EndpointConfigName="ds-demo-config"),
        check=("sagemaker:CreateEndpoint", "*"))
attempt("refused", "start a training job with the MLOps role (iam:PassRole)",
        training_job(OTHER_ROLE_ARN), check=("iam:PassRole", OTHER_ROLE_ARN))
attempt("refused", "create a new S3 bucket (never granted)",
        lambda: user_s3.create_bucket(Bucket="ds-private-bucket"))
attempt("refused", "change group membership (never granted)",
        lambda: as_user("iam").add_user_to_group(GroupName=GROUP, UserName=USERS[1]))

emu.step("Done", "Open the dashboard: IAM > Users > ds-user-1 shows every statement that applies to the user. "
                 "Known emulator gap: SageMaker does not check the caller's IAM permissions (this build enforces "
                 "them only for lineage reads), so test SageMaker guard rails with the simulator or on real AWS.")

"""Local dashboard for AWS Emulator.

    python dashboard/server.py            # then open http://127.0.0.1:8800

A browser cannot call the emulator directly (requests must be SigV4-signed and the
certificate is self-signed), so this small server makes the calls with boto3 and hands
the page plain JSON. It binds to 127.0.0.1 only and needs nothing beyond boto3.
"""
from __future__ import annotations

import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import emu  # noqa: E402

HERE = Path(__file__).resolve().parent
PORT = 8800
ATHENA_RESULTS_BUCKET = "emulator-dashboard-athena-results"
_clients: dict = {}


def c(name: str):
    if name not in _clients:
        _clients[name] = emu.client(name)
    return _clients[name]


def ts(v) -> str:
    return v.strftime("%Y-%m-%d %H:%M:%S") if hasattr(v, "strftime") else ("" if v is None else str(v))


def table(columns, rows, drill=None, key_col=0):
    return {"columns": columns, "rows": rows, "drill": drill, "key_col": key_col}


# ---- one function per view: returns {"columns": [...], "rows": [[...]], "drill": view-name|None} ----

def s3_buckets(q):
    b = c("s3").list_buckets().get("Buckets", [])
    return table(["Bucket", "Created"], [[x["Name"], ts(x.get("CreationDate"))] for x in b], "s3_objects")


def s3_objects(q):
    r = c("s3").list_objects_v2(Bucket=q["key"], MaxKeys=500)
    return table(["Key", "Size (bytes)", "Last modified"],
                 [[o["Key"], o["Size"], ts(o.get("LastModified"))] for o in r.get("Contents", [])])


def glue_databases(q):
    d = c("glue").get_databases().get("DatabaseList", [])
    return table(["Database", "Description", "Created"],
                 [[x["Name"], x.get("Description", ""), ts(x.get("CreateTime"))] for x in d], "glue_tables")


def glue_tables(q):
    t = c("glue").get_tables(DatabaseName=q["key"]).get("TableList", [])
    rows = []
    for x in t:
        sd = x.get("StorageDescriptor", {})
        cols = ", ".join(f"{k['Name']}:{k.get('Type', '')}" for k in sd.get("Columns", []))
        rows.append([x["Name"], sd.get("Location", ""), cols])
    return table(["Table", "Location", "Columns"], rows)


def athena_history(q):
    a = c("athena")
    ids = a.list_query_executions(MaxResults=25).get("QueryExecutionIds", [])
    rows = []
    if ids:
        for e in a.batch_get_query_execution(QueryExecutionIds=ids).get("QueryExecutions", []):
            st = e.get("Status", {})
            rows.append([ts(st.get("SubmissionDateTime")), st.get("State", ""),
                         e.get("QueryExecutionContext", {}).get("Database", ""), e.get("Query", "")])
    rows.sort(reverse=True)
    return table(["Submitted", "State", "Database", "SQL"], rows)


def dynamodb_tables(q):
    d = c("dynamodb")
    rows = []
    for n in d.list_tables().get("TableNames", []):
        t = d.describe_table(TableName=n)["Table"]
        keys = ", ".join(f"{k['AttributeName']} ({k['KeyType']})" for k in t.get("KeySchema", []))
        rows.append([n, t.get("TableStatus", ""), keys, t.get("ItemCount", "")])
    return table(["Table", "Status", "Key schema", "Item count"], rows, "dynamodb_items")


def dynamodb_items(q):
    items = c("dynamodb").scan(TableName=q["key"], Limit=100).get("Items", [])
    cols = sorted({k for i in items for k in i})
    flat = lambda v: next(iter(v.values())) if isinstance(v, dict) and len(v) == 1 else v
    return table(cols, [[flat(i.get(k, "")) for k in cols] for i in items])


def sagemaker_training(q):
    j = c("sagemaker").list_training_jobs(MaxResults=50).get("TrainingJobSummaries", [])
    return table(["Training job", "Status", "Created", "Ended"],
                 [[x["TrainingJobName"], x.get("TrainingJobStatus", ""), ts(x.get("CreationTime")),
                   ts(x.get("TrainingEndTime"))] for x in j])


def sagemaker_models(q):
    m = c("sagemaker").list_models(MaxResults=50).get("Models", [])
    return table(["Model", "Created", "ARN"], [[x["ModelName"], ts(x.get("CreationTime")), x.get("ModelArn", "")] for x in m])


def sagemaker_endpoints(q):
    e = c("sagemaker").list_endpoints(MaxResults=50).get("Endpoints", [])
    return table(["Endpoint", "Status", "Created"],
                 [[x["EndpointName"], x.get("EndpointStatus", ""), ts(x.get("CreationTime"))] for x in e])


def cloudwatch_alarms(q):
    a = c("cloudwatch").describe_alarms().get("MetricAlarms", [])
    return table(["Alarm", "State", "Metric", "Condition"],
                 [[x["AlarmName"], x.get("StateValue", ""), f"{x.get('Namespace', '')}/{x.get('MetricName', '')}",
                   f"{x.get('ComparisonOperator', '')} {x.get('Threshold', '')}"] for x in a])


def cloudwatch_metrics(q):
    m = c("cloudwatch").list_metrics().get("Metrics", [])
    return table(["Namespace", "Metric", "Dimensions"],
                 [[x.get("Namespace", ""), x.get("MetricName", ""),
                   ", ".join(f"{d['Name']}={d['Value']}" for d in x.get("Dimensions", []))] for x in m[:300]])


def log_groups(q):
    g = c("logs").describe_log_groups().get("logGroups", [])
    return table(["Log group", "Stored bytes", "Retention (days)"],
                 [[x["logGroupName"], x.get("storedBytes", ""), x.get("retentionInDays", "")] for x in g])


def sfn_machines(q):
    m = c("stepfunctions").list_state_machines().get("stateMachines", [])
    return table(["State machine", "Type", "Created", "ARN"],
                 [[x["name"], x.get("type", ""), ts(x.get("creationDate")), x["stateMachineArn"]] for x in m], "sfn_executions", 3)


def sfn_executions(q):
    e = c("stepfunctions").list_executions(stateMachineArn=q["key"]).get("executions", [])
    return table(["Execution", "Status", "Started", "Stopped"],
                 [[x["name"], x.get("status", ""), ts(x.get("startDate")), ts(x.get("stopDate"))] for x in e])


def kinesis_streams(q):
    s = c("kinesis").list_streams().get("StreamSummaries", [])
    return table(["Stream", "Status", "Mode", "Created"],
                 [[x["StreamName"], x.get("StreamStatus", ""), x.get("StreamModeDetails", {}).get("StreamMode", ""),
                   ts(x.get("StreamCreationTimestamp"))] for x in s])


def sqs_queues(q):
    return table(["Queue URL"], [[u] for u in c("sqs").list_queues().get("QueueUrls", [])])


def sns_topics(q):
    return table(["Topic ARN"], [[t["TopicArn"]] for t in c("sns").list_topics().get("Topics", [])])


def _name(tags, default=""):
    return next((x["Value"] for x in tags or [] if x["Key"] == "Name"), default)


def vpcs(q):
    v = c("ec2").describe_vpcs().get("Vpcs", [])
    return table(["VPC", "Name", "CIDR", "Default", "State"],
                 [[x["VpcId"], _name(x.get("Tags")), x["CidrBlock"], x.get("IsDefault", False), x.get("State", "")] for x in v], "vpc_subnets")


def vpc_subnets(q):
    e = c("ec2")
    by = [{"Name": "vpc-id", "Values": [q["key"]]}]
    rts = e.describe_route_tables(Filters=by)["RouteTables"]
    main = next((rt for rt in rts if any(a.get("Main") for a in rt["Associations"])), None)
    def route_of(sn):
        rt = next((rt for rt in rts if any(a.get("SubnetId") == sn for a in rt["Associations"])), main)
        default = next((r for r in (rt or {}).get("Routes", []) if r.get("DestinationCidrBlock") == "0.0.0.0/0"), None)
        if not default:
            return "local only (isolated)"
        target = default.get("GatewayId") or default.get("NatGatewayId") or ""
        return ("internet gateway " if target.startswith("igw-") else "NAT gateway " if target.startswith("nat-") else "") + target
    s = e.describe_subnets(Filters=by).get("Subnets", [])
    return table(["Subnet", "Name", "CIDR", "Zone", "Free IPs", "Public IP on launch", "Default route (0.0.0.0/0)"],
                 [[x["SubnetId"], _name(x.get("Tags")), x["CidrBlock"], x["AvailabilityZone"], x["AvailableIpAddressCount"],
                   x.get("MapPublicIpOnLaunch", False), route_of(x["SubnetId"])] for x in sorted(s, key=lambda x: x["CidrBlock"])])


def route_tables(q):
    rows = []
    for rt in c("ec2").describe_route_tables().get("RouteTables", []):
        for r in rt.get("Routes", []):
            rows.append([rt["RouteTableId"], _name(rt.get("Tags"), "main" if any(a.get("Main") for a in rt["Associations"]) else ""),
                         rt["VpcId"], r.get("DestinationCidrBlock") or r.get("DestinationPrefixListId", ""),
                         r.get("GatewayId") or r.get("NatGatewayId") or r.get("VpcPeeringConnectionId", ""), r.get("State", "")])
    return table(["Route table", "Name", "VPC", "Destination", "Target", "State"], rows)


def security_groups(q):
    g = c("ec2").describe_security_groups().get("SecurityGroups", [])
    return table(["Group", "Name", "VPC", "Inbound rules", "Outbound rules", "Description"],
                 [[x["GroupId"], x["GroupName"], x.get("VpcId", ""), len(x.get("IpPermissions", [])),
                   len(x.get("IpPermissionsEgress", [])), x.get("Description", "")] for x in g], "sg_rules")


def sg_rules(q):
    rules = c("ec2").describe_security_group_rules(Filters=[{"Name": "group-id", "Values": [q["key"]]}]).get("SecurityGroupRules", [])
    rows = []
    for r in sorted(rules, key=lambda r: r["IsEgress"]):
        port = "all" if r.get("FromPort", -1) == -1 else (str(r["FromPort"]) if r["FromPort"] == r.get("ToPort") else f'{r["FromPort"]}-{r["ToPort"]}')
        peer = r.get("CidrIpv4") or r.get("CidrIpv6") or r.get("PrefixListId") or r.get("ReferencedGroupInfo", {}).get("GroupId", "")
        rows.append(["Outbound" if r["IsEgress"] else "Inbound", "all" if r["IpProtocol"] == "-1" else r["IpProtocol"], port, peer, r.get("Description", "")])
    return table(["Direction", "Protocol", "Port", "Source / destination", "Description"], rows)


def network_acls(q):
    a = c("ec2").describe_network_acls().get("NetworkAcls", [])
    return table(["Network ACL", "Name", "VPC", "Default", "Subnets", "Rules"],
                 [[x["NetworkAclId"], _name(x.get("Tags")), x["VpcId"], x.get("IsDefault", False),
                   len(x.get("Associations", [])), len(x.get("Entries", []))] for x in a], "nacl_entries")


def nacl_entries(q):
    acl = c("ec2").describe_network_acls(NetworkAclIds=[q["key"]])["NetworkAcls"][0]
    proto = {"6": "tcp", "17": "udp", "1": "icmp", "-1": "all"}
    rows = [["Outbound" if e["Egress"] else "Inbound", "*" if e["RuleNumber"] == 32767 else e["RuleNumber"], e["RuleAction"].upper(),
             proto.get(e["Protocol"], e["Protocol"]),
             f'{e["PortRange"]["From"]}-{e["PortRange"]["To"]}' if e.get("PortRange") else "all", e.get("CidrBlock", "")]
            for e in sorted(acl.get("Entries", []), key=lambda e: (e["Egress"], e["RuleNumber"]))]
    return table(["Direction", "Rule", "Action", "Protocol", "Ports", "CIDR"], rows)


def gateways(q):
    e = c("ec2")
    rows = [[g["InternetGatewayId"], "Internet gateway", _name(g.get("Tags")), ", ".join(a["VpcId"] for a in g.get("Attachments", [])) or "detached",
             ", ".join(a.get("State", "") for a in g.get("Attachments", []))] for g in e.describe_internet_gateways().get("InternetGateways", [])]
    rows += [[n["NatGatewayId"], "NAT gateway", _name(n.get("Tags")), n.get("VpcId", ""), n.get("State", "")]
             for n in e.describe_nat_gateways().get("NatGateways", [])]
    rows += [[v["VpcEndpointId"], f'{v.get("VpcEndpointType", "")} endpoint', v.get("ServiceName", ""), v.get("VpcId", ""), v.get("State", "")]
             for v in e.describe_vpc_endpoints().get("VpcEndpoints", [])]
    return table(["Gateway", "Type", "Name / service", "VPC", "State"], rows)


def instances(q):
    rows = []
    for r in c("ec2").describe_instances().get("Reservations", []):
        for i in r["Instances"]:
            rows.append([i["InstanceId"], _name(i.get("Tags")), i.get("InstanceType", ""), i["State"]["Name"], i.get("SubnetId", ""),
                         i.get("PrivateIpAddress", ""), i.get("PublicIpAddress", ""), ", ".join(g["GroupName"] for g in i.get("SecurityGroups", []))])
    return table(["Instance", "Name", "Type", "State", "Subnet", "Private IP", "Public IP", "Security groups"], rows)


def iam_users(q):
    i = c("iam")
    rows = []
    for u in i.list_users().get("Users", []):
        groups = [g["GroupName"] for g in i.list_groups_for_user(UserName=u["UserName"]).get("Groups", [])]
        keys = len(i.list_access_keys(UserName=u["UserName"]).get("AccessKeyMetadata", []))
        rows.append([u["UserName"], ", ".join(groups), keys, ts(u.get("CreateDate")), u["Arn"]])
    return table(["User", "Groups", "Access keys", "Created", "ARN"], rows, "iam_user_access")


def _policies_for(kind, name):
    i = c("iam")
    attached = getattr(i, f"list_attached_{kind}_policies")(**{f"{kind.capitalize()}Name": name}).get("AttachedPolicies", [])
    inline = getattr(i, f"list_{kind}_policies")(**{f"{kind.capitalize()}Name": name}).get("PolicyNames", [])
    out = []
    for p in attached:
        meta = i.get_policy(PolicyArn=p["PolicyArn"])["Policy"]
        doc = i.get_policy_version(PolicyArn=p["PolicyArn"], VersionId=meta["DefaultVersionId"])["PolicyVersion"]["Document"]
        out.append((f"managed: {p['PolicyName']}", doc))
    for n in inline:
        out.append((f"inline: {n}", getattr(i, f"get_{kind}_policy")(**{f"{kind.capitalize()}Name": name, "PolicyName": n})["PolicyDocument"]))
    return out


def _statement_rows(source, via, doc):
    if isinstance(doc, str):
        from urllib.parse import unquote
        doc = json.loads(unquote(doc))
    stmts = doc.get("Statement", [])
    stmts = stmts if isinstance(stmts, list) else [stmts]
    as_list = lambda v: ", ".join(v) if isinstance(v, list) else str(v)
    return [[via, source, s.get("Effect", ""), as_list(s.get("Action", s.get("NotAction", ""))), as_list(s.get("Resource", ""))] for s in stmts]


def iam_user_access(q):
    """Everything that grants or denies this user access: own policies plus each group's."""
    rows = []
    for src, doc in _policies_for("user", q["key"]):
        rows += _statement_rows(src, "user", doc)
    for g in c("iam").list_groups_for_user(UserName=q["key"]).get("Groups", []):
        for src, doc in _policies_for("group", g["GroupName"]):
            rows += _statement_rows(src, f"group {g['GroupName']}", doc)
    return table(["Via", "Policy", "Effect", "Actions", "Resources"], rows)


def iam_groups(q):
    i = c("iam")
    rows = [[g["GroupName"], len(i.get_group(GroupName=g["GroupName"]).get("Users", [])), ts(g.get("CreateDate")), g["Arn"]]
            for g in i.list_groups().get("Groups", [])]
    return table(["Group", "Members", "Created", "ARN"], rows)


def iam_roles(q):
    rows = []
    for r in c("iam").list_roles().get("Roles", []):
        doc = r.get("AssumeRolePolicyDocument", {})
        if isinstance(doc, str):
            from urllib.parse import unquote
            doc = json.loads(unquote(doc))
        principals = []
        for s in doc.get("Statement", []):
            for v in (s.get("Principal") or {}).values():
                principals += v if isinstance(v, list) else [v]
        rows.append([r["RoleName"], ", ".join(principals), r.get("MaxSessionDuration", ""), r.get("Description", ""), r["Arn"]])
    return table(["Role", "Trusted by (who may assume it)", "Max session (s)", "Description", "ARN"], rows, "iam_role_access")


def iam_role_access(q):
    rows = []
    for src, doc in _policies_for("role", q["key"]):
        rows += _statement_rows(src, "role", doc)
    return table(["Via", "Policy", "Effect", "Actions", "Resources"], rows)


def iam_policies(q):
    p = c("iam").list_policies(Scope="Local").get("Policies", [])
    return table(["Customer-managed policy", "Attached to", "Default version", "ARN"],
                 [[x["PolicyName"], x.get("AttachmentCount", 0), x.get("DefaultVersionId", ""), x["Arn"]] for x in p])


# name -> (group, label, function, shown in sidebar)
VIEWS = {
    "vpcs": ("Network", "VPCs", vpcs, True),
    "vpc_subnets": ("Network", "Subnets", vpc_subnets, False),
    "route_tables": ("Network", "Route tables", route_tables, True),
    "gateways": ("Network", "Gateways and endpoints", gateways, True),
    "security_groups": ("Network", "Security groups", security_groups, True),
    "sg_rules": ("Network", "Rules", sg_rules, False),
    "network_acls": ("Network", "Network ACLs", network_acls, True),
    "nacl_entries": ("Network", "Rules", nacl_entries, False),
    "instances": ("Network", "EC2 instances", instances, True),
    "iam_users": ("IAM", "Users", iam_users, True),
    "iam_user_access": ("IAM", "Effective policies", iam_user_access, False),
    "iam_groups": ("IAM", "Groups", iam_groups, True),
    "iam_roles": ("IAM", "Roles", iam_roles, True),
    "iam_role_access": ("IAM", "Role policies", iam_role_access, False),
    "iam_policies": ("IAM", "Customer-managed policies", iam_policies, True),
    "s3_buckets": ("Data lake", "S3 buckets", s3_buckets, True),
    "s3_objects": ("Data lake", "S3 objects", s3_objects, False),
    "glue_databases": ("Data lake", "Glue databases", glue_databases, True),
    "glue_tables": ("Data lake", "Glue tables", glue_tables, False),
    "athena_history": ("Data lake", "Athena query history", athena_history, True),
    "dynamodb_tables": ("Data lake", "DynamoDB tables", dynamodb_tables, True),
    "dynamodb_items": ("Data lake", "DynamoDB items", dynamodb_items, False),
    "kinesis_streams": ("Streaming", "Kinesis streams", kinesis_streams, True),
    "sqs_queues": ("Streaming", "SQS queues", sqs_queues, True),
    "sns_topics": ("Streaming", "SNS topics", sns_topics, True),
    "sagemaker_training": ("ML and MLOps", "SageMaker training jobs", sagemaker_training, True),
    "sagemaker_models": ("ML and MLOps", "SageMaker models", sagemaker_models, True),
    "sagemaker_endpoints": ("ML and MLOps", "SageMaker endpoints", sagemaker_endpoints, True),
    "sfn_machines": ("ML and MLOps", "Step Functions", sfn_machines, True),
    "sfn_executions": ("ML and MLOps", "Executions", sfn_executions, False),
    "cloudwatch_alarms": ("AIOps", "CloudWatch alarms", cloudwatch_alarms, True),
    "cloudwatch_metrics": ("AIOps", "CloudWatch metrics", cloudwatch_metrics, True),
    "log_groups": ("AIOps", "Log groups", log_groups, True),
}


def short_error(e: Exception) -> str:
    code = getattr(e, "response", {}).get("Error", {}).get("Code") if hasattr(e, "response") else None
    msg = str(e)
    return f"{code}: {msg}" if code and code not in msg else msg


def run_athena(sql: str, database: str | None):
    """Run SQL on the emulator's Athena and return the result set."""
    a, s3 = c("athena"), c("s3")
    try:
        s3.head_bucket(Bucket=ATHENA_RESULTS_BUCKET)
    except Exception:
        s3.create_bucket(Bucket=ATHENA_RESULTS_BUCKET)
    args = {"QueryString": sql, "ResultConfiguration": {"OutputLocation": f"s3://{ATHENA_RESULTS_BUCKET}/"}}
    if database:
        args["QueryExecutionContext"] = {"Database": database}
    qid = a.start_query_execution(**args)["QueryExecutionId"]
    deadline = time.time() + 60
    while True:
        st = a.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]
        if st["State"] in ("SUCCEEDED", "FAILED", "CANCELLED"):
            break
        if time.time() > deadline:
            return {"error": "Query still running after 60 seconds", "id": qid}
        time.sleep(0.3)
    if st["State"] != "SUCCEEDED":
        return {"error": f"{st['State']}: {st.get('StateChangeReason', 'no reason given')}", "id": qid}
    res = a.get_query_results(QueryExecutionId=qid, MaxResults=500)["ResultSet"]
    cols = [x["Name"] for x in res.get("ResultSetMetadata", {}).get("ColumnInfo", [])]
    rows = [[d.get("VarCharValue", "") for d in r.get("Data", [])] for r in res.get("Rows", [])]
    if rows and rows[0] == cols:  # Athena repeats the header as the first row
        rows = rows[1:]
    return {"columns": cols, "rows": rows, "id": qid}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # keep the terminal quiet
        pass

    def send_json(self, obj, status=200):
        body = json.dumps(obj, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path in ("/", "/index.html"):
            body = (HERE / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif u.path == "/api/status":
            s = emu.settings()
            self.send_json({"healthy": emu.health(), "endpoint": s["endpoint_url"], "region": s["region_name"],
                            "views": [{"id": k, "group": g, "label": l} for k, (g, l, _, show) in VIEWS.items() if show]})
        elif u.path == "/api/counts":
            out = {}
            for k, (_, _, fn, show) in VIEWS.items():
                if show:
                    try:
                        out[k] = len(fn({})["rows"])
                    except Exception:
                        out[k] = None
            self.send_json(out)
        elif u.path.startswith("/api/view/"):
            name = u.path.rsplit("/", 1)[1]
            if name not in VIEWS:
                return self.send_json({"error": "Unknown view"}, 404)
            try:
                self.send_json(VIEWS[name][2](q))
            except Exception as e:
                self.send_json({"error": short_error(e)})
        else:
            self.send_json({"error": "Not found"}, 404)

    def do_POST(self):
        if self.path != "/api/athena":
            return self.send_json({"error": "Not found"}, 404)
        # Only the page served from this server may post; blocks other sites open in the browser.
        origin = self.headers.get("Origin")
        if origin and origin not in (f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"):
            return self.send_json({"error": "Forbidden"}, 403)
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
            self.send_json(run_athena(body.get("sql", ""), body.get("database") or None))
        except Exception as e:
            self.send_json({"error": short_error(e)})


if __name__ == "__main__":
    if len(sys.argv) > 1:
        PORT = int(sys.argv[1])
    print(f"Emulator endpoint: {emu.settings()['endpoint_url']}  healthy: {emu.health()}")
    print(f"Dashboard: http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()

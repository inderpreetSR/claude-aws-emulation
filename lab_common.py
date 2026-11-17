"""Helpers shared by every lab branch. Each lab calls these so it can run on its own."""
from __future__ import annotations

import json
import time

import pandas as pd
from botocore.exceptions import ClientError

import emu
from make_data import loan_book

LAKE, RESULTS, DB = "bank-lake", "bank-athena-results", "lending"
ROLE = "lab-service-role"
FEATURES = ["credit_score", "annual_income", "loan_amount", "dti", "tenure_months", "days_past_due"]
_GLUE_TYPES = {"int64": "bigint", "float64": "double", "object": "string", "str": "string"}


def attempt(label, fn):
    """Run one emulator call; report a refusal instead of stopping the notebook."""
    try:
        out = fn()
        print(f"OK      {label}")
        return out
    except ClientError as e:
        err = e.response["Error"]
        print(f"REFUSED {label}: {err.get('Code')} - {err.get('Message', '')[:200]}")


def ensure_lake(rows: int = 2000) -> pd.DataFrame:
    """Create the buckets, upload the synthetic loan book and register it in Glue. Safe to re-run."""
    assert emu.health(), "Emulator is not reachable. Start it first (README.md, step 1)."
    s3, glue = emu.client("s3"), emu.client("glue")
    df = loan_book(rows)
    have = [b["Name"] for b in s3.list_buckets()["Buckets"]]
    for b in (LAKE, RESULTS):
        if b not in have:
            s3.create_bucket(Bucket=b)
    s3.put_object(Bucket=LAKE, Key="loans/loans.csv", Body=df.to_csv(index=False).encode())
    if DB not in [d["Name"] for d in glue.get_databases()["DatabaseList"]]:
        glue.create_database(DatabaseInput={"Name": DB, "Description": "Synthetic retail lending book"})
    if "loans" in [t["Name"] for t in glue.get_tables(DatabaseName=DB)["TableList"]]:
        glue.delete_table(DatabaseName=DB, Name="loans")
    glue.create_table(DatabaseName=DB, TableInput={
        "Name": "loans", "TableType": "EXTERNAL_TABLE",
        "Parameters": {"classification": "csv", "skip.header.line.count": "1"},
        "StorageDescriptor": {
            "Columns": [{"Name": c, "Type": _GLUE_TYPES[str(t)]} for c, t in df.dtypes.items()],
            "Location": f"s3://{LAKE}/loans/",
            "InputFormat": "org.apache.hadoop.mapred.TextInputFormat",
            "OutputFormat": "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat",
            "SerdeInfo": {"SerializationLibrary": "org.apache.hadoop.hive.serde2.lazy.LazySimpleSerDe",
                          "Parameters": {"field.delim": ","}}}})
    return df


def run_sql(sql: str, database: str = DB) -> pd.DataFrame:
    """Run SQL on the emulator's Athena and return a DataFrame."""
    athena = emu.client("athena")
    qid = athena.start_query_execution(
        QueryString=sql, QueryExecutionContext={"Database": database},
        ResultConfiguration={"OutputLocation": f"s3://{RESULTS}/"})["QueryExecutionId"]
    while True:
        status = athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]
        if status["State"] in ("SUCCEEDED", "FAILED", "CANCELLED"):
            break
        time.sleep(0.2)
    if status["State"] != "SUCCEEDED":
        raise RuntimeError(f"{status['State']}: {status.get('StateChangeReason')}")
    names, rows, token = None, [], None
    while True:  # results come back 1,000 rows a page
        page = athena.get_query_results(QueryExecutionId=qid, **({"NextToken": token} if token else {}))
        names = names or [c["Name"] for c in page["ResultSet"]["ResultSetMetadata"]["ColumnInfo"]]
        rows += [[d.get("VarCharValue") for d in r["Data"]] for r in page["ResultSet"]["Rows"]]
        token = page.get("NextToken")
        if not token:
            break
    if rows and rows[0] == names:
        rows = rows[1:]
    out = pd.DataFrame(rows, columns=names)
    for col in out.columns:  # Athena returns every value as text
        try:
            out[col] = pd.to_numeric(out[col])
        except (ValueError, TypeError):
            pass
    return out


def ensure_role() -> str:
    """An IAM role SageMaker and Step Functions can assume; returns its ARN."""
    iam = emu.client("iam")
    try:
        return iam.get_role(RoleName=ROLE)["Role"]["Arn"]
    except ClientError:
        trust = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "sts:AssumeRole",
                 "Principal": {"Service": ["sagemaker.amazonaws.com", "states.amazonaws.com"]}}]}
        arn = iam.create_role(RoleName=ROLE, AssumeRolePolicyDocument=json.dumps(trust))["Role"]["Arn"]
        iam.put_role_policy(RoleName=ROLE, PolicyName="lab-access", PolicyDocument=json.dumps(
            {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Resource": "*",
             "Action": ["s3:*", "logs:*", "cloudwatch:*", "sagemaker:*"]}]}))
        return arn


def train_default_model(df: pd.DataFrame):
    """Train the credit-default model locally. Returns (model, hold-out AUC, X_test, y_test)."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    X_train, X_test, y_train, y_test = train_test_split(
        df[FEATURES], df.defaulted, test_size=0.25, random_state=7, stratify=df.defaulted)
    model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=500)).fit(X_train, y_train)
    auc = roc_auc_score(y_test, model.predict_proba(X_test)[:, 1])
    return model, float(auc), X_test, y_test

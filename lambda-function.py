"""
Self-healing Lambda for AWS.

Triggers:
  1. CloudWatch alarm delivered via SNS (alarm on EC2 StatusCheckFailed).
  2. HTTP GET (Function URL / API Gateway) with ?view=actions to read the
     recent healing-actions log for the dashboard.

Remediation policy for EC2 StatusCheckFailed:
  attempt 1..MAX_REBOOTS  -> reboot the instance
  attempt MAX_REBOOTS + 1 -> terminate (ASG, if any, launches a replacement)

Every action is written to DynamoDB table ACTIONS_TABLE so the dashboard
can render a timeline.
"""

import json
import os
import time
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError

REGION = os.environ.get("AWS_REGION", "us-east-1")
ACTIONS_TABLE = os.environ.get("ACTIONS_TABLE", "self-healing-actions")
MAX_REBOOTS = int(os.environ.get("MAX_REBOOTS", "2"))
ESCALATION_TOPIC_ARN = os.environ.get("ESCALATION_TOPIC_ARN")  # optional SNS topic

ec2 = boto3.client("ec2", region_name=REGION)
sns = boto3.client("sns", region_name=REGION)
_table = boto3.resource("dynamodb", region_name=REGION).Table(ACTIONS_TABLE)


# ---------- helpers ----------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record_action(instance_id: str, action: str, reason: str, outcome: str) -> dict:
    item = {
        "instance_id": instance_id,
        "timestamp": _now_iso(),
        "action": action,
        "reason": reason,
        "outcome": outcome,
    }
    _table.put_item(Item=item)
    return item


def _reboot_count_in_last_hour(instance_id: str) -> int:
    cutoff = time.time() - 3600
    resp = _table.query(
        KeyConditionExpression="instance_id = :i",
        ExpressionAttributeValues={":i": instance_id},
        ScanIndexForward=False,
        Limit=25,
    )
    count = 0
    for item in resp.get("Items", []):
        try:
            ts = datetime.fromisoformat(item["timestamp"]).timestamp()
        except ValueError:
            continue
        if ts < cutoff:
            break
        if item.get("action") == "reboot" and item.get("outcome") == "ok":
            count += 1
    return count


def _escalate(subject: str, body: dict) -> None:
    if not ESCALATION_TOPIC_ARN:
        return
    sns.publish(
        TopicArn=ESCALATION_TOPIC_ARN,
        Subject=subject[:100],
        Message=json.dumps(body, default=str, indent=2),
    )


# ---------- remediation ------------------------------------------------------

def _remediate_ec2(instance_id: str, reason: str) -> dict:
    prior_reboots = _reboot_count_in_last_hour(instance_id)

    if prior_reboots < MAX_REBOOTS:
        try:
            ec2.reboot_instances(InstanceIds=[instance_id])
            action = _record_action(instance_id, "reboot", reason, "ok")
        except ClientError as e:
            action = _record_action(instance_id, "reboot", reason, f"error:{e.response['Error']['Code']}")
        return action

    # Escalate to terminate — ASG (if attached) will replace it.
    try:
        ec2.terminate_instances(InstanceIds=[instance_id])
        action = _record_action(instance_id, "terminate", reason, "ok")
        _escalate(
            f"[self-healing] terminated {instance_id}",
            {"instance_id": instance_id, "reason": reason, "prior_reboots": prior_reboots},
        )
    except ClientError as e:
        action = _record_action(
            instance_id, "terminate", reason, f"error:{e.response['Error']['Code']}"
        )
        _escalate(f"[self-healing] FAILED to terminate {instance_id}", action)
    return action


# ---------- event parsing ----------------------------------------------------

def _parse_alarm(event: dict) -> dict | None:
    """Extract {instance_id, alarm_name, reason} from an SNS-wrapped CloudWatch alarm."""
    records = event.get("Records") or []
    if not records:
        return None
    try:
        msg = json.loads(records[0]["Sns"]["Message"])
    except (KeyError, json.JSONDecodeError):
        return None

    dims = (msg.get("Trigger") or {}).get("Dimensions") or []
    instance_id = next((d["value"] for d in dims if d.get("name") == "InstanceId"), None)
    if not instance_id:
        return None

    return {
        "instance_id": instance_id,
        "alarm_name": msg.get("AlarmName", "unknown"),
        "reason": msg.get("NewStateReason", "alarm fired"),
        "new_state": msg.get("NewStateValue", "ALARM"),
    }


def _is_dashboard_request(event: dict) -> bool:
    qs = event.get("queryStringParameters") or {}
    return qs.get("view") == "actions"


def _recent_actions(limit: int = 50) -> list[dict]:
    resp = _table.scan(Limit=limit)
    items = resp.get("Items", [])
    items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return [_decimal_safe(i) for i in items[:limit]]


def _decimal_safe(item: dict) -> dict:
    return {k: (float(v) if isinstance(v, Decimal) else v) for k, v in item.items()}


# ---------- entrypoint -------------------------------------------------------

def lambda_handler(event, context):
    # Dashboard read path
    if _is_dashboard_request(event):
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"actions": _recent_actions()}),
        }

    # Alarm remediation path
    alarm = _parse_alarm(event)
    if not alarm:
        return {"statusCode": 400, "body": "unrecognized event"}

    if alarm["new_state"] != "ALARM":
        return {"statusCode": 200, "body": f"ignored state {alarm['new_state']}"}

    result = _remediate_ec2(alarm["instance_id"], f"{alarm['alarm_name']}: {alarm['reason']}")
    return {"statusCode": 200, "body": json.dumps(result)}

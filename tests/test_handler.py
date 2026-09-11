"""Offline tests for the self-healing Lambda.

The module's boto3 clients are replaced with mocks after import so no
AWS calls happen. Covers event parsing, dashboard routing, and the
reboot -> terminate escalation policy.
"""

import importlib.util
import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock


HERE = os.path.dirname(os.path.abspath(__file__))
LAMBDA_PATH = os.path.join(HERE, "..", "lambda-function.py")


def load_module():
    spec = importlib.util.spec_from_file_location("lambda_function", LAMBDA_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeTable:
    def __init__(self, items=None):
        self.items = list(items or [])
        self.put_calls = []

    def put_item(self, Item):
        self.put_calls.append(Item)
        self.items.append(Item)

    def query(self, **kwargs):
        return {"Items": list(reversed(self.items))}

    def scan(self, **kwargs):
        return {"Items": self.items}


def iso_offset(seconds):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def alarm_event(instance_id, state="ALARM"):
    return {
        "Records": [{
            "Sns": {
                "Message": json.dumps({
                    "AlarmName": "test",
                    "NewStateValue": state,
                    "NewStateReason": "test",
                    "Trigger": {"Dimensions": [{"name": "InstanceId", "value": instance_id}]},
                })
            }
        }]
    }


class TestSelfHealing(unittest.TestCase):
    def setUp(self):
        os.environ["ACTIONS_TABLE"] = "test-actions"
        os.environ["MAX_REBOOTS"] = "2"
        sys.modules.pop("lambda_function", None)
        self.mod = load_module()
        self.table = FakeTable()
        self.ec2 = MagicMock()
        self.sns = MagicMock()
        self.mod._table = self.table
        self.mod.ec2 = self.ec2
        self.mod.sns = self.sns

    def _with_history(self, prior):
        self.table = FakeTable(prior)
        self.mod._table = self.table

    def test_alarm_triggers_reboot(self):
        with open(os.path.join(HERE, "..", "events", "ec2-alarm.json")) as f:
            event = json.load(f)
        result = self.mod.lambda_handler(event, None)
        self.assertEqual(result["statusCode"], 200)
        self.ec2.reboot_instances.assert_called_once_with(InstanceIds=["i-0123456789abcdef0"])
        self.assertEqual(len(self.table.put_calls), 1)
        self.assertEqual(self.table.put_calls[0]["action"], "reboot")

    def test_after_max_reboots_terminates(self):
        self._with_history([
            {"instance_id": "i-abc", "timestamp": iso_offset(-60), "action": "reboot", "outcome": "ok"},
            {"instance_id": "i-abc", "timestamp": iso_offset(-30), "action": "reboot", "outcome": "ok"},
        ])
        self.mod.lambda_handler(alarm_event("i-abc"), None)
        self.ec2.terminate_instances.assert_called_once_with(InstanceIds=["i-abc"])
        self.ec2.reboot_instances.assert_not_called()

    def test_dashboard_returns_actions(self):
        self._with_history([
            {"instance_id": "i-x", "timestamp": iso_offset(-5),
             "action": "reboot", "outcome": "ok", "reason": "r"}
        ])
        res = self.mod.lambda_handler({"queryStringParameters": {"view": "actions"}}, None)
        self.assertEqual(res["statusCode"], 200)
        body = json.loads(res["body"])
        self.assertEqual(len(body["actions"]), 1)
        self.assertEqual(body["actions"][0]["instance_id"], "i-x")

    def test_ok_state_ignored(self):
        res = self.mod.lambda_handler(alarm_event("i-xyz", state="OK"), None)
        self.assertEqual(res["statusCode"], 200)
        self.ec2.reboot_instances.assert_not_called()

    def test_unknown_event_400(self):
        res = self.mod.lambda_handler({"foo": "bar"}, None)
        self.assertEqual(res["statusCode"], 400)


if __name__ == "__main__":
    unittest.main()

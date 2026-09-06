"""Tests for the visitor-counter Lambda handler.

Uses moto to stand up a fake DynamoDB in-process, so the tests
exercise the real boto3 calls without touching AWS.
"""
import importlib
import json
import os
import sys
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

TABLE_NAME = "serverless-web-application-on-aws"
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def handler(monkeypatch):
    # Give boto3 fake creds + a region so it works fully offline.
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")

    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        ddb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )

        # Import the Lambda file. Its name has a dash, so use importlib.
        sys.path.insert(0, str(ROOT))
        if "lambda_function_module" in sys.modules:
            del sys.modules["lambda_function_module"]
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "lambda_function_module", ROOT / "lambda-function.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        yield mod.lambda_handler, ddb.Table(TABLE_NAME)


def test_first_call_creates_item_and_returns_1(handler):
    fn, _ = handler
    resp = fn({}, None)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == 1


def test_repeated_calls_increment_monotonically(handler):
    fn, _ = handler
    values = [json.loads(fn({}, None)["body"]) for _ in range(5)]
    assert values == [1, 2, 3, 4, 5]


def test_response_includes_permissive_cors_header(handler):
    fn, _ = handler
    resp = fn({}, None)
    assert resp["headers"]["Access-Control-Allow-Origin"] == "*"
    assert resp["headers"]["Content-Type"] == "application/json"


def test_state_persists_in_dynamodb(handler):
    fn, table = handler
    for _ in range(3):
        fn({}, None)
    item = table.get_item(Key={"id": "0"})["Item"]
    assert int(item["views"]) == 3

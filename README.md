# AWS Self-Healing Infrastructure

An event-driven controller on AWS that watches CloudWatch alarms and **auto-remediates unhealthy EC2 instances** — reboot first, terminate if reboots don't stick, escalate to a human via SNS only when auto-recovery has been exhausted. Every action is written to DynamoDB so a small static dashboard can render the healing timeline.

## How it works

```
CloudWatch alarm (StatusCheckFailed) ──► SNS ──► Lambda (this repo)
                                                    │
                                       ┌────────────┴────────────┐
                                       ▼                         ▼
                             reboot instance             log action → DynamoDB
                             (up to MAX_REBOOTS)
                                       │
                                       ▼
                             terminate (ASG replaces)
                                       │
                                       ▼
                             SNS escalation topic → email
```

The same Lambda serves a **dashboard endpoint** at `GET /?view=actions` that returns the last 50 healing actions as JSON. The static site under `website/` polls it every 30 s.

## Repository layout

```
lambda-function.py            # the healing controller
template.yaml                 # SAM: table, topics, function, function URL
events/
  ec2-alarm.json              # sample SNS-wrapped CloudWatch alarm
  dashboard.json              # sample dashboard request
tests/
  test_handler.py             # offline tests (boto3 mocked)
website/
  index.html style.css script.js config.js
.github/workflows/ci.yml      # py_compile + unit tests + cfn-lint
requirements.txt
```

## Remediation policy

| Attempts on the same instance in the last hour | Action |
|---|---|
| 0 or 1 successful reboots | **Reboot** the instance |
| ≥ `MAX_REBOOTS` (default 2) | **Terminate** — ASG launches a fresh instance; publish to escalation topic |
| Terminate fails | Escalate immediately with the error payload |

Tunable via environment variables:

| Var | Default | Purpose |
|---|---|---|
| `ACTIONS_TABLE` | `self-healing-actions` | DynamoDB table for the action log |
| `MAX_REBOOTS` | `2` | Reboots per instance per rolling hour before escalating |
| `ESCALATION_TOPIC_ARN` | *(unset)* | Optional SNS topic for human escalation |

## Deploy (SAM)

```bash
sam build
sam deploy --guided \
  --parameter-overrides EscalationEmail=you@example.com
```

Outputs include:
- `AlarmTopicArn` — point your CloudWatch alarms' `AlarmActions` at this
- `DashboardUrl` — public Function URL; append `?view=actions`

### Wiring an EC2 alarm

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name ec2-status-check-failed-i-0abc \
  --metric-name StatusCheckFailed --namespace AWS/EC2 \
  --statistic Maximum --period 60 --evaluation-periods 2 \
  --threshold 1 --comparison-operator GreaterThanOrEqualToThreshold \
  --dimensions Name=InstanceId,Value=i-0abc123... \
  --alarm-actions <AlarmTopicArn>
```

### Wiring the dashboard

Edit `website/config.js` and paste the `DashboardUrl` from the SAM output. Upload `website/` to any static host (S3 + CloudFront works well).

## Local test

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v
```

Or invoke against a sample event with SAM:

```bash
sam local invoke HealerFunction -e events/ec2-alarm.json
sam local invoke HealerFunction -e events/dashboard.json
```

## What's next

- Additional controllers: ELB target replacement, deploy auto-rollback, DynamoDB throttle response
- Per-controller Lambda split (each with its own EventBridge rule)
- Terraform variant of `template.yaml`
- Richer dashboard: alarm map, MTTR chart

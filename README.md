# AWS Self-Healing Infrastructure

An in-progress project exploring **self-healing patterns on AWS** — infrastructure that detects failures, recovers on its own, and reports what happened without a human in the loop.

The idea: build small, composable Lambda-driven controllers that watch CloudWatch signals (alarms, log patterns, metric anomalies) and take corrective action — restart an unhealthy target, roll a bad deploy back, replace a stuck EC2 instance, scale a hot table, page a human only when auto-recovery fails.

## Current state

This repo is at the **scaffold** stage — the runtime (Lambda + DynamoDB + static frontend) is wired up so future controllers have somewhere to live and something to visualize. What's checked in right now:

- `lambda-function.py` — a minimal Lambda handler backed by a DynamoDB table (`serverless-web-application-on-aws`). Today it just increments a `views` counter; it's the template every healing controller will be forked from.
- `website/` — a static frontend (`index.html`, `script.js`, `style.css`) meant to become the ops dashboard: alarm state, recent healing actions, escalation log.
- `.github/workflows/ci.yml` — syntax + asset smoke test.

## Planned controllers

Each is a small Lambda triggered by an EventBridge rule or a CloudWatch alarm.

| Signal | Action |
|---|---|
| EC2 `StatusCheckFailed` | Stop + start the instance; if still bad, terminate so ASG replaces it |
| ELB target failing health checks for N minutes | Deregister, launch replacement, register |
| Deployment error rate spike | Auto-rollback via CodeDeploy `StopDeployment` + previous revision |
| DynamoDB throttled reads | Bump provisioned RCU (or switch to on-demand) |
| Lambda `Errors` alarm | Divert traffic to previous alias version |
| Any of the above escalating | Post to SNS → PagerDuty / Slack |

## Repository layout

```
lambda-function.py          # starter Lambda (will be split per controller)
website/                    # dashboard scaffold (S3 static hosting)
  index.html
  script.js
  style.css
.github/workflows/ci.yml    # CI: py_compile + static asset check
```

## Deploy (current scaffold)

1. **DynamoDB** — table `serverless-web-application-on-aws`, partition key `id` (String); seed `{ id: "0", views: 0 }`.
2. **Lambda** — Python 3.x, paste `lambda-function.py`, attach a role with `dynamodb:GetItem` + `dynamodb:PutItem` on that table.
3. **Endpoint** — expose via Function URL or API Gateway; drop the URL into `website/script.js`.
4. **S3** — bucket with static website hosting, upload `website/`.
5. (Optional) **CloudFront** in front of the bucket for HTTPS + caching.

## Roadmap

- [ ] Move the scaffold Lambda into `controllers/` and split by responsibility
- [ ] IaC (SAM or Terraform) so the stack is reproducible
- [ ] First real controller: EC2 status-check auto-remediation
- [ ] Dashboard: recent alarms + actions taken
- [ ] SNS escalation path

## Notes

The current Lambda uses `boto3`, which ships with the AWS Lambda Python runtime — no packaging needed. If you call the endpoint from a browser on a different origin, enable CORS on the Function URL / API Gateway.

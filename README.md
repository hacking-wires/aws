# Serverless Visitor Counter on AWS

A tiny serverless web app: a static site on S3 that fetches a visitor count from a Lambda function, which increments and returns a counter stored in DynamoDB.

## Architecture

```
Browser ──► S3 (static site) ──► API endpoint ──► Lambda ──► DynamoDB
                                                    │
                                                    └── returns updated view count
```

- **S3** hosts `website/` (`index.html`, `style.css`, `script.js`)
- **Lambda** (`lambda-function.py`) reads the `views` field, increments it, writes it back, returns the new value
- **DynamoDB** table `serverless-web-application-on-aws` with a single item at `id = "0"`

## Repository layout

```
lambda-function.py   # Python 3 Lambda handler
website/             # Static frontend served from S3
  index.html
  script.js
  style.css
```

## Deploy

1. **DynamoDB** — create a table named `serverless-web-application-on-aws` with partition key `id` (String). Seed one item: `{ "id": "0", "views": 0 }`.
2. **Lambda** — create a Python 3.x function, paste `lambda-function.py`, and attach a role with `dynamodb:GetItem` and `dynamodb:PutItem` on the table.
3. **API** — expose the Lambda via Function URL or API Gateway. Copy the invoke URL into `website/script.js`.
4. **S3** — create a bucket, enable static website hosting, and upload the contents of `website/`.
5. (Optional) Front the bucket with **CloudFront** for HTTPS and caching.

## Local check

```bash
python3 -c "import ast; ast.parse(open('lambda-function.py').read())"
```

## Notes

- The Lambda uses `boto3`, which is already available in the AWS Lambda Python runtime — no packaging needed.
- CORS: if calling from a browser on a different origin, enable CORS on API Gateway or the Function URL.

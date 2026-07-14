# Medexa AWS Deployment (Phase 1)

Industry target: **long-lived App Runner** hosting the existing FastAPI process.

| Layer | Service | Why |
|-------|---------|-----|
| API host | AWS App Runner | Same Path A/B/C process model; no Lambda timeout / fire-and-forget breakage |
| Auth to AWS APIs | IAM **instance role** | No static `AWS_ACCESS_KEY_ID` on the service |
| Path B / Path C | Amazon Bedrock Haiku 4.5 | Locked via env (`MEDEXA_*_PROVIDER=bedrock`) |
| Session state | DynamoDB `medexa-sessions` | Already exists in this account |
| Objects | S3 `medexa-storage` | Already exists |
| STT | Deepgram (Secrets Manager) | Keep current ambient UX; Transcribe streaming is Phase 2 |
| Frontend | Vercel | Point `NEXT_PUBLIC_MEDEXA_API_URL` at App Runner HTTPS URL |

## What we deliberately are NOT doing in Phase 1

- Pure Lambda + API Gateway for the live session API (breaks Path B `asyncio.create_task`)
- Rewriting Path A rules into Lambda
- Amazon Transcribe streaming (diagram step — later)
- HealthScribe

## Prerequisites

1. An IAM principal that can deploy CloudFormation (not the locked-down `region2-app-user` boundary alone).
   Attach `deploy/iam/deployer-permissions.json` to an admin/deployer user **or** expand the permissions boundary.
2. Docker **or** GitHub Actions (recommended — builds in the cloud).
3. Deepgram API key for ambient STT.

`region2-app-user` today: Bedrock + DynamoDB + S3 ✅ · ECR / App Runner / CloudFormation / IAM ❌

## Deploy steps

### 1) Bootstrap data plane (already partially done)

```powershell
$env:MEDEXA_AWS_REGION = "us-east-2"
python scripts/aws_bootstrap.py --bucket medexa-storage
```

### 2) Create infra stack (ECR + IAM + secrets) — once

Run as **admin/deployer** (permissions expanded):

```powershell
.\scripts\deploy_aws.ps1 -Action infra `
  -Environment staging `
  -Region us-east-2 `
  -CorsAllowOrigins "https://YOUR-APP.vercel.app,http://localhost:3000" `
  -DeepgramApiKey "dg_xxx"
```

This uses `ExistingDynamoTableName=medexa-sessions` and `ExistingS3BucketName=medexa-storage`.

### 3) Build & push image (GitHub Actions preferred)

- Push to `main` with `.github/workflows/deploy-aws.yml`
- Or locally (Docker required):

```powershell
.\scripts\deploy_aws.ps1 -Action image -Environment staging -Region us-east-2
```

### 4) Enable App Runner service

```powershell
.\scripts\deploy_aws.ps1 -Action service -Environment staging -Region us-east-2
```

### 5) Point frontend

Set Vercel env:

```env
NEXT_PUBLIC_MEDEXA_API_URL=https://xxxxx.us-east-2.awsapprunner.com
```

### 6) Verify

```text
GET https://xxxxx.us-east-2.awsapprunner.com/health
GET https://xxxxx.us-east-2.awsapprunner.com/health/bedrock
```

Expect `path_b.ok` and `path_c.ok` both `true`, and finalize `documentationSource: bedrock`.

## Security model

- App Runner assumes `medexa-apprunner-instance-*` → Bedrock / DynamoDB / S3 only
- Deepgram key lives in Secrets Manager → injected as `MEDEXA_DEEPGRAM_API_KEY`
- No Bedrock access keys stored in HF or App Runner env
- S3 public access blocked; DynamoDB SSE + TTL enabled

## Rollback

- App Runner: deploy previous ECR image tag
- Keep HF Space as emergency backend only if Vercel URL is switched back

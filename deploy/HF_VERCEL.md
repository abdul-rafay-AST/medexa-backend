# Vercel frontend + Hugging Face Space backend

This is the **current production demo path** until App Runner IAM is unlocked.

```
Vercel (medexa-fe) ──► HF Space (medexa-backend FastAPI)
                              ├── Path A: rules
                              ├── Path B: Bedrock → Groq failover
                              ├── Path C: Bedrock → Groq failover
                              └── Ambient STT: Amazon Transcribe → Deepgram failover
```

## Why failover exists

HF Spaces run from cloud IPs. Your `region2-app-user` Bedrock policy can **deny**
those IPs. Local laptop Bedrock still works. Failover keeps Vercel usable:

| Feature | Preference | If blocked on HF |
|---------|------------|------------------|
| Path B / Path C | Bedrock Haiku 4.5 | Groq |
| Ambient STT | Amazon Transcribe | Deepgram Nova-3 Medical |

## HF Space secrets / variables (set then Restart Space)

### Secrets
| Name | Value |
|------|--------|
| `AWS_ACCESS_KEY_ID` | IAM access key |
| `AWS_SECRET_ACCESS_KEY` | IAM secret |
| `MEDEXA_GROQ_API_KEY` | Groq key (Path B/C failover) |
| `MEDEXA_DEEPGRAM_API_KEY` | Deepgram key (STT failover) |

### Variables
| Name | Value |
|------|--------|
| `MEDEXA_AWS_REGION` | `us-east-2` |
| `MEDEXA_USE_DYNAMODB` | `false` (Space: single instance / in-memory or file OK) |
| `MEDEXA_S3_BUCKET` | `medexa-storage` |
| `MEDEXA_TRANSCRIBE_S3_BUCKET` | `medexa-storage` |
| `MEDEXA_CONFIG_SOURCE` | `local` |
| `MEDEXA_PATH_B_ENABLED` | `true` |
| `MEDEXA_PATH_B_PROVIDER` | `bedrock` |
| `MEDEXA_PATH_B_MODEL_ID` | `us.anthropic.claude-haiku-4-5-20251001-v1:0` |
| `MEDEXA_SOAP_GENERATOR` | `bedrock` |
| `MEDEXA_SUMMARY_GENERATOR` | `bedrock` |
| `MEDEXA_PATH_C_MODEL_ID` | `us.anthropic.claude-haiku-4-5-20251001-v1:0` |
| `MEDEXA_TRANSCRIPTION_PROVIDER` | `aws_transcribe` |
| `MEDEXA_TRANSCRIBE_ENABLE_SPEAKER_LABELS` | `true` |
| `MEDEXA_TRANSCRIBE_MAX_SPEAKERS` | `2` |
| `MEDEXA_DEEPGRAM_MODEL` | `nova-3-medical` |
| `MEDEXA_CORS_ALLOW_ORIGINS` | `https://YOUR-APP.vercel.app,http://localhost:3000` |

## Frontend (Vercel)

```env
NEXT_PUBLIC_MEDEXA_API_URL=https://abdul-rafay-ast-medexa-backend.hf.space
```

Already set in `frontend/.env.production`. Redeploy Vercel after pushing `medexa-fe`.

## Verify after Space restart

```text
https://abdul-rafay-ast-medexa-backend.hf.space/health
https://abdul-rafay-ast-medexa-backend.hf.space/health/bedrock
https://abdul-rafay-ast-medexa-backend.hf.space/health/transcribe
```

Then open the Vercel app → start session → ambient + chat → finalize.

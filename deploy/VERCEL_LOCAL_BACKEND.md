# Hybrid: local Bedrock backend + Vercel frontend

Vercel **cannot** call `http://localhost:8000` on your laptop.
You must expose the local API with a public HTTPS tunnel.

```
Vercel FE  ──HTTPS──►  ngrok/cloudflare tunnel  ──►  localhost:8000
                                                    Bedrock + Transcribe
```

## 1) Local backend (`.env`)

```env
MEDEXA_PATH_B_ENABLED=true
MEDEXA_PATH_B_PROVIDER=bedrock
MEDEXA_SOAP_GENERATOR=bedrock
MEDEXA_SUMMARY_GENERATOR=bedrock
# Prefer Deepgram for live ambient (batch Transcribe is 15–90s and breaks UX).
MEDEXA_TRANSCRIPTION_PROVIDER=deepgram
MEDEXA_S3_BUCKET=medexa-storage
MEDEXA_TRANSCRIBE_S3_BUCKET=medexa-storage
MEDEXA_AWS_REGION=us-east-2
MEDEXA_CORS_ALLOW_ORIGINS=*
```

```powershell
python scripts/run_api_server.py
```

## 2) Tunnel

```powershell
ngrok http 8000
# or: cloudflared tunnel --url http://localhost:8000
```

Copy the `https://….ngrok-free.app` URL.

## 3) Vercel env

```env
NEXT_PUBLIC_MEDEXA_API_URL=https://YOUR-TUNNEL.ngrok-free.app
```

Redeploy Vercel (or wait for env update).

## 4) Verify

- `https://YOUR-TUNNEL/.../health/bedrock`
- `https://YOUR-TUNNEL/.../health/transcribe`
- Then use the Vercel site (ambient + Path A/B/C).

**Keep the tunnel running** while testing. HF Space is optional; this hybrid does not need HF for Path B/C/Transcribe.

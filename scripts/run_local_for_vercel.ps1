<#
.SYNOPSIS
  Start Medexa API locally for Vercel testing (Bedrock + Amazon Transcribe).

Vercel cannot reach localhost. After the API is up, run a tunnel in another
terminal and set NEXT_PUBLIC_MEDEXA_API_URL on Vercel to the HTTPS tunnel URL.

See deploy/VERCEL_LOCAL_BACKEND.md
#>
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "Starting Medexa API on http://0.0.0.0:8000 ..."
Write-Host "Providers expected from .env: Path B/C = bedrock, STT = aws_transcribe"
Write-Host ""
Write-Host "In a SECOND terminal, expose the API:"
Write-Host "  cloudflared tunnel --url http://localhost:8000"
Write-Host "  # or: npx --yes localtunnel --port 8000"
Write-Host ""
Write-Host "Then set Vercel env NEXT_PUBLIC_MEDEXA_API_URL=<https tunnel url> and redeploy."
Write-Host ""

python scripts/run_api_server.py

<#
.SYNOPSIS
  Medexa AWS Phase-1 deploy helper (App Runner + ECR).

.PARAMETER Action
  infra   - Create/update CloudFormation (ECR, IAM, Secrets). CreateAppRunnerService=false
  image   - Build + push Docker image to ECR (requires Docker)
  service - Update stack with CreateAppRunnerService=true
  status  - Print stack outputs / health

.EXAMPLE
  .\scripts\deploy_aws.ps1 -Action infra -CorsAllowOrigins "https://app.vercel.app" -DeepgramApiKey "..."
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [ValidateSet("infra", "image", "service", "status")]
  [string]$Action,

  [string]$Environment = "staging",
  [string]$Region = "us-east-2",
  [string]$StackName = "",
  [string]$CorsAllowOrigins = "http://localhost:3000",
  [string]$DeepgramApiKey = "",
  [string]$ImageTag = "latest",
  [string]$ExistingDynamoTableName = "medexa-sessions",
  [string]$ExistingS3BucketName = "medexa-storage"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $StackName) { $StackName = "medexa-apprunner-$Environment" }
$Template = Join-Path $Root "deploy\cloudformation\medexa-apprunner.yaml"

function Get-AccountId {
  return (aws sts get-caller-identity --query Account --output text --region $Region).Trim()
}

function Deploy-Stack([string]$CreateService) {
  if (-not (Test-Path $Template)) { throw "Missing template: $Template" }

  $params = @(
    "ParameterKey=EnvironmentName,ParameterValue=$Environment",
    "ParameterKey=CorsAllowOrigins,ParameterValue=$CorsAllowOrigins",
    "ParameterKey=ExistingDynamoTableName,ParameterValue=$ExistingDynamoTableName",
    "ParameterKey=ExistingS3BucketName,ParameterValue=$ExistingS3BucketName",
    "ParameterKey=ImageTag,ParameterValue=$ImageTag",
    "ParameterKey=CreateAppRunnerService,ParameterValue=$CreateService",
    "ParameterKey=CreateGithubOidcProvider,ParameterValue=false"
  )
  if ($DeepgramApiKey) {
    $params += "ParameterKey=DeepgramApiKey,ParameterValue=$DeepgramApiKey"
  }

  $exists = $false
  try {
    aws cloudformation describe-stacks --stack-name $StackName --region $Region | Out-Null
    $exists = $true
  } catch {
    $exists = $false
  }

  if ($exists) {
    Write-Host "Updating stack $StackName ..."
    aws cloudformation update-stack `
      --stack-name $StackName `
      --region $Region `
      --template-body "file://$Template" `
      --capabilities CAPABILITY_NAMED_IAM `
      --parameters $params
    aws cloudformation wait stack-update-complete --stack-name $StackName --region $Region
  } else {
    Write-Host "Creating stack $StackName ..."
    aws cloudformation create-stack `
      --stack-name $StackName `
      --region $Region `
      --template-body "file://$Template" `
      --capabilities CAPABILITY_NAMED_IAM `
      --parameters $params
    aws cloudformation wait stack-create-complete --stack-name $StackName --region $Region
  }
  Write-Host "Stack $StackName ready."
}

function Push-Image {
  $account = Get-AccountId
  $repo = "medexa-api-$Environment"
  $uri = "$account.dkr.ecr.$Region.amazonaws.com/$repo"

  if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker is not installed. Use GitHub Actions (.github/workflows/deploy-aws.yml) or install Docker Desktop."
  }

  Write-Host "Logging into ECR $uri ..."
  aws ecr get-login-password --region $Region | docker login --username AWS --password-stdin "$account.dkr.ecr.$Region.amazonaws.com"

  Push-Location $Root
  try {
    docker build -t "${repo}:${ImageTag}" .
    docker tag "${repo}:${ImageTag}" "${uri}:${ImageTag}"
    docker push "${uri}:${ImageTag}"
  } finally {
    Pop-Location
  }
  Write-Host "Pushed ${uri}:${ImageTag}"
}

function Show-Status {
  aws cloudformation describe-stacks --stack-name $StackName --region $Region `
    --query "Stacks[0].Outputs" --output table

  $url = aws cloudformation describe-stacks --stack-name $StackName --region $Region `
    --query "Stacks[0].Outputs[?OutputKey=='AppRunnerServiceUrl'].OutputValue" --output text 2>$null
  if ($url -and $url -ne "None") {
    Write-Host "`nHealth:"
    try {
      Invoke-RestMethod "https://$url/health" | ConvertTo-Json -Depth 5
      Invoke-RestMethod "https://$url/health/bedrock" -TimeoutSec 40 | ConvertTo-Json -Depth 6
    } catch {
      Write-Host "Service URL not reachable yet: $_"
    }
  }
}

switch ($Action) {
  "infra" { Deploy-Stack -CreateService "false"; Show-Status }
  "image" { Push-Image }
  "service" { Deploy-Stack -CreateService "true"; Show-Status }
  "status" { Show-Status }
}

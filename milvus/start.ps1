$ErrorActionPreference = 'Stop'

$composeFile = Join-Path $PSScriptRoot 'docker-compose.yml'
$composeUrl = 'https://github.com/milvus-io/milvus/releases/download/v2.6.25/milvus-standalone-docker-compose.yml'

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker CLI is not installed. Install Docker Desktop with the WSL 2 backend first.'
}

try {
    docker info --format '{{.ServerVersion}}' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Docker engine is not responding.' }
} catch {
    throw 'Start Docker Desktop and wait until its status says the engine is running, then run this script again.'
}

if (-not (Test-Path -LiteralPath $composeFile)) {
    Write-Host 'Downloading the official Milvus 2.6.25 standalone Compose configuration…'
    Invoke-WebRequest -Uri $composeUrl -OutFile $composeFile
}

docker compose -f $composeFile up -d
if ($LASTEXITCODE -ne 0) { throw 'Milvus did not start. Check Docker Desktop and run docker compose logs.' }
docker compose -f $composeFile ps
Write-Host 'Milvus should become available at http://localhost:19530. Web UI: http://localhost:9091/webui/'

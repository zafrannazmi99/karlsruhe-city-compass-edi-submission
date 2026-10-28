$ErrorActionPreference = 'Stop'
$composeFile = Join-Path $PSScriptRoot 'docker-compose.yml'
if (-not (Test-Path -LiteralPath $composeFile)) {
    Write-Host 'No local Milvus Compose file found; nothing to stop.'
    exit 0
}
docker compose -f $composeFile down
if ($LASTEXITCODE -ne 0) { throw 'Could not stop the Milvus containers.' }
Write-Host 'Milvus stopped. Its indexed data remains in milvus/volumes for the next run.'

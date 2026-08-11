param(
    [string]$Server = "jushu-prod"
)

$ErrorActionPreference = "Stop"
$commit = (git rev-parse HEAD).Trim()
if (-not $commit) { throw "Unable to resolve the local Git commit." }

$remote = @"
set -euo pipefail
cd /home/ubuntu/social-ops-center
git fetch origin main
git pull --ff-only origin main
test "`$(git rev-parse HEAD)" = "$commit"
docker compose --profile production up -d --build
docker compose --profile production ps
curl -fsS https://app.duanju.chat/api/health >/dev/null
printf 'DEPLOYED_COMMIT='
git rev-parse --short HEAD
"@

& ssh $Server $remote
if ($LASTEXITCODE -ne 0) { throw "Production deployment failed." }

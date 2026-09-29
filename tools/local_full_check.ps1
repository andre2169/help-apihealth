$ErrorActionPreference = "Stop"

$apiRoot = Split-Path $PSScriptRoot -Parent
$frontendRoot = Join-Path (Split-Path $apiRoot -Parent) "helphealth-web"

function Assert-LastExitCode {
    param([string]$Step)
    if ($LASTEXITCODE -ne 0) {
        throw "A etapa '$Step' falhou com codigo $LASTEXITCODE."
    }
}

Write-Host "[1/2] Verificacoes da API"
& powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "local_security_check.ps1")
Assert-LastExitCode "verificacoes da API"

if (-not (Test-Path (Join-Path $frontendRoot "package.json"))) {
    throw "Frontend nao encontrado em $frontendRoot"
}

Write-Host "[2/2] Lint e build do frontend"
Push-Location $frontendRoot
try {
    & npm run check
    Assert-LastExitCode "lint e build do frontend"
}
finally {
    Pop-Location
}

Write-Host "Verificacoes locais completas concluidas."

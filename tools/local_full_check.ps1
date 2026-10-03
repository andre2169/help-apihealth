param([switch]$IncludeBrowserTests)

$ErrorActionPreference = "Stop"

$apiRoot = Split-Path $PSScriptRoot -Parent
$frontendRoot = Join-Path (Split-Path $apiRoot -Parent) "helphealth-web"

function Assert-LastExitCode {
    param([string]$Step)
    if ($LASTEXITCODE -ne 0) {
        throw "A etapa '$Step' falhou com codigo $LASTEXITCODE."
    }
}

if (-not (Test-Path (Join-Path $frontendRoot "package.json"))) {
    throw "Frontend nao encontrado em $frontendRoot"
}

Write-Host "[1/3] Testes e seguranca da API"
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "local_security_check.ps1")
Assert-LastExitCode "verificacoes da API"

Write-Host "[2/3] Lint, testes e build do frontend"
Push-Location $frontendRoot
try {
    & npm run check
    Assert-LastExitCode "lint, testes e build do frontend"

    Write-Host "[3/3] Auditoria das dependencias do frontend"
    & npm audit
    Assert-LastExitCode "npm audit"

    if ($IncludeBrowserTests) {
        $previousBrowserEnv = @{}
        foreach ($name in @("UI_TEST_SERVE_DIST", "UI_TEST_BASE_URL", "UI_TEST_DETAIL_ONLY")) {
            $previousBrowserEnv[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
        }
        try {
            $env:UI_TEST_SERVE_DIST = Join-Path $frontendRoot "dist"
            $env:UI_TEST_BASE_URL = "http://localhost:5173"
            Remove-Item Env:UI_TEST_DETAIL_ONLY -ErrorAction SilentlyContinue
            Write-Host "[Extra] Interface e PWA com dados simulados (porta 5173 livre)"
            & npm run test:ui
            Assert-LastExitCode "testes de interface"
            & npm run test:pwa
            Assert-LastExitCode "testes de PWA"
        }
        finally {
            foreach ($name in $previousBrowserEnv.Keys) {
                [Environment]::SetEnvironmentVariable($name, $previousBrowserEnv[$name], "Process")
            }
        }
    }
}
finally {
    Pop-Location
}

Write-Host "Verificacoes locais completas concluidas."

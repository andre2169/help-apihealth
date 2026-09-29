$ErrorActionPreference = "Stop"

$localPython = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
$pythonCommand = if (Test-Path $localPython) { $localPython } else { "python" }

function Assert-LastExitCode {
    param([string]$Step)
    if ($LASTEXITCODE -ne 0) {
        throw "A etapa '$Step' falhou com codigo $LASTEXITCODE."
    }
}

Write-Host "[1/4] Testes automatizados"
& $pythonCommand -m pytest -q
Assert-LastExitCode "testes automatizados"

Write-Host "[2/4] Compilacao"
& $pythonCommand -m compileall -q app main.py
Assert-LastExitCode "compilacao"

Write-Host "[3/4] Dependencias instaladas"
& $pythonCommand -m pip check
Assert-LastExitCode "pip check"

Write-Host "[4/4] Auditoria de dependencias"
$auditJob = Start-Job -ScriptBlock {
    param($pythonPath, $requirementsPath)

    $output = & $pythonPath -m pip_audit -r $requirementsPath --progress-spinner off --timeout 15 2>&1
    [pscustomobject]@{
        ExitCode = [int]$LASTEXITCODE
        Output = $output
    }
} -ArgumentList $pythonCommand, (Join-Path $PSScriptRoot "..\requirements-dev.txt")

try {
    if (-not (Wait-Job -Job $auditJob -Timeout 45)) {
        Stop-Job -Job $auditJob
        throw "pip-audit nao respondeu em 45 segundos; a auditoria online foi interrompida."
    }

    $auditResult = Receive-Job -Job $auditJob
    $auditResult.Output | Write-Host
    if ($auditResult.ExitCode -ne 0) {
        throw "A etapa 'pip-audit' falhou com codigo $($auditResult.ExitCode)."
    }
}
finally {
    Remove-Job -Job $auditJob -Force -ErrorAction SilentlyContinue
}

Write-Host "Verificacoes locais de seguranca concluidas."

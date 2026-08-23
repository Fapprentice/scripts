$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

function Invoke-WebSuite([string]$Suite) {
    $originalLocalAppData = $env:LOCALAPPDATA
    $env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $originalLocalAppData "ms-playwright"
    $temp = Join-Path $env:TEMP ("taskverge-verify-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory $temp | Out-Null
    $stdout = Join-Path $temp "server.out"
    $env:LOCALAPPDATA = $temp
    $server = Start-Process python -ArgumentList @("task-panel.pyw", "--ci") -WorkingDirectory $Root -RedirectStandardOutput $stdout -RedirectStandardError (Join-Path $temp "server.err") -WindowStyle Hidden -PassThru
    try {
        for ($i=0; $i -lt 100; $i++) {
            $line = if (Test-Path $stdout) { Get-Content $stdout | Select-String "^CI_URL=" | Select-Object -Last 1 }
            if ($line) { $env:TASKVERGE_TEST_URL = $line.ToString().Substring(7); break }
            Start-Sleep -Milliseconds 100
        }
        if (-not $env:TASKVERGE_TEST_URL) { throw "CI server did not start" }
        python -m pytest $Suite -q
        if ($LASTEXITCODE -ne 0) { throw "$Suite failed" }
    } finally {
        if ($server -and -not $server.HasExited) { Stop-Process $server.Id -Force }
        $env:LOCALAPPDATA = $originalLocalAppData
        Remove-Item Env:TASKVERGE_TEST_URL -ErrorAction SilentlyContinue
        Remove-Item $temp -Recurse -Force -ErrorAction SilentlyContinue
    }
}

python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "unit tests failed" }
Invoke-WebSuite "tests/test_api.py"
Invoke-WebSuite "tests/test_e2e_main_flow.py"
Invoke-WebSuite "tests/test_ui_full_flow.py"

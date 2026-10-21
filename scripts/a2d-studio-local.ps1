param(
    [ValidateSet('Start', 'Stop')]
    [string]$Action = 'Start'
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$script:ProjectRoot = Split-Path -Parent $PSScriptRoot
$script:RunRoot = Join-Path $script:ProjectRoot 'tmp\a2d-runs'
$script:Manifest = $null
$script:ManifestPath = $null
$script:LauncherLog = $null
$script:LaunchedProcesses = New-Object System.Collections.Generic.List[object]

function Write-LauncherLog {
    param([string]$Message)

    $line = '[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss.fff'), $Message
    Add-Content -LiteralPath $script:LauncherLog -Value $line -Encoding UTF8
    Write-Host $Message
}

function Save-Manifest {
    $json = ConvertTo-Json -InputObject $script:Manifest -Depth 6
    Set-Content -LiteralPath $script:ManifestPath -Value $json -Encoding UTF8
}

function Get-BackendPort {
    $port = 8765
    $envPath = Join-Path $script:ProjectRoot '.env'
    if (-not (Test-Path -LiteralPath $envPath)) {
        return $port
    }

    foreach ($line in Get-Content -LiteralPath $envPath) {
        if ($line -match '^\s*BACKEND_PORT\s*=') {
            $rawPort = ($line -replace '^\s*BACKEND_PORT\s*=', '').Split('#')[0].Trim().Trim('"').Trim("'")
            $parsedPort = 0
            if (-not [int]::TryParse($rawPort, [ref]$parsedPort) -or $parsedPort -lt 1 -or $parsedPort -gt 65535) {
                throw 'BACKEND_PORT in .env is not a valid TCP port.'
            }
            return $parsedPort
        }
    }

    return $port
}

function Get-NodeExecutable {
    $command = Get-Command node.exe -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $candidates = @(
        (Join-Path $env:ProgramFiles 'nodejs\node.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\nodejs\node.exe'),
        (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe')
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return $candidate
        }
    }

    throw 'Node.js was not found. Install Node.js or add node.exe to PATH before starting A2D Studio.'
}

function Assert-RequiredFiles {
    param([string[]]$Paths)

    foreach ($path in $Paths) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Required file is missing: $path"
        }
    }
}

function Assert-PortsAvailable {
    param([int[]]$Ports)

    $listeners = @(Get-NetTCPConnection -State Listen -ErrorAction Stop)
    $conflicts = @($listeners | Where-Object { $Ports -contains $_.LocalPort })
    if ($conflicts.Count -eq 0) {
        return
    }

    $details = $conflicts | ForEach-Object {
        'port {0} is owned by PID {1} ({2})' -f $_.LocalPort, $_.OwningProcess, $_.LocalAddress
    }
    throw ('Startup cancelled; existing listener(s): ' + ($details -join '; '))
}

function Start-LoggedProcess {
    param(
        [string]$Name,
        [string]$Executable,
        [string]$Arguments,
        [string]$WorkingDirectory,
        [string]$ExpectedArgument,
        [string]$RuntimePath = ''
    )

    $stdoutPath = Join-Path $script:RunDirectory ($Name + '.stdout.log')
    $stderrPath = Join-Path $script:RunDirectory ($Name + '.stderr.log')
    Write-LauncherLog ("Starting {0}: {1} {2}" -f $Name, $Executable, $Arguments)

    $previousPath = $env:PATH
    if ($RuntimePath) {
        $env:PATH = $RuntimePath + ';' + $previousPath
    }
    try {
        $process = Start-Process -FilePath $Executable `
            -ArgumentList $Arguments `
            -WorkingDirectory $WorkingDirectory `
            -RedirectStandardOutput $stdoutPath `
            -RedirectStandardError $stderrPath `
            -WindowStyle Hidden `
            -PassThru
    }
    finally {
        $env:PATH = $previousPath
    }

    $script:LaunchedProcesses.Add($process)
    $entry = [ordered]@{
        name = $Name
        pid = $process.Id
        executable = [System.IO.Path]::GetFullPath($Executable)
        started_at_utc = $process.StartTime.ToUniversalTime().ToString('o')
        expected_argument = $ExpectedArgument
        stdout = $stdoutPath
        stderr = $stderrPath
        status = 'starting'
    }
    $script:Manifest.services += $entry
    Save-Manifest
    return $process
}

function Wait-ForHttp {
    param(
        [System.Diagnostics.Process]$Process,
        [string]$Name,
        [string]$Url,
        [int]$TimeoutSeconds = 180
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if ($Process.HasExited) {
            throw "$Name exited before becoming ready (exit code $($Process.ExitCode))."
        }

        try {
            $response = Invoke-WebRequest -Uri $Url -TimeoutSec 3 -UseBasicParsing
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) {
                Write-LauncherLog ("{0} ready: HTTP {1} at {2}" -f $Name, $response.StatusCode, $Url)
                return
            }
        }
        catch {
            # The service can refuse connections while loading; keep polling until the deadline.
        }

        Start-Sleep -Seconds 2
    }

    throw "$Name did not become ready within $TimeoutSeconds seconds. See its stdout/stderr logs."
}

function Stop-OwnedProcess {
    param([System.Diagnostics.Process]$Process)

    if (-not $Process.HasExited) {
        $Process.Kill()
        $Process.WaitForExit(5000) | Out-Null
        Write-LauncherLog ("Stopped process PID {0} started by this launcher." -f $Process.Id)
    }
}

function Start-A2DStudio {
    $runId = '{0}-{1}' -f (Get-Date -Format 'yyyyMMdd-HHmmss'), ([guid]::NewGuid().ToString('N').Substring(0, 8))
    $script:RunDirectory = Join-Path $script:RunRoot $runId
    New-Item -ItemType Directory -Path $script:RunDirectory -ErrorAction Stop | Out-Null
    $script:LauncherLog = Join-Path $script:RunDirectory 'launcher.log'
    $script:ManifestPath = Join-Path $script:RunDirectory 'processes.json'
    $script:Manifest = [ordered]@{
        run_id = $runId
        created_at = (Get-Date).ToString('o')
        project_root = $script:ProjectRoot
        status = 'preflight'
        services = @()
    }
    Save-Manifest
    Write-LauncherLog "A2D Studio run $runId"
    Write-LauncherLog "Full service logs: $script:RunDirectory"

    try {
        $gsvRoot = Join-Path (Split-Path -Parent $script:ProjectRoot) 'third_party\GPT-SoVITS-v2pro-20250604'
        $gsvPython = Join-Path $gsvRoot 'runtime\python.exe'
        $gsvConfig = Join-Path $gsvRoot 'GPT_SoVITS\configs\tts_infer.yaml'
        $backendPython = Join-Path $script:ProjectRoot '.venv\Scripts\python.exe'
        $frontendRoot = Join-Path $script:ProjectRoot 'frontend_vue'
        $viteCli = Join-Path $frontendRoot 'node_modules\vite\bin\vite.js'
        $nodeExecutable = Get-NodeExecutable
        $backendPort = Get-BackendPort
        if ($backendPort -ne 8765) {
            throw 'The A2D WebSocket client currently uses backend port 8765; this launcher requires BACKEND_PORT=8765.'
        }

        Assert-RequiredFiles @(
            $gsvPython,
            (Join-Path $gsvRoot 'api_v2.py'),
            $gsvConfig,
            $backendPython,
            $viteCli
        )

        $ports = @(31801, 31802, $backendPort, 5173)
        Assert-PortsAvailable -Ports $ports
        Write-LauncherLog ("Preflight passed. Ports: GSV1=31801, GSV2=31802, backend={0}, frontend=5173." -f $backendPort)

        $oldPythonUtf8 = $env:PYTHONUTF8
        $oldPythonIoEncoding = $env:PYTHONIOENCODING
        $env:PYTHONUTF8 = '1'
        $env:PYTHONIOENCODING = 'utf-8'
        try {
            $gsvArguments = '-u api_v2.py -a 127.0.0.1 -p 31801 -c GPT_SoVITS/configs/tts_infer.yaml'
            $gsv1 = Start-LoggedProcess -Name 'gsv1-31801' -Executable $gsvPython -Arguments $gsvArguments `
                -WorkingDirectory $gsvRoot -ExpectedArgument 'api_v2.py' -RuntimePath (Join-Path $gsvRoot 'runtime')
            Wait-ForHttp -Process $gsv1 -Name 'GSV1' -Url 'http://127.0.0.1:31801/openapi.json'
            $script:Manifest.services[-1].status = 'ready'
            Save-Manifest

            $gsvArguments = '-u api_v2.py -a 127.0.0.1 -p 31802 -c GPT_SoVITS/configs/tts_infer.yaml'
            $gsv2 = Start-LoggedProcess -Name 'gsv2-31802' -Executable $gsvPython -Arguments $gsvArguments `
                -WorkingDirectory $gsvRoot -ExpectedArgument 'api_v2.py' -RuntimePath (Join-Path $gsvRoot 'runtime')
            Wait-ForHttp -Process $gsv2 -Name 'GSV2' -Url 'http://127.0.0.1:31802/openapi.json'
            $script:Manifest.services[-1].status = 'ready'
            Save-Manifest

            $backendArguments = '-u main.py --nogui'
            $backend = Start-LoggedProcess -Name 'backend' -Executable $backendPython -Arguments $backendArguments `
                -WorkingDirectory $script:ProjectRoot -ExpectedArgument 'main.py'
            Wait-ForHttp -Process $backend -Name 'Backend' -Url ("http://127.0.0.1:{0}/openapi.json" -f $backendPort)
            $script:Manifest.services[-1].status = 'ready'
            Save-Manifest

            $viteArguments = '"{0}" --host 127.0.0.1 --port 5173 --strictPort' -f $viteCli
            $frontend = Start-LoggedProcess -Name 'frontend' -Executable $nodeExecutable -Arguments $viteArguments `
                -WorkingDirectory $frontendRoot -ExpectedArgument 'vite.js'
            $studioUrl = 'http://127.0.0.1:5173/studio'
            Wait-ForHttp -Process $frontend -Name 'Frontend' -Url $studioUrl
            $script:Manifest.services[-1].status = 'ready'
        }
        finally {
            $env:PYTHONUTF8 = $oldPythonUtf8
            $env:PYTHONIOENCODING = $oldPythonIoEncoding
        }

        $script:Manifest.status = 'running'
        Save-Manifest
        Write-LauncherLog 'All four services are ready.'
        Write-LauncherLog "Opening A2D Studio: $studioUrl"
        try {
            Start-Process -FilePath $studioUrl -ErrorAction Stop | Out-Null
        }
        catch {
            Write-LauncherLog "Could not open the default browser: $($_.Exception.Message)"
        }
        Write-LauncherLog 'Stop them with stop-a2d-studio.bat.'
        return 0
    }
    catch {
        $script:Manifest.status = 'startup_failed'
        Save-Manifest
        Write-LauncherLog ("Startup failed: {0}" -f $_.Exception.Message)
        $processesToStop = @($script:LaunchedProcesses.ToArray())
        [array]::Reverse($processesToStop)
        foreach ($process in $processesToStop) {
            try {
                Stop-OwnedProcess -Process $process
            }
            catch {
                Write-LauncherLog ("Could not stop PID {0}: {1}" -f $process.Id, $_.Exception.Message)
            }
        }
        Write-LauncherLog "Review launcher.log and each service's stdout/stderr logs in $script:RunDirectory"
        return 1
    }
}

function Stop-A2DStudio {
    if (-not (Test-Path -LiteralPath $script:RunRoot)) {
        Write-Host 'No A2D Studio run logs were found; nothing to stop.'
        return 1
    }

    $trackedRuns = @()
    foreach ($candidateFile in Get-ChildItem -LiteralPath $script:RunRoot -Filter 'processes.json' -File -Recurse) {
        try {
            $candidateManifest = Get-Content -LiteralPath $candidateFile.FullName -Raw | ConvertFrom-Json
            if (@($candidateManifest.services).Count -gt 0) {
                $trackedRuns += [pscustomobject]@{
                    file = $candidateFile
                    manifest = $candidateManifest
                }
            }
        }
        catch {
            Write-Host ("Skipping unreadable manifest {0}: {1}" -f $candidateFile.FullName, $_.Exception.Message)
        }
    }

    $latestTrackedRun = $trackedRuns | Sort-Object { $_.file.LastWriteTime } -Descending | Select-Object -First 1
    if (-not $latestTrackedRun) {
        Write-Host 'No launcher-owned service processes were recorded; nothing to stop.'
        return 0
    }

    $script:ManifestPath = $latestTrackedRun.file.FullName
    $script:LauncherLog = Join-Path $latestTrackedRun.file.DirectoryName 'launcher.log'
    $script:Manifest = $latestTrackedRun.manifest
    Write-LauncherLog ("Stopping run {0} from its recorded process manifest." -f $script:Manifest.run_id)

    $allStopped = $true
    $servicesToStop = @($script:Manifest.services)
    [array]::Reverse($servicesToStop)
    foreach ($service in $servicesToStop) {
        try {
            $processInfo = Get-CimInstance Win32_Process -Filter ("ProcessId = {0}" -f [int]$service.pid) -ErrorAction SilentlyContinue
            if (-not $processInfo) {
                Write-LauncherLog ("{0}: PID {1} is already stopped." -f $service.name, $service.pid)
                $service.status = 'stopped'
                Save-Manifest
                continue
            }

            $sameExecutable = [string]::Equals(
                [System.IO.Path]::GetFullPath($processInfo.ExecutablePath),
                [System.IO.Path]::GetFullPath($service.executable),
                [System.StringComparison]::OrdinalIgnoreCase
            )
            $sameArguments = $processInfo.CommandLine -and $processInfo.CommandLine.Contains([string]$service.expected_argument)
            $actualStart = ([DateTime]$processInfo.CreationDate).ToUniversalTime()
            $recordedStart = ([DateTime]$service.started_at_utc).ToUniversalTime()
            $sameStart = [Math]::Abs(($actualStart - $recordedStart).TotalSeconds) -le 5

            if (-not ($sameExecutable -and $sameArguments -and $sameStart)) {
                Write-LauncherLog ("{0}: PID {1} no longer matches the recorded process identity; left untouched." -f $service.name, $service.pid)
                $allStopped = $false
                continue
            }

            $taskkillOutput = & "$env:WINDIR\System32\taskkill.exe" /PID ([int]$service.pid) /T /F 2>&1
            if ($LASTEXITCODE -ne 0) {
                throw "taskkill failed for PID $($service.pid): $($taskkillOutput -join ' ')"
            }
            Write-LauncherLog ("{0}: stopped recorded process tree rooted at PID {1}." -f $service.name, $service.pid)
            $service.status = 'stopped'
            Save-Manifest
        }
        catch {
            Write-LauncherLog ("{0}: stop failed: {1}" -f $service.name, $_.Exception.Message)
            $allStopped = $false
        }
    }

    if ($allStopped) {
        $script:Manifest.status = 'stopped'
        Save-Manifest
        Write-LauncherLog 'All recorded services are stopped.'
        return 0
    }

    $script:Manifest.status = 'stop_incomplete'
    Save-Manifest
    Write-LauncherLog 'Some processes were left running because their identity did not match or they could not be stopped.'
    return 1
}

if ($Action -eq 'Start') {
    exit (Start-A2DStudio)
}

exit (Stop-A2DStudio)

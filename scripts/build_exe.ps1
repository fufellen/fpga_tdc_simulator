[CmdletBinding()]
param(
    [string]$PythonCommand = "python",
    [switch]$SkipTests,
    [switch]$SkipSmokeTest
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (
    [System.Environment]::OSVersion.Platform -ne
    [System.PlatformID]::Win32NT
) {
    throw "This script builds a Windows executable and must run on Windows."
}

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$venvDirectory = Join-Path $repoRoot ".venv"
$venvPython = Join-Path $venvDirectory "Scripts\python.exe"
$requirements = Join-Path $repoRoot "requirements-exe.txt"
$entryPoint = Join-Path $repoRoot "scripts\fpga_tdc_gui_entry.py"
$sourceDirectory = Join-Path $repoRoot "src"
$fixtureDirectory = Join-Path $repoRoot "fixtures"
$distDirectory = Join-Path $repoRoot "dist"
$artifactDirectory = Join-Path $repoRoot "artifacts"
$canonicalExecutable = Join-Path $distDirectory "FPGA_TDC_Simulator.exe"
$executable = $canonicalExecutable
$systemTempRoot = [System.IO.Path]::GetFullPath(
    [System.IO.Path]::GetTempPath()
).TrimEnd("\")
$temporaryBuildName = (
    "fpga-tdc-simulator-pyinstaller-" +
    [guid]::NewGuid().ToString("N")
)
$temporaryBuildRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $systemTempRoot $temporaryBuildName)
)
$safeTempPrefix = $systemTempRoot + [System.IO.Path]::DirectorySeparatorChar
if (
    -not $temporaryBuildRoot.StartsWith(
        $safeTempPrefix,
        [System.StringComparison]::OrdinalIgnoreCase
    ) -or
    $temporaryBuildName -notmatch (
        "^fpga-tdc-simulator-pyinstaller-[0-9a-f]{32}$"
    )
) {
    throw "Refusing to use an unsafe temporary build path: $temporaryBuildRoot"
}
$workDirectory = Join-Path $temporaryBuildRoot "work"
$specDirectory = Join-Path $temporaryBuildRoot "spec"
$stagingDistDirectory = Join-Path $temporaryBuildRoot "dist"
$stagedExecutable = Join-Path $stagingDistDirectory "FPGA_TDC_Simulator.exe"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string[]]$ArgumentList
    )

    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath"
    }
}

function Close-CanonicalExecutable {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    $resolved = (Resolve-Path -LiteralPath $Path).Path
    $running = @(
        Get-Process -ErrorAction SilentlyContinue |
            Where-Object {
                $candidate = $null
                try { $candidate = $_.Path } catch { $candidate = $null }
                $candidate -and
                    $candidate.Equals(
                        $resolved,
                        [System.StringComparison]::OrdinalIgnoreCase
                    )
            }
    )
    if ($running.Count -eq 0) {
        return
    }

    Write-Host (
        "The canonical executable is running ({0} process(es)); " -f
        $running.Count
    ) -NoNewline
    Write-Host "requesting normal closure..."
    foreach ($process in $running) {
        try { $process.CloseMainWindow() | Out-Null } catch { }
    }
    Start-Sleep -Seconds 3
    foreach ($process in $running) {
        try {
            $process.Refresh()
            if (-not $process.HasExited) {
                Stop-Process -Id $process.Id -Force -ErrorAction Stop
            }
        }
        catch { }
    }
    Start-Sleep -Seconds 1
}

if (-not (Test-Path -LiteralPath $venvPython)) {
    $pythonCandidates = @(
        Get-Command $PythonCommand -CommandType Application `
            -ErrorAction SilentlyContinue
    )
    if ($pythonCandidates.Count -eq 0) {
        throw (
            "Python was not found. Install Python 3.11 or newer and " +
            "ensure '$PythonCommand' is available in PATH, or pass " +
            "-PythonCommand with the full path to python.exe."
        )
    }

    $python = $null
    foreach ($candidate in $pythonCandidates) {
        & $candidate.Path -c (
            "import sys; raise SystemExit(" +
            "0 if sys.version_info >= (3, 11) else 1)"
        )
        if ($LASTEXITCODE -eq 0) {
            $python = $candidate
            break
        }
    }
    if ($null -eq $python) {
        throw (
            "None of the '$PythonCommand' executables in PATH use Python " +
            "3.11 or newer. Install a supported version or pass its full path."
        )
    }

    Write-Host "Creating build environment: $venvDirectory"
    Invoke-Checked -FilePath $python.Path -ArgumentList @(
        "-m", "venv", $venvDirectory
    )
}

$versionCheckArguments = @(
    "-c",
    "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
)
& $venvPython @versionCheckArguments
if ($LASTEXITCODE -ne 0) {
    throw (
        "The existing build environment does not use Python 3.11 or newer. " +
        "Remove '$venvDirectory' and run this script with a supported Python."
    )
}

Write-Host "Installing the pinned executable build toolchain..."
Invoke-Checked -FilePath $venvPython -ArgumentList @(
    "-m", "pip", "install",
    "-e", "${repoRoot}[gui]",
    "-r", $requirements
)

if (-not $SkipTests) {
    Write-Host "Running project checks..."
    $previousQtPlatform = $env:QT_QPA_PLATFORM
    try {
        $env:QT_QPA_PLATFORM = "offscreen"
        Invoke-Checked -FilePath $venvPython -ArgumentList @(
            (Join-Path $repoRoot "scripts\check.py")
        )
    }
    finally {
        $env:QT_QPA_PLATFORM = $previousQtPlatform
    }
}

New-Item -ItemType Directory -Path $specDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $stagingDistDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $distDirectory -Force | Out-Null

Write-Host "Building the standalone Windows executable..."
$dataArgument = $fixtureDirectory + ";fixtures"
try {
    Invoke-Checked -FilePath $venvPython -ArgumentList @(
        "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--windowed",
        "--name", "FPGA_TDC_Simulator",
        "--paths", $sourceDirectory,
        "--add-data", $dataArgument,
        "--distpath", $stagingDistDirectory,
        "--workpath", $workDirectory,
        "--specpath", $specDirectory,
        $entryPoint
    )

    if (-not (Test-Path -LiteralPath $stagedExecutable)) {
        throw (
            "PyInstaller completed without producing the expected file: " +
            $stagedExecutable
        )
    }

    Close-CanonicalExecutable -Path $canonicalExecutable

    try {
        Copy-Item `
            -LiteralPath $stagedExecutable `
            -Destination $canonicalExecutable `
            -Force
    }
    catch {
        $publishError = $_.Exception.Message
        $executable = Join-Path $distDirectory "FPGA_TDC_Simulator.new.exe"
        Copy-Item `
            -LiteralPath $stagedExecutable `
            -Destination $executable `
            -Force
        Write-Warning (
            "The canonical executable is probably open and could not be " +
            "replaced: $publishError`nThe new build was published as " +
            "'$executable'."
        )
    }

    if ($executable -eq $canonicalExecutable) {
        $staleFallback = Join-Path `
            $distDirectory `
            "FPGA_TDC_Simulator.new.exe"
        if (Test-Path -LiteralPath $staleFallback) {
            try {
                Remove-Item -LiteralPath $staleFallback -Force
            }
            catch {
                Write-Warning (
                    "Could not remove stale fallback executable at " +
                    "'$staleFallback': $($_.Exception.Message)"
                )
            }
        }
    }
}
finally {
    if (Test-Path -LiteralPath $temporaryBuildRoot) {
        try {
            Remove-Item -LiteralPath $temporaryBuildRoot -Recurse -Force
        }
        catch {
            Write-Warning (
                "Could not remove temporary PyInstaller files at " +
                "'$temporaryBuildRoot': $($_.Exception.Message)"
            )
        }
    }
}

if (-not $SkipSmokeTest) {
    Write-Host "Running the packaged executable smoke test..."
    New-Item -ItemType Directory -Path $artifactDirectory -Force | Out-Null
    $screenshot = Join-Path $artifactDirectory "exe-build-smoke.png"
    if (Test-Path -LiteralPath $screenshot) {
        Remove-Item -LiteralPath $screenshot -Force
    }
    # native Windows platform: offscreen Qt renders Cyrillic as boxes
    $process = Start-Process `
        -FilePath $executable `
        -ArgumentList @(
            "--tab", "line",
            "--screenshot", ('"{0}"' -f $screenshot)
        ) `
        -WorkingDirectory ([System.IO.Path]::GetTempPath()) `
        -Wait `
        -PassThru

    if ($process.ExitCode -ne 0) {
        throw (
            "Packaged executable smoke test failed with exit code " +
            "$($process.ExitCode)."
        )
    }
    if (-not (Test-Path -LiteralPath $screenshot)) {
        throw "Packaged executable did not create the smoke-test screenshot."
    }
}

$file = Get-Item -LiteralPath $executable
$hash = Get-FileHash -LiteralPath $executable -Algorithm SHA256
Write-Host ""
Write-Host "Build complete: $($file.FullName)"
Write-Host ("Size: {0:N2} MiB" -f ($file.Length / 1MB))
Write-Host "SHA-256: $($hash.Hash)"

[CmdletBinding()]
param(
    [string]$RtlDir = "C:\workspace\verilog-fpga-tdc\src\TDC\fpga_tdc",
    [string]$Vsim = "C:\intelFPGA\18.1\modelsim_ase\win32aloem\vsim.exe",
    [string[]]$Configs = @("A", "B", "C")
)

# Runs the reference interval sweep in ModelSim and dumps every vector to
# CSV, so the Python port can be compared point by point instead of only
# by aggregates. The RTL checkout is read-only: sources are pulled in via
# +incdir and every generated file stays under rtl_bridge/.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$bridgeDir = Join-Path $repoRoot "rtl_bridge"
$doFile = Join-Path $bridgeDir "tdc_dump_tb.do"

foreach ($path in @($Vsim, $RtlDir, $doFile)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Not found: $path"
    }
}

$rtlResolved = (Resolve-Path -LiteralPath $RtlDir).Path
$dirtyBefore = & git -C $rtlResolved status --porcelain
if ($LASTEXITCODE -ne 0) { $dirtyBefore = $null }

$env:TDC_RTL_DIR = $rtlResolved -replace "\\", "/"
$env:TDC_BRIDGE_DIR = $bridgeDir -replace "\\", "/"

foreach ($cfg in $Configs) {
    Write-Host "=== ModelSim sweep dump, config $cfg ==="
    $env:TDC_CFG = $cfg
    & $Vsim -batch -do "do `"$($env:TDC_BRIDGE_DIR)/tdc_dump_tb.do`"; quit -f"
    if ($LASTEXITCODE -ne 0) {
        throw "ModelSim failed for config ${cfg} with exit code $LASTEXITCODE"
    }
    $csv = Join-Path $bridgeDir "dumps\modelsim_sweep_$cfg.csv"
    if (-not (Test-Path -LiteralPath $csv)) {
        throw "Config $cfg produced no dump at $csv"
    }
    $lines = (Get-Content -LiteralPath $csv | Measure-Object -Line).Lines
    Write-Host "  $csv : $lines lines"
}

if ($null -ne $dirtyBefore) {
    $dirtyAfter = & git -C $rtlResolved status --porcelain
    if (($dirtyAfter | Out-String) -ne ($dirtyBefore | Out-String)) {
        throw (
            "The read-only RTL checkout was modified by this run. " +
            "Inspect: git -C `"$rtlResolved`" status"
        )
    }
    Write-Host "Reference RTL checkout unchanged."
}

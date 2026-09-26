#requires -Version 5.1
<# Default: offline configuration plan/check, no init. -Execute is reserved for
   the authorized hardware operator: bounded identity reads, no reset/halt or
   memory-write/programming commands. Optional -ReadFlash backs up internal Flash
   only after identity guards; default remains identity-only. #>
param(
    [switch]$Execute,
    [switch]$ReadFlash,
    [string]$OpenOCD = 'D:\STM32CubeIDE\App\STM32CubeIDE\plugins\com.st.stm32cube.ide.mcu.externaltools.openocd.win32_2.4.500.202604080855\tools\bin\openocd.exe',
    [string]$Scripts = 'D:\STM32CubeIDE\App\STM32CubeIDE\plugins\com.st.stm32cube.ide.mcu.debug.openocd_2.3.400.202606220929\resources\openocd\st_scripts',
    [string]$ProbeSerial = '',
    [ValidateRange(100,4000)][int]$SpeedKHz = 1000,
    [ValidateRange(1,60)][int]$TimeoutSeconds = 15,
    [string]$OutputDir = ''
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$config = Join-Path $projectRoot 'Debug\firedap.cfg'
foreach ($path in @($OpenOCD,$config,(Join-Path $Scripts 'interface\cmsis-dap.cfg'),
                    (Join-Path $Scripts 'target\stm32f4x.cfg'))) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing debugger file: $path" }
}
if ($ProbeSerial -notmatch '^[A-Za-z0-9_-]+$') { throw 'ProbeSerial must be an exact alphanumeric fireDAP serial.' }
$OpenOCD = (Resolve-Path -LiteralPath $OpenOCD).Path
$Scripts = (Resolve-Path -LiteralPath $Scripts).Path
if (-not $OutputDir) {
    $OutputDir = Join-Path $projectRoot ('Build\firedap-snapshots\' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
}
$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$flashPath = Join-Path $OutputDir 'target-flash.bin'
if ($ReadFlash -and (Test-Path -LiteralPath $flashPath)) {
    throw 'Refusing an existing target-flash.bin; choose a fresh OutputDir for Flash readback.'
}
$utf8 = [System.Text.UTF8Encoding]::new($false)

# Windows CreateProcess quoting, with no shell/CALL expansion and no Tcl source
# interpolation of paths. Serial is separately restricted before Tcl insertion.
function Quote-ProcessArgument([string]$Value) {
    $escaped = [regex]::Replace($Value, '(\\*)"', '$1$1\"')
    $escaped = [regex]::Replace($escaped, '(\\+)$', '$1$1')
    return '"' + $escaped + '"'
}
function Get-SnapshotSHA256([string]$Path) {
    $algorithm = [System.Security.Cryptography.SHA256]::Create()
    $stream = [System.IO.File]::OpenRead($Path)
    try { return ([BitConverter]::ToString($algorithm.ComputeHash($stream))).Replace('-','').ToLowerInvariant() }
    finally { $stream.Dispose(); $algorithm.Dispose() }
}

$guard = @'
# Override ST examine-end's DBGMCU writes and all active debug hooks BEFORE init.
$_TARGETNAME configure -event examine-end {}
$_TARGETNAME configure -event halted {}
$_TARGETNAME configure -event reset-init {}
$_TARGETNAME configure -event reset-end {}
$_TARGETNAME configure -event gdb-attach {}
$_TARGETNAME configure -event gdb-detach {}
reset_config none
bindto 127.0.0.1
gdb_port disabled
tcl_port disabled
telnet_port disabled
'@
$reads = @'
if {[catch {
    init
    set cpuid [lindex [read_memory 0xE000ED00 32 1] 0]
    set idcode [lindex [read_memory 0xE0042000 32 1] 0]
    set flash_kib [lindex [read_memory 0x1FFF7A22 16 1] 0]
    set vtor [lindex [read_memory 0xE000ED08 32 1] 0]
    set vectors [read_memory 0x08000000 32 2]
    echo [format {GS_SNAPSHOT CPUID=0x%08x} $cpuid]
    echo [format {GS_SNAPSHOT DBGMCU_IDCODE=0x%08x} $idcode]
    echo [format {GS_SNAPSHOT FLASH_KIB=%u} $flash_kib]
    echo [format {GS_SNAPSHOT VTOR=0x%08x} $vtor]
    echo [format {GS_SNAPSHOT FLASH_INITIAL_MSP=0x%08x} [lindex $vectors 0]]
    echo [format {GS_SNAPSHOT FLASH_RESET_VECTOR=0x%08x} [lindex $vectors 1]]
} message]} {
    echo "GS_SNAPSHOT_ERROR $message"
}
shutdown
'@
if ($ReadFlash) {
    # Fixed relative filename: no user-controlled path is inserted into Tcl.
    # Guard again in Tcl immediately before dump_image to reject late collisions.
    $flashReads = @'
    if {$cpuid != 0x410fc241 || ($idcode & 0xfff) != 0x419 || $flash_kib != 1024} {
        error {Flash readback identity guard failed; dump_image not attempted}
    }
    if {[file exists target-flash.bin]} {
        error {Refusing existing target-flash.bin; dump_image not attempted}
    }
    dump_image target-flash.bin 0x08000000 0x00100000
    echo GS_SNAPSHOT_FLASH_COMPLETE
'@
    $reads = $reads.Replace('} message]} {', $flashReads + "`n} message]} {")
}
$planPath = Join-Path $OutputDir 'read-plan.tcl'
[System.IO.File]::WriteAllText($planPath, $guard + "`n" + $reads + "`n", $utf8)
$sessionPath = Join-Path $OutputDir 'session.tcl'
$session = $guard + "`n"
if ($Execute) { $session += $reads } else { $session += "echo GS_SNAPSHOT_PLAN_OK`nshutdown`n" }
[System.IO.File]::WriteAllText($sessionPath, $session + "`n", $utf8)
$arguments = @('-s',$Scripts,'-c',"set GS_DAP_SERIAL {$ProbeSerial}",'-c',"set GS_SWD_KHZ $SpeedKHz",
               '-f',$config,'-f',$sessionPath)
$record = [ordered]@{
    generated_at = (Get-Date).ToString('o')
    mode = $(if ($Execute) { 'execute' } else { 'offline_check' })
    outcome = 'failed'
    hardware_contact_attempted = [bool]$Execute
    readback_observed = $false
    flash_readback_requested = [bool]$ReadFlash
    flash_readback_complete = $false
    flash_readback = $null
    identity_matches_expected = $null
    expected = @{ core='Cortex-M4'; device_id='0x419'; flash_kib=1024 }
    planned_reads = @('CPUID@0xE000ED00/32','DBGMCU_IDCODE@0xE0042000/32','FLASH_KIB@0x1FFF7A22/16',
                     'VTOR@0xE000ED08/32','FLASH_VECTORS@0x08000000/32x2')
    planned_flash_readback = $(if ($ReadFlash) {
        @{ address='0x08000000'; size_bytes=1048576; file='target-flash.bin'; cpuid='0x410fc241' }
    } else { $null })
    readback = $null
    probe_serial = $ProbeSerial
    speed_khz = $SpeedKHz
    timeout_seconds = $TimeoutSeconds
    timed_out = $false
    openocd_exit_code = $null
    openocd_executable = $OpenOCD
    openocd_sha256 = Get-SnapshotSHA256 $OpenOCD
    debugger_config_sha256 = Get-SnapshotSHA256 $config
    openocd_arguments = $arguments
    stdout_log = 'stdout.log'
    stderr_log = 'stderr.log'
    error = $null
    limitations = @('DEV_ID and capacity do not identify package or exact F429/F439 ordering code.',
                    'OpenOCD init/examination can configure the debug subsystem; this is not a guarantee of zero bus writes.',
                    'Flash vectors and VTOR do not prove the current firmware or application execution.')
}
$process = [System.Diagnostics.Process]::new()
$process.StartInfo = [System.Diagnostics.ProcessStartInfo]::new()
$process.StartInfo.FileName = $OpenOCD
$process.StartInfo.Arguments = (($arguments | ForEach-Object { Quote-ProcessArgument $_ }) -join ' ')
$process.StartInfo.UseShellExecute = $false
$process.StartInfo.CreateNoWindow = $true
$process.StartInfo.RedirectStandardOutput = $true
$process.StartInfo.RedirectStandardError = $true
$process.StartInfo.WorkingDirectory = $OutputDir
$started = $false
$stdout = $stderr = ''
try {
    $started = $process.Start()
    if (-not $started) { throw 'OpenOCD process did not start.' }
    $outTask = $process.StandardOutput.ReadToEndAsync()
    $errTask = $process.StandardError.ReadToEndAsync()
    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        $record.timed_out = $true
        $process.Kill()
        if (-not $process.WaitForExit(2000)) { throw 'Timed-out OpenOCD process could not be reaped.' }
    }
    $stdout = $outTask.GetAwaiter().GetResult()
    $stderr = $errTask.GetAwaiter().GetResult()
    $record.openocd_exit_code = $process.ExitCode
    if ($record.timed_out) { throw 'OpenOCD identity snapshot timed out; process terminated.' }
    if ($process.ExitCode -ne 0) { throw "OpenOCD exited with code $($process.ExitCode)." }
    $text = $stdout + "`n" + $stderr
    if ($Execute) {
        if ($text -match 'GS_SNAPSHOT_ERROR') { throw 'OpenOCD reported an identity read error.' }
        $values = [ordered]@{}
        foreach ($field in @('CPUID','DBGMCU_IDCODE','FLASH_KIB','VTOR','FLASH_INITIAL_MSP','FLASH_RESET_VECTOR')) {
            $pattern = $(if ($field -eq 'FLASH_KIB') { '[0-9]{1,5}' } else { '0x[0-9a-fA-F]{8}' })
            $fieldLines = [regex]::Matches($text, "(?m)^GS_SNAPSHOT $field=.*\r?$")
            $matches = [regex]::Matches($text, "(?m)^GS_SNAPSHOT $field=($pattern)\r?$")
            if ($fieldLines.Count -ne 1 -or $matches.Count -ne 1) {
                throw "Expected exactly one valid actual readback for $field; got $($fieldLines.Count) field lines."
            }
            $value = $matches[0].Groups[1].Value
            $values[$field] = $value
        }
        $record.readback = $values
        $record.readback_observed = $true
        $cpuidValue = [Convert]::ToUInt32($values.CPUID.Substring(2),16)
        $deviceValue = [Convert]::ToUInt32($values.DBGMCU_IDCODE.Substring(2),16) -band 0xFFF
        $record.identity_matches_expected = (($cpuidValue -band 0xFF00FFF0L) -eq 0x4100C240L -and
                                             $deviceValue -eq 0x419 -and [int]$values.FLASH_KIB -eq 1024)
        if (-not $record.identity_matches_expected) { throw 'Actual core/device ID/Flash capacity does not match expected F42x/F43x 1024 KiB target.' }
        if ($ReadFlash) {
            if ($cpuidValue -ne 0x410FC241L) { throw 'Flash readback requires the previously verified CPUID 0x410fc241.' }
            $markerLines = [regex]::Matches($text, '(?m)^GS_SNAPSHOT_FLASH_COMPLETE.*\r?$')
            $validMarkers = [regex]::Matches($text, '(?m)^GS_SNAPSHOT_FLASH_COMPLETE\r?$')
            if ($markerLines.Count -ne 1 -or $validMarkers.Count -ne 1) {
                throw 'Expected exactly one valid Flash readback completion marker.'
            }
            if (-not (Test-Path -LiteralPath $flashPath -PathType Leaf)) { throw 'Flash readback file is missing.' }
            $flashFile = Get-Item -LiteralPath $flashPath
            if ($flashFile.Length -ne 1048576) { throw "Flash readback length is $($flashFile.Length), expected 1048576 bytes." }
            $record.flash_readback = @{ file='target-flash.bin'; address='0x08000000';
                size_bytes=$flashFile.Length; sha256=(Get-SnapshotSHA256 $flashPath) }
            $record.flash_readback_complete = $true
        }
        $record.outcome = 'identity_readback_matches'
        if ($ReadFlash) { $record.outcome = 'flash_readback_complete' }
    } else {
        if ($text -notmatch '(?m)^GS_SNAPSHOT_PLAN_OK\r?$') { throw 'Offline configuration completion marker missing.' }
        $record.outcome = 'offline_plan_checked'
    }
} catch {
    $record.error = $_.Exception.Message
} finally {
    if ($started -and -not $process.HasExited) {
        $process.Kill()
        [void]$process.WaitForExit(2000)
    }
    if ($started) {
        if ($outTask.IsCompleted) { $stdout = $outTask.GetAwaiter().GetResult() }
        if ($errTask.IsCompleted) { $stderr = $errTask.GetAwaiter().GetResult() }
    }
    [System.IO.File]::WriteAllText((Join-Path $OutputDir 'stdout.log'), $stdout, $utf8)
    [System.IO.File]::WriteAllText((Join-Path $OutputDir 'stderr.log'), $stderr, $utf8)
    [System.IO.File]::WriteAllText((Join-Path $OutputDir 'result.json'), ($record | ConvertTo-Json -Depth 8) + "`n", $utf8)
    $process.Dispose()
}
if ($record.error) { throw "$($record.error) Result and raw logs: $OutputDir" }
Write-Output "PASS: $($record.outcome). Result and raw logs: $OutputDir"

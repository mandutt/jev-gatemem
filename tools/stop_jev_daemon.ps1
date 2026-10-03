# Stop the live jev-mem core daemon (pythonw hosts only). Restart is a
# separate spawn via the client ensure_core() or a direct spawn command.
$ErrorActionPreference = "Stop"
# Filter guard: bash wrappers embed the WHOLE spawn command string in their
# cmdline, so a naive 'jev_mem_core.*--serve' regex matches them too and
# killing them can break the calling terminal. Name guard excludes them.
# (Measured 2026-10-03: Name -eq 'pythonw.exe' + regex = correct filter.)
$targets = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq 'pythonw.exe' -and $_.CommandLine -match 'jev_mem_core.*--serve'
}
foreach ($p in $targets) {
    Write-Output ("STOP PID={0} NAME={1}" -f $p.ProcessId, $p.Name)
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2
# NOTE: nohup/bash-wrapper cleanup intentionally omitted — the wrapper is the
# calling terminal session itself (Hermes bash -lic); killing it breaks the
# session. The pythonw tree kill above is sufficient; wrapper exits on its own.
Start-Sleep -Seconds 2
Write-Output "TREE_STOPPED"
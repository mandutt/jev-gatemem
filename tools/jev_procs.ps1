$procs = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'jev_mem|jev-mem|jevmem|47821|jev serve' }
if (-not $procs) { Write-Output "NO_JEV_PROCESS_FOUND" } else {
foreach ($p in $procs) {
    Write-Output ("PID={0} NAME={1}`nCMD={2}`n---" -f $p.ProcessId, $p.Name, $p.CommandLine)
}
}
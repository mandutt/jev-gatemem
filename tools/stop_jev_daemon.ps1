# P2a 검증용 데몬 재시작 — 기존 트리(nohup→pythonw)를 정지하고
# 동일한 명령으로 재시작. pythonw 프로세스만 숙주(jev_mem_core --serve) 매치.
$ErrorActionPreference = "Stop"
$targets = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -match 'jev_mem_core.*--serve'
}
foreach ($p in $targets) {
    Write-Output ("STOP PID={0} NAME={1}" -f $p.ProcessId, $p.Name)
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2
# nohup 부모도 정리
$nohup = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'nohup.*jev_mem_core' }
foreach ($p in $nohup) {
    Write-Output ("STOP nohup PID={0}" -f $p.ProcessId)
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2
Write-Output "TREE_STOPPED"
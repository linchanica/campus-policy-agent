param([int]$Port=8000)
$ErrorActionPreference='Stop'
$projectRoot=[System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$recordPath=Join-Path $projectRoot 'work/active-process.json'
if (-not (Test-Path -LiteralPath $recordPath)) { throw '没有可核验的实际服务进程记录，不自动终止任何进程。' }
$record=Get-Content -LiteralPath $recordPath -Raw -Encoding utf8 | ConvertFrom-Json
if ([System.IO.Path]::GetFullPath($record.project) -ne $projectRoot) { throw '进程记录不属于当前项目。' }
$servicePid=[int]$record.pid
$serviceProcess=Get-Process -Id $servicePid -ErrorAction SilentlyContinue
if (-not $serviceProcess) { Write-Output '项目服务进程已结束。'; return }
if ($serviceProcess.ProcessName -ne 'python') { throw 'PID 已被其他程序使用，不终止。' }
$startGap=[Math]::Abs(($serviceProcess.StartTime.ToUniversalTime()-([datetime]$record.started).ToUniversalTime()).TotalSeconds)
if ($startGap -gt 20) { throw 'PID 与启动时刻不一致，不终止。' }
$listeners=@(Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
if (-not ($listeners | Where-Object OwningProcess -eq $servicePid)) { throw '目标端口不是记录中的项目服务，不终止。' }
Stop-Process -Id $servicePid
Write-Output "已停止本项目服务进程 $servicePid。"

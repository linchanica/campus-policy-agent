param([int]$Port=8000)
$ErrorActionPreference='Stop'
$projectRoot=[System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$pythonPath=Join-Path $projectRoot '.venv/Scripts/python.exe'
$workRoot=Join-Path $projectRoot 'work'
New-Item -ItemType Directory -Path $workRoot -Force | Out-Null
if (-not (Test-Path -LiteralPath $pythonPath)) { throw '请先按 README 创建项目虚拟环境并安装依赖。' }
try {
  $health=Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health/ready" -TimeoutSec 2
  if ($health.release_id -eq 'provided-copies-20261030-v1') { Write-Output "项目已运行：http://127.0.0.1:$Port"; return }
} catch { }
$process=Start-Process -FilePath $pythonPath -ArgumentList @('-m','uvicorn','app.api:app','--host','127.0.0.1','--port',"$Port") -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $workRoot 'server.log') -RedirectStandardError (Join-Path $workRoot 'server.err.log') -PassThru
@{pid=$process.Id;port=$Port;project=$projectRoot;started=(Get-Date).ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $workRoot 'server-process.json') -Encoding utf8
Write-Output "已启动项目进程 $($process.Id)，访问 http://127.0.0.1:$Port"

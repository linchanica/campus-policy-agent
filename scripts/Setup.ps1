param([string]$Python='python',[switch]$DownloadModels)
$ErrorActionPreference='Stop'
$projectRoot=[System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Set-Location -LiteralPath $projectRoot
$venvPython=Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    & $Python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw '创建虚拟环境失败；本项目实际验证环境为 Windows Python 3.13。' }
}
& $venvPython -m pip install -r requirements.lock.txt
if ($LASTEXITCODE -ne 0) { throw '依赖安装失败。' }
if ($DownloadModels) {
    & $venvPython scripts/download_local_model.py
    if ($LASTEXITCODE -ne 0) { throw '本地模型下载失败。' }
    & $venvPython -m app.cli index --semantic
} else {
    & $venvPython -m app.cli index
}
if ($LASTEXITCODE -ne 0) { throw '检索索引建立失败。' }
& $venvPython scripts/configure_workbuddy.py
if ($LASTEXITCODE -ne 0) { throw '项目工具配置失败。' }
& $venvPython -m app.cli doctor
if ($LASTEXITCODE -ne 0) { throw '项目检查失败。' }
Write-Output '准备完成。运行 ./scripts/Start.ps1 启动本地服务。未下载模型时只有基线检索与程序规则，不代表语义模型已接入。'

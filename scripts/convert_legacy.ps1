$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$rawRoot = Join-Path $projectRoot 'data/raw'
$convertedRoot = Join-Path $projectRoot 'data/converted'
New-Item -ItemType Directory -Path $convertedRoot -Force | Out-Null
$wordApp = $null
try {
    $wordApp = New-Object -ComObject Word.Application
    $wordApp.Visible = $false
    $wordApp.DisplayAlerts = 0
    $wordApp.AutomationSecurity = 3
    foreach ($inputFile in Get-ChildItem -LiteralPath $rawRoot -Filter '*.doc') {
        $outputPath = [System.IO.Path]::GetFullPath((Join-Path $convertedRoot ($inputFile.BaseName + '.docx')))
        if (-not $outputPath.StartsWith($projectRoot + [System.IO.Path]::DirectorySeparatorChar)) { throw 'Path out of project' }
        if (Test-Path -LiteralPath $outputPath) { continue }
        $document = $null
        try {
            $document = $wordApp.Documents.Open($inputFile.FullName, $false, $true, $false)
            $document.SaveAs2($outputPath, 16)
            Write-Output ($inputFile.Name + ' converted')
        } finally { if ($null -ne $document) { $document.Close(0) } }
    }
} finally { if ($null -ne $wordApp) { $wordApp.Quit() } }

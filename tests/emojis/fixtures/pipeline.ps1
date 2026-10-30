param([string]$CommandPath, [string]$RecordsPath)
$records = Get-Content -Raw -LiteralPath $RecordsPath | ConvertFrom-Json
$records | & $CommandPath

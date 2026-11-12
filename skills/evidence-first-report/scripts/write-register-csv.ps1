param(
    [Parameter(Mandatory = $true)][string]$InputJsonPath,
    [Parameter(Mandatory = $true)][string]$OutputPath
)

$ErrorActionPreference = 'Stop'
$payload = Get-Content -LiteralPath $InputJsonPath -Raw | ConvertFrom-Json -AsHashtable
$header = @($payload.header | ForEach-Object { [string]$_ })
$rows = @($payload.rows)
if ($header.Count -eq 0 -or $rows.Count -eq 0) {
    throw 'The CSV contract requires a nonempty header and at least one data row.'
}
$headerNames = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
foreach ($name in $header) {
    if ([string]::IsNullOrWhiteSpace($name) -or -not $headerNames.Add($name)) { throw 'CSV has an empty or duplicate header name.' }
}
foreach ($row in $rows) {
    if ($null -eq $row -or $row -isnot [System.Collections.IDictionary]) {
        throw 'Every row must be a JSON object keyed by the exact header names.'
    }
    $keys = @($row.Keys | ForEach-Object { [string]$_ })
    $rowNames = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
    foreach ($key in $keys) { [void]$rowNames.Add($key) }
    if ($keys.Count -ne $header.Count -or -not $rowNames.SetEquals([string[]]$header)) {
        throw 'A row does not have exactly the required header fields.'
    }
}

$objects = foreach ($row in $rows) {
    $ordered = [ordered]@{}
    foreach ($name in $header) { $ordered[$name] = [string]$row[$name] }
    [pscustomobject]$ordered
}
$csvLines = @($objects | ConvertTo-Csv -NoTypeInformation)
$csvText = ($csvLines -join "`r`n") + "`r`n"
$fullOutputPath = [System.IO.Path]::GetFullPath($OutputPath)
$parent = [System.IO.Path]::GetDirectoryName($fullOutputPath)
[System.IO.Directory]::CreateDirectory($parent) | Out-Null
[System.IO.File]::WriteAllText($fullOutputPath, $csvText, [System.Text.UTF8Encoding]::new($false))

function Add-ValidatedRecord {
    param([System.Collections.Generic.List[string]]$Fields, [System.Text.StringBuilder]$Field, [System.Collections.Generic.List[object]]$Records)
    $Fields.Add($Field.ToString())
    if (@($Fields | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }).Count -eq 0) {
        throw 'CSV contains an empty or whitespace-only logical record.'
    }
    $Records.Add(@($Fields.ToArray()))
}

$text = [System.Text.UTF8Encoding]::new($false, $true).GetString([System.IO.File]::ReadAllBytes($fullOutputPath))
$records = [System.Collections.Generic.List[object]]::new()
$fields = [System.Collections.Generic.List[string]]::new()
$field = [System.Text.StringBuilder]::new()
$inQuotes = $false
$afterQuote = $false
$fieldStart = $true
$touched = $false
$quote = [char]34
$comma = [char]44
$lf = [char]10
$cr = [char]13
for ($i = 0; $i -lt $text.Length; $i++) {
    $ch = $text[$i]
    if ($inQuotes) {
        if ($ch -eq $quote) {
            if ($i + 1 -lt $text.Length -and $text[$i + 1] -eq $quote) {
                [void]$field.Append($quote)
                $i++
            } else {
                $inQuotes = $false
                $afterQuote = $true
            }
        } else {
            [void]$field.Append($ch)
        }
        continue
    }
    if ($afterQuote -and $ch -ne $comma -and $ch -ne $lf -and $ch -ne $cr) {
        throw 'CSV has characters after a closing quote.'
    }
    if ($ch -eq $quote) {
        if (-not $fieldStart -or $afterQuote) { throw 'CSV has an unexpected quote.' }
        $inQuotes = $true
        $fieldStart = $false
        $touched = $true
    } elseif ($ch -eq $comma) {
        $fields.Add($field.ToString())
        [void]$field.Clear()
        $fieldStart = $true
        $afterQuote = $false
        $touched = $true
    } elseif ($ch -eq $cr -or $ch -eq $lf) {
        if ($ch -eq $cr) {
            if ($i + 1 -ge $text.Length -or $text[$i + 1] -ne $lf) { throw 'CSV contains a bare carriage return.' }
            $i++
        }
        Add-ValidatedRecord -Fields $fields -Field $field -Records $records
        [void]$fields.Clear()
        [void]$field.Clear()
        $fieldStart = $true
        $afterQuote = $false
        $touched = $false
    } else {
        if ($afterQuote) { throw 'CSV has data after a closing quote.' }
        [void]$field.Append($ch)
        $fieldStart = $false
        $touched = $true
    }
}
if ($inQuotes) { throw 'CSV ended inside a quoted field.' }
if ($fields.Count -gt 0 -or $field.Length -gt 0 -or $afterQuote -or $touched) {
    Add-ValidatedRecord -Fields $fields -Field $field -Records $records
}
if ($records.Count -lt 2) { throw 'CSV requires a header and at least one data record.' }
$parsedHeader = @($records[0])
if ($parsedHeader.Count -ne $header.Count) { throw 'Serialized CSV header width differs from the contract.' }
for ($i = 0; $i -lt $header.Count; $i++) {
    if ($parsedHeader[$i] -cne $header[$i]) { throw 'Serialized CSV header differs from the contract.' }
}
if ($records.Count -ne ($rows.Count + 1)) { throw 'Serialized CSV data-row count differs from the structured input.' }
for ($rowIndex = 1; $rowIndex -lt $records.Count; $rowIndex++) {
    if ($records[$rowIndex].Count -ne $header.Count) {
        throw "CSV logical record $($rowIndex + 1) has $($records[$rowIndex].Count) fields; expected $($header.Count)."
    }
    for ($columnIndex = 0; $columnIndex -lt $header.Count; $columnIndex++) {
        $expectedValue = [string]$rows[$rowIndex - 1][$header[$columnIndex]]
        if (-not [string]::Equals($records[$rowIndex][$columnIndex], $expectedValue, [System.StringComparison]::Ordinal)) {
            throw "Serialized CSV data field at record $($rowIndex + 1), column $($columnIndex + 1) differs from the structured input."
        }
    }
}
Write-Output "Wrote and strictly validated $($records.Count - 1) CSV records at $fullOutputPath"

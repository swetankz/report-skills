<#
.SYNOPSIS
Validates statement-level coverage and provenance for a local derivative package.

.DESCRIPTION
Checks the claim-mapping CSV against all declared copy-bearing artifacts. Markdown
copy blocks, structured text items, and one-copy-unit-per-row CSV files use stable
statement IDs. Requires exact output text, source IDs for facts, per-file/per-row
provenance, and complete marker-to-map reconciliation.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ArtifactsRoot,
    [Parameter(Mandatory = $true)][string]$Mapping,
    [Parameter(Mandatory = $true)][string]$Deliverables
)

$ErrorActionPreference = 'Stop'
$requiredMapColumns = @(
    'statement_id', 'claim_ids', 'source_locator', 'deliverable_id', 'output_path',
    'output_location', 'statement_type', 'output_text', 'status', 'context_retained',
    'context_omitted', 'reason'
)
$csvProvenanceColumns = @(
    'parent_report_id', 'parent_report_version', 'parent_report_hash', 'source_claim_ids',
    'transformation_type', 'dimensions', 'aspect_ratio', 'status'
)
$csvFrameColumns = @('frame_id', 'duration_seconds', 'content_type', 'visual_source', 'transformation', 'transition_intent')
$markdownProvenanceFields = @(
    'deliverable_id', 'parent_report_id', 'parent_report_version', 'parent_report_hash',
    'source_claim_ids', 'transformation_type', 'dimensions', 'aspect_ratio', 'status'
)
$errors = [System.Collections.Generic.List[string]]::new()

function Read-StrictCsv {
    param([Parameter(Mandatory = $true)][string]$Path)
    Add-Type -AssemblyName Microsoft.VisualBasic
    $parser = [Microsoft.VisualBasic.FileIO.TextFieldParser]::new(
        $Path,
        [System.Text.Encoding]::UTF8,
        $true
    )
    $parser.TextFieldType = [Microsoft.VisualBasic.FileIO.FieldType]::Delimited
    $parser.SetDelimiters([string[]]@(','))
    $parser.HasFieldsEnclosedInQuotes = $true
    $parser.TrimWhiteSpace = $false
    $records = [System.Collections.Generic.List[object]]::new()
    try {
        while (-not $parser.EndOfData) {
            $fields = $parser.ReadFields()
            if ($null -eq $fields) {
                $records.Add([pscustomobject]@{ Fields = [string[]]@() })
            } else {
                $records.Add([pscustomobject]@{ Fields = [string[]]$fields })
            }
        }
    } finally {
        $parser.Close()
    }
    return [pscustomobject]@{ Records = $records.ToArray() }
}

function Resolve-SafeArtifact {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$RelativePath
    )
    if ([System.IO.Path]::IsPathRooted($RelativePath) -or $RelativePath -match '(^|[\\/])\.\.([\\/]|$)') {
        throw "path must be a safe relative path: $RelativePath"
    }
    $full = [System.IO.Path]::GetFullPath((Join-Path $Root $RelativePath))
    $prefix = $Root.TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    if (-not $full.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "path escapes artifacts root: $RelativePath"
    }
    $current = $Root
    $parts = @($RelativePath -split '[\\/]')
    for ($index = 0; $index -lt $parts.Count; $index++) {
        $part = $parts[$index]
        if (-not $part) { continue }
        $current = Join-Path $current $part
        $isLast = ($index -eq $parts.Count - 1)
        if ($isLast -and -not (Test-Path -LiteralPath $current -PathType Leaf)) {
            throw "artifact does not exist as a regular file: $RelativePath"
        }
        if (-not $isLast -and -not (Test-Path -LiteralPath $current -PathType Container)) {
            throw "artifact parent is not a directory: $RelativePath"
        }
        $item = Get-Item -LiteralPath $current -Force
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "symlinks or reparse points are not allowed: $RelativePath"
        }
    }
    return $full
}

function Read-OutputStatements {
    param([Parameter(Mandatory = $true)][string]$Path)
    $localErrors = [System.Collections.Generic.List[string]]::new()
    $statements = @{}
    $extension = [System.IO.Path]::GetExtension($Path).ToLowerInvariant()

    if ($extension -eq '.csv') {
        try { $csvData = Read-StrictCsv -Path $Path; $records = @($csvData.Records) }
        catch { return @{ Statements = @{}; Errors = @("$([System.IO.Path]::GetFileName($Path)): strict CSV parse failed: $($_.Exception.Message)") } }
        if ($records.Count -lt 1) { return @{ Statements = @{}; Errors = @("$([System.IO.Path]::GetFileName($Path)): CSV has no header") } }
        $headers = @($records[0].Fields)
        foreach ($column in @('statement_id', 'output_text')) {
            if ($headers -cnotcontains $column) { $localErrors.Add("$([System.IO.Path]::GetFileName($Path)): CSV deliverable needs $column column") }
        }
        foreach ($column in $csvProvenanceColumns) {
            if ($headers -cnotcontains $column) { $localErrors.Add("$([System.IO.Path]::GetFileName($Path)): CSV deliverable is missing per-row provenance column $column") }
        }
        if ($headers -ccontains 'frame_id') {
            foreach ($column in $csvFrameColumns) {
                if ($headers -cnotcontains $column) { $localErrors.Add("$([System.IO.Path]::GetFileName($Path)): frame CSV is missing production-plan column $column") }
            }
        }
        if ($localErrors.Count -gt 0) { return @{ Statements = @{}; Errors = $localErrors.ToArray() } }
        for ($i = 1; $i -lt $records.Count; $i++) {
            $fields = @($records[$i].Fields)
            $lineNumber = $i + 1
            if ($fields.Count -ne $headers.Count) {
                $localErrors.Add("$([System.IO.Path]::GetFileName($Path)): CSV row $lineNumber has $($fields.Count) fields; expected $($headers.Count)")
                continue
            }
            $row = @{}
            for ($c = 0; $c -lt $headers.Count; $c++) { $row[$headers[$c]] = [string]$fields[$c] }
            $statementId = $row['statement_id'].Trim()
            $outputText = $row['output_text'].Trim()
            if (-not $statementId -or -not $outputText) {
                $localErrors.Add("$([System.IO.Path]::GetFileName($Path)): CSV row $lineNumber has an empty statement_id or output_text")
                continue
            }
            if ($statements.ContainsKey($statementId)) {
                $localErrors.Add("$([System.IO.Path]::GetFileName($Path)): duplicate statement_id $statementId")
                continue
            }
            foreach ($column in $csvProvenanceColumns) {
                if (-not $row[$column].Trim()) { $localErrors.Add("$([System.IO.Path]::GetFileName($Path)): CSV row $lineNumber has empty provenance field $column") }
            }
            if ($row['status'].Trim() -notin @('draft', 'ready-for-approval')) { $localErrors.Add("$([System.IO.Path]::GetFileName($Path)): CSV row $lineNumber has an invalid release status") }
            $statements[$statementId] = $outputText
        }
        return @{ Statements = $statements; Errors = $localErrors.ToArray() }
    }

    $text = [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
    if ($extension -eq '.md') {
        $lines = [System.IO.File]::ReadAllLines($Path, [System.Text.Encoding]::UTF8)
        if ($lines.Count -eq 0 -or $lines[0].Trim() -ne '---') {
            $localErrors.Add("$([System.IO.Path]::GetFileName($Path)): Markdown deliverables need a YAML provenance header")
            return @{ Statements = @{}; Errors = $localErrors.ToArray() }
        }
        $end = -1
        for ($i = 1; $i -lt $lines.Count; $i++) { if ($lines[$i].Trim() -eq '---') { $end = $i; break } }
        if ($end -lt 0) {
            $localErrors.Add("$([System.IO.Path]::GetFileName($Path)): unterminated YAML provenance header")
            return @{ Statements = @{}; Errors = $localErrors.ToArray() }
        }
        $headerLines = @()
        if ($end -gt 1) { $headerLines = $lines[1..($end - 1)] }
        $header = ($headerLines -join "`n")
        foreach ($field in $markdownProvenanceFields) {
            if ($header -notmatch "(?m)^\s*$([regex]::Escape($field)):\s*\S.*$") {
                $localErrors.Add("$([System.IO.Path]::GetFileName($Path)): provenance header is missing nonempty $field")
            }
        }
        if ($header -match '(?m)^\s*status:\s*(\S+)\s*$' -and $Matches[1] -notin @('draft', 'ready-for-approval')) {
            $localErrors.Add("$([System.IO.Path]::GetFileName($Path)): provenance header has an invalid release status")
        }
        $bodyLines = @()
        if ($end + 1 -lt $lines.Count) { $bodyLines = $lines[($end + 1)..($lines.Count - 1)] }
        $text = $bodyLines -join "`n"
        $blocks = [regex]::Split($text, '\r?\n\s*\r?\n')
        foreach ($block in $blocks) {
            $content = $block.Trim()
            if (-not $content) { continue }
            $matches = [regex]::Matches($content, '<!--\s*statement_id:\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*-->')
            if ($matches.Count -ne 1) {
                $localErrors.Add("$([System.IO.Path]::GetFileName($Path)): each nonempty Markdown content block needs exactly one statement_id marker")
                continue
            }
            $statementId = $matches[0].Groups[1].Value
            $statementBody = [regex]::Replace($content, '<!--\s*statement_id:\s*[A-Za-z0-9][A-Za-z0-9._-]*\s*-->', '', 1).Trim()
            if ($statements.ContainsKey($statementId)) { $localErrors.Add("$([System.IO.Path]::GetFileName($Path)): duplicate statement_id $statementId") }
            else { $statements[$statementId] = $statementBody }
        }
        return @{ Statements = $statements; Errors = $localErrors.ToArray() }
    }

    if ($extension -notin @('.yaml', '.yml', '.json')) {
        return @{ Statements = @{}; Errors = @("$([System.IO.Path]::GetFileName($Path)): unsupported deliverable format $extension") }
    }
    if ($extension -eq '.json') { $matches = [regex]::Matches($text, '"statement_id"\s*:\s*"([A-Za-z0-9][A-Za-z0-9._-]*)"') }
    else {
        $matches = [regex]::Matches($text, '(?m)^\s*(?:-\s*)?statement_id:\s*["'']?([A-Za-z0-9][A-Za-z0-9._-]*)["'']?\s*$')
        $accessMatch = [regex]::Match($text, '(?m)^accessibility_copy:\s*$')
        if ($accessMatch.Success) {
            $tail = $text.Substring($accessMatch.Index + $accessMatch.Length)
            $nextTopLevel = [regex]::Match($tail, '(?m)^(?!accessibility_copy:)\S[^\r\n]*:\s*$')
            $accessBlock = if ($nextTopLevel.Success) { $tail.Substring(0, $nextTopLevel.Index) } else { $tail }
            $accessItems = [regex]::Matches($accessBlock, '(?m)^\s*-\s+deliverable_id:\s*\S+').Count
            $accessIds = [regex]::Matches($accessBlock, '(?m)^\s*(?:-\s*)?statement_id:\s*["'']?[A-Za-z0-9][A-Za-z0-9._-]*["'']?\s*$').Count
            if ($accessItems -ne $accessIds) { $localErrors.Add("$([System.IO.Path]::GetFileName($Path)): every accessibility_copy item needs exactly one statement_id") }
        }
    }
    for ($i = 0; $i -lt $matches.Count; $i++) {
        $statementId = $matches[$i].Groups[1].Value
        $start = $matches[$i].Index + $matches[$i].Length
        $finish = if ($i + 1 -lt $matches.Count) { $matches[$i + 1].Index } else { $text.Length }
        if ($statements.ContainsKey($statementId)) { $localErrors.Add("$([System.IO.Path]::GetFileName($Path)): duplicate statement_id $statementId") }
        else { $statements[$statementId] = $text.Substring($start, $finish - $start) }
    }
    if ($statements.Count -eq 0) { $localErrors.Add("$([System.IO.Path]::GetFileName($Path)): no statement_id fields found") }
    return @{ Statements = $statements; Errors = $localErrors.ToArray() }
}

try {
    $root = (Resolve-Path -LiteralPath $ArtifactsRoot).Path
    if (-not (Test-Path -LiteralPath $root -PathType Container)) { throw 'artifacts root is not a directory' }
    $mappingFull = (Resolve-Path -LiteralPath $Mapping).Path
    $rootPrefix = $root.TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    if (-not $mappingFull.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) { throw 'mapping CSV must be inside artifacts root' }
    $mappingItem = Get-Item -LiteralPath $mappingFull -Force
    if (-not $mappingItem.PSIsContainer -and ($mappingItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -eq 0) { }
    else { throw 'mapping CSV must be a regular non-link file' }

    $mappingCsvData = Read-StrictCsv -Path $mappingFull
    $mapRecords = @($mappingCsvData.Records)
    if ($mapRecords.Count -lt 1) { throw 'mapping CSV has no header' }
    $headers = @($mapRecords[0].Fields)
    foreach ($column in $requiredMapColumns) { if ($headers -cnotcontains $column) { $errors.Add("mapping CSV is missing required column $column") } }
    $mapRows = [System.Collections.Generic.List[hashtable]]::new()
    for ($i = 1; $i -lt $mapRecords.Count; $i++) {
        $fields = @($mapRecords[$i].Fields)
        if ($fields.Count -ne $headers.Count) { $errors.Add("mapping row $($i + 1) has $($fields.Count) fields; expected $($headers.Count)"); continue }
        $row = @{}
        for ($c = 0; $c -lt $headers.Count; $c++) { $row[$headers[$c]] = [string]$fields[$c].Trim() }
        $mapRows.Add($row)
    }

    $expected = @{}
    foreach ($row in $mapRows) {
        $status = $row['status']
        if ($status -notin @('used', 'shortened', 'omitted')) { $errors.Add("mapping row has unsupported status '$status'"); continue }
        if ($status -eq 'omitted') {
            if ($row['statement_id'] -or $row['output_path'] -or $row['output_text']) { $errors.Add('omitted mapping row must not claim an output statement') }
            if (-not $row['claim_ids'] -or -not $row['context_omitted'] -or -not $row['reason']) { $errors.Add('omitted mapping row needs claim_ids, context_omitted, and reason') }
            continue
        }
        $statementId = $row['statement_id']
        if (-not $statementId) { $errors.Add('used/shortened mapping row is missing statement_id'); continue }
        if ($expected.ContainsKey($statementId)) { $errors.Add("mapping has duplicate statement_id $statementId"); continue }
        foreach ($field in @('deliverable_id', 'output_path', 'output_location', 'statement_type', 'output_text')) {
            if (-not $row[$field]) { $errors.Add("mapping statement $statementId is missing $field") }
        }
        if ($row['statement_type'] -in @('sourced_fact', 'analysis', 'source_metadata')) {
            if (-not $row['claim_ids'] -or -not $row['source_locator']) { $errors.Add("factual statement $statementId needs claim_ids and source_locator") }
        }
        if ($row['statement_type'] -eq 'recommendation' -and -not $row['reason']) { $errors.Add("recommendation $statementId needs its rationale") }
        if ($status -eq 'shortened' -and (-not $row['context_omitted'] -or -not $row['reason'])) { $errors.Add("shortened statement $statementId needs omitted context and reason") }
        $expected[$statementId] = @{ Path = $row['output_path'].Replace('\', '/'); Text = $row['output_text'] }
    }

    $declared = @{}
    foreach ($relative in ($Deliverables -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })) {
        $target = Resolve-SafeArtifact -Root $root -RelativePath $relative
        $rel = [System.IO.Path]::GetRelativePath($root, $target).Replace('\', '/')
        if ($declared.ContainsKey($rel)) { $errors.Add("duplicate declared deliverable $rel") }
        else { $declared[$rel] = $target }
    }
    if ($declared.Count -eq 0) { $errors.Add('at least one deliverable must be declared') }

    $found = @{}
    foreach ($rel in $declared.Keys) {
        $parsed = Read-OutputStatements -Path $declared[$rel]
        foreach ($message in $parsed.Errors) { $errors.Add($message) }
        foreach ($statementId in $parsed.Statements.Keys) {
            if ($found.ContainsKey($statementId)) { $errors.Add("statement_id $statementId appears in more than one deliverable") }
            else { $found[$statementId] = @{ Path = $rel; Body = [string]$parsed.Statements[$statementId]; Extension = [System.IO.Path]::GetExtension($declared[$rel]).ToLowerInvariant() } }
        }
    }

    foreach ($statementId in $expected.Keys) { if (-not $found.ContainsKey($statementId)) { $errors.Add("mapped statement $statementId is absent from declared deliverables") } }
    foreach ($statementId in $found.Keys) { if (-not $expected.ContainsKey($statementId)) { $errors.Add("unmapped statement $statementId appears in a declared deliverable") } }
    foreach ($statementId in $expected.Keys) {
        if (-not $found.ContainsKey($statementId)) { continue }
        $mapped = $expected[$statementId]
        $actual = $found[$statementId]
        if ($mapped.Path -ne $actual.Path) { $errors.Add("statement $statementId path mismatch: map=$($mapped.Path), file=$($actual.Path)") }
        if ($actual.Extension -in @('.md', '.csv')) {
            if ($mapped.Text -cne $actual.Body.Trim()) { $errors.Add("statement $statementId output_text does not exactly match its marked output") }
        } elseif (-not $actual.Body.Contains($mapped.Text, [System.StringComparison]::Ordinal)) {
            $errors.Add("statement $statementId output_text does not match its marked output block")
        }
    }
} catch {
    $errors.Add($_.Exception.Message)
}

if ($errors.Count -gt 0) {
    Write-Output "Derivative traceability validation failed with $($errors.Count) issue(s):"
    foreach ($message in $errors) { Write-Output "- $message" }
    exit 1
}
Write-Output 'Derivative traceability validation passed: all declared statement IDs and verbatim output text reconcile.'
exit 0

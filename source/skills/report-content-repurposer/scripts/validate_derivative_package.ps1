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
    [Parameter(Mandatory = $true)][string]$Deliverables,
    [Parameter(Mandatory = $false)][string]$SourceReport,
    [Parameter(Mandatory = $false)][string]$SourceInventory,
    [Parameter(Mandatory = $false)][string]$StatementSupport,
    [switch]$StructuralOnly
)

$ErrorActionPreference = 'Stop'
$requiredMapColumns = @(
    'statement_id', 'claim_ids', 'source_locator', 'deliverable_id', 'output_path',
    'output_location', 'statement_type', 'output_text', 'status', 'context_retained',
    'context_omitted', 'reason', 'visual_unit_id', 'related_statement_ids'
)
$csvProvenanceColumns = @(
    'parent_report_id', 'parent_report_version', 'parent_report_hash', 'source_claim_ids',
    'transformation_type', 'dimensions', 'aspect_ratio', 'status'
)
$csvFrameColumns = @('frame_id', 'duration_seconds', 'content_type', 'visual_source', 'transformation', 'transition_intent')
$videoContentTypes = @('on_screen_copy', 'narration', 'caption', 'accessibility_transcript')
$allowedStatementTypes = @('sourced_fact', 'analysis', 'recommendation', 'source_metadata', 'nonfactual', 'accessibility_copy')
$markdownProvenanceFields = @(
    'deliverable_id', 'parent_report_id', 'parent_report_version', 'parent_report_hash',
    'source_claim_ids', 'transformation_type', 'dimensions', 'aspect_ratio', 'status'
)
$errors = [System.Collections.Generic.List[string]]::new()
if ($StructuralOnly -and ($SourceReport -or $SourceInventory -or $StatementSupport)) {
    Write-Output 'StructuralOnly is mutually exclusive with SourceReport, SourceInventory and StatementSupport.'
    exit 1
}
if (-not $StructuralOnly -and -not $SourceReport) {
    Write-Output 'SourceReport is required for handoff validation.'
    exit 1
}

function Read-StrictCsv {
    param([Parameter(Mandatory = $true)][string]$Path)
    # TextFieldParser skips blank physical lines. Reject empty logical records
    # first, while retaining embedded line breaks inside quoted fields.
    $rawCsv = [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
    $insideQuotes = $false
    $recordHasContent = $false
    for ($characterIndex = 0; $characterIndex -lt $rawCsv.Length; $characterIndex++) {
        $character = $rawCsv[$characterIndex]
        if ($character -eq '"') {
            $recordHasContent = $true
            if ($insideQuotes -and $characterIndex + 1 -lt $rawCsv.Length -and $rawCsv[$characterIndex + 1] -eq '"') { $characterIndex++; continue }
            $insideQuotes = -not $insideQuotes
        } elseif (-not $insideQuotes -and ($character -eq "`r" -or $character -eq "`n")) {
            if (-not $recordHasContent) { throw 'CSV has a blank logical record' }
            $recordHasContent = $false
            if ($character -eq "`r" -and $characterIndex + 1 -lt $rawCsv.Length -and $rawCsv[$characterIndex + 1] -eq "`n") { $characterIndex++ }
        } elseif (-not [char]::IsWhiteSpace($character)) { $recordHasContent = $true }
    }
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
    if ($records.Count) {
        $csvHeaders = @($records[0].Fields)
        $headerSet = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
        foreach ($csvHeader in $csvHeaders) { if (-not $csvHeader.Trim() -or -not $headerSet.Add($csvHeader)) { throw 'CSV has a blank or duplicate header name' } }
    }
    return [pscustomobject]@{ Records = $records.ToArray() }
}

function Normalize-AccessibleText {
    param([Parameter(Mandatory = $true)][string]$Text)
    $normalized = [regex]::Replace($Text, '(?m)^\s{0,3}#{1,6}\s+', '')
    $normalized = [regex]::Replace($normalized, '\[([^\]]+)\]\([^)]*\)', '$1')
    $normalized = [regex]::Replace($normalized, '[*`_~]', '')
    return [regex]::Replace($normalized, '\s+', ' ').Trim().ToLowerInvariant()
}

function Normalize-LiteralMetadata {
    param([string]$Text)
    $normalized = [regex]::Replace($Text, '(?m)^\s{0,3}#{1,6}\s+', '')
    return [regex]::Replace($normalized, '\s+', ' ').Trim()
}

function Get-ContractKey {
    param([string[]]$Parts)
    return (@($Parts | ForEach-Object { "$($_.Length):$_" }) -join '')
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

function Test-SourceContract {
    param([string]$Root, [object[]]$Rows, [string[]]$FormatIds, [string]$SourceText,
        [string]$SourceHash, [string]$InventoryPath, [string]$SupportPath)
    # This checks a reviewed inventory. Clause boundaries, classification,
    # entailment and materiality remain the declared manual review.
    try {
        $inventoryRelative = [System.IO.Path]::GetRelativePath($Root, [System.IO.Path]::GetFullPath($InventoryPath))
        $supportRelative = [System.IO.Path]::GetRelativePath($Root, [System.IO.Path]::GetFullPath($SupportPath))
        $inventoryFile = Resolve-SafeArtifact -Root $Root -RelativePath $inventoryRelative
        $supportFile = Resolve-SafeArtifact -Root $Root -RelativePath $supportRelative
        $inventory = [System.IO.File]::ReadAllText($inventoryFile, [System.Text.Encoding]::UTF8) | ConvertFrom-Json -AsHashtable
    } catch { $errors.Add("required source inventory and statement support cannot be read: $($_.Exception.Message)"); return }
    foreach ($contract in $manifestContracts) {
        foreach ($field in @('source_inventory', 'statement_support')) {
            $expectedPath = if ($field -ceq 'source_inventory') { $inventoryRelative.Replace('\', '/') } else { $supportRelative.Replace('\', '/') }
            $pointer = $contract[$field]
            if ($pointer -isnot [string] -or $pointer.Replace('\', '/') -cne $expectedPath) { $errors.Add("manifest $($contract['path']) $field must name the exact validated relative path $expectedPath") }
        }
    }
    if ($inventory -isnot [hashtable] -or $inventory['schema_version'] -cne '1.0') { $errors.Add('source inventory must use schema_version 1.0'); return }
    if ($inventory['source_report_hash'] -cne $SourceHash) { $errors.Add('source inventory hash does not match source report bytes') }
    $review = $inventory['review']
    $requiredChecks = @('atomic-units', 'source-types', 'semantic-support', 'material-omissions')
    if ($review -isnot [hashtable] -or $review['status'] -cne 'complete' -or $review['method'] -cne 'manual-clause-review' -or $review['checks'] -isnot [array] -or @($review['checks'] | Where-Object { $_ -isnot [string] }).Count -or @($requiredChecks | Where-Object { @($review['checks']) -cnotcontains $_ }).Count) {
        $errors.Add('source inventory needs complete manual-clause-review of atomic-units, source-types, semantic-support and material-omissions')
    }
    $lines = @($SourceText -split '\r\n|\n|\r')
    $covered = [System.Collections.Generic.List[object]]::new()
    foreach ($line in $lines) { $covered.Add([System.Collections.Generic.HashSet[int]]::new()) }
    $units = [System.Collections.Generic.Dictionary[string,hashtable]]::new([System.StringComparer]::Ordinal)
    $kinds = @('sourced_fact', 'analysis', 'recommendation', 'safeguard', 'stop_rule', 'measurement', 'source_metadata', 'nonfactual')
    if ($inventory['source_units'] -isnot [array] -or @($inventory['source_units']).Count -eq 0) { $errors.Add('source inventory needs nonempty source_units') }
    foreach ($unit in @($inventory['source_units'])) {
        if ($unit -isnot [hashtable]) { $errors.Add('source inventory unit must be an object'); continue }
        $unitId = $unit['source_unit_id']
        if ($unitId -isnot [string] -or -not $unitId -or $units.ContainsKey($unitId)) { $errors.Add('source inventory has empty or duplicate source_unit_id'); continue }
        $kind = $unit['kind']; $quote = $unit['source_text']; $locator = $unit['source_locator']
        if ($kind -isnot [string] -or $kinds -cnotcontains $kind -or $quote -isnot [string] -or -not $quote) { $errors.Add("source unit $unitId needs a supported kind and literal source_text"); continue }
        $claims = @($unit['claim_ids'])
        if ($unit['claim_ids'] -isnot [array] -or @($claims | Where-Object { $_ -isnot [string] -or -not $_ }).Count -or @($claims | Sort-Object -CaseSensitive -Unique).Count -ne $claims.Count) {
            $errors.Add("source unit $unitId needs a unique claim_ids array"); continue
        }
        $units.Add($unitId, $unit)
        if ($kind -cin @('sourced_fact', 'analysis') -and $claims.Count -eq 0) { $errors.Add("source unit $unitId factual/analysis support needs exact claim_ids") }
        if ($kind -ceq 'source_metadata' -and $claims.Count) { $errors.Add("source unit $unitId metadata must not carry claim_ids") }
        foreach ($claim in $claims) {
            if (-not [regex]::IsMatch($SourceText, '(?<![\w.-])' + [regex]::Escape($claim) + '(?![\w.-])')) { $errors.Add("source unit $unitId claim_id $claim does not occur verbatim in source") }
        }
        $match = if ($locator -is [string]) { [regex]::Match($locator, '^line:([1-9][0-9]*)$') } else { [regex]::Match('', '^line:([1-9][0-9]*)$') }
        $lineNumber = 0
        if ($match.Success) { [void][int]::TryParse($match.Groups[1].Value, [ref]$lineNumber) }
        if ($lineNumber -lt 1 -or $lineNumber -gt $lines.Count) { $errors.Add("source unit $unitId needs an exact line:N locator"); continue }
        $line = [string]$lines[$lineNumber - 1]
        $start = $line.IndexOf($quote, [System.StringComparison]::Ordinal)
        if ($start -lt 0 -or $line.IndexOf($quote, $start + 1, [System.StringComparison]::Ordinal) -ge 0) { $errors.Add("source unit $unitId source_text must occur exactly once at $locator"); continue }
        for ($i = $start; $i -lt $start + $quote.Length; $i++) { [void]$covered[$lineNumber - 1].Add($i) }
    }
    for ($lineIndex = 0; $lineIndex -lt $lines.Count; $lineIndex++) {
        $line = [string]$lines[$lineIndex]
        if (-not $line.Trim() -or $line -match '^\s*#{1,6}\s') { continue }
        for ($i = 0; $i -lt $line.Length; $i++) {
            if (-not [char]::IsWhiteSpace($line[$i]) -and -not $covered[$lineIndex].Contains($i)) { $errors.Add("source line $($lineIndex + 1) has text missing from the upstream inventory: $($line.Substring(0, [Math]::Min(100, $line.Length)))"); break }
        }
    }
    if ($FormatIds.Count -eq 0) { $errors.Add('source reconciliation needs explicit requested-format manifest entries') }
    $mapped = [System.Collections.Generic.Dictionary[string,hashtable]]::new([System.StringComparer]::Ordinal)
    foreach ($row in $Rows) { if ($row['status'] -cne 'omitted' -and $row['statement_id'] -and -not $mapped.ContainsKey($row['statement_id'])) { $mapped.Add($row['statement_id'], $row) } }
    $formatPaths = @{}
    foreach ($statementId in $mapped.Keys) {
        $row = $mapped[$statementId]
        if (-not $manifestDeliverableRoles.ContainsKey($row['deliverable_id'])) { $errors.Add("output statement $statementId references an absent manifest deliverable_id") }
        if ($FormatIds -ccontains $row['deliverable_id']) {
            if (-not $formatPaths.ContainsKey($row['deliverable_id'])) { $formatPaths[$row['deliverable_id']] = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal) }
            [void]$formatPaths[$row['deliverable_id']].Add($row['output_path'])
        }
        if ($declared.ContainsKey($row['output_path']) -and [System.IO.Path]::GetExtension($row['output_path']).ToLowerInvariant() -eq '.md') {
            $headerText = [System.IO.File]::ReadAllText($declared[$row['output_path']], [System.Text.Encoding]::UTF8)
            $headerParts = @($headerText -split '---', 3)
            $header = if ($headerParts.Count -gt 1) { $headerParts[1] } else { '' }
            $identityMatch = [regex]::Match($header, '(?m)^deliverable_id:\s*["'']?([^\r\n"'']+)["'']?\s*$')
            if (-not $identityMatch.Success -or $identityMatch.Groups[1].Value.Trim() -cne $row['deliverable_id']) { $errors.Add("output statement $statementId deliverable_id disagrees with its file header") }
        }
    }
    foreach ($formatId in $FormatIds) { if (-not $formatPaths.ContainsKey($formatId) -or $formatPaths[$formatId].Count -ne 1) { $errors.Add("requested format $formatId must bind exactly one copy-bearing output file") } }
    try {
        $supportCsv = Read-StrictCsv -Path $supportFile
        $records = @($supportCsv.Records)
        if ($records.Count -eq 0) { throw 'statement support CSV has no header' }
        $headers = @($records[0].Fields)
        if (@($headers | Sort-Object -Unique).Count -ne $headers.Count) { throw 'statement support CSV has duplicate header names' }
        foreach ($column in @('support_id', 'statement_id', 'source_unit_id', 'output_text', 'output_occurrence', 'claim_ids', 'source_locator', 'kind', 'reason')) { if ($headers -cnotcontains $column) { throw 'statement support CSV is missing required columns' } }
    } catch { $errors.Add("cannot read statement support CSV: $($_.Exception.Message)"); return }
    $supports = [System.Collections.Generic.Dictionary[string,object]]::new([System.StringComparer]::Ordinal)
    $uses = [System.Collections.Generic.Dictionary[string,object]]::new([System.StringComparer]::Ordinal)
    $supportIds = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
    $occurrenceBindings = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
    for ($recordIndex = 1; $recordIndex -lt $records.Count; $recordIndex++) {
        $fields = @($records[$recordIndex].Fields)
        if ($fields.Count -ne $headers.Count) { $errors.Add("statement support row $($recordIndex + 1) has the wrong field count"); continue }
        $child = @{}
        for ($c = 0; $c -lt $headers.Count; $c++) { $child[$headers[$c]] = [string]$fields[$c].Trim() }
        $supportId = $child['support_id']; $statementId = $child['statement_id']
        if (-not $supportId -or -not $supportIds.Add($supportId)) { $errors.Add('statement support has empty or duplicate support_id') }
        if (-not $mapped.ContainsKey($statementId)) { $errors.Add("support $supportId has no canonical output statement $statementId"); continue }
        $parent = $mapped[$statementId]
        if (-not $supports.ContainsKey($statementId)) { $supports.Add($statementId, [System.Collections.Generic.List[hashtable]]::new()) }
        $supports[$statementId].Add($child)
        $fragment = if ($child['output_text']) { Normalize-AccessibleText -Text $child['output_text'] } else { '' }
        $occurrences = if ($fragment) { @([regex]::Matches((Normalize-AccessibleText -Text $parent['output_text']), [regex]::Escape($fragment))) } else { @() }
        $occurrence = 0L
        if ($child['output_occurrence'] -match '^[1-9][0-9]*$') { [void][long]::TryParse($child['output_occurrence'], [ref]$occurrence) }
        $binding = Get-ContractKey -Parts @($statementId, $fragment, [string]$occurrence)
        if ($occurrence -lt 1 -or $occurrence -gt $occurrences.Count) { $errors.Add("support $supportId output_text is not a literal fragment of $statementId") }
        elseif (-not $occurrenceBindings.Add($binding)) { $errors.Add("support $supportId repeats an output occurrence binding") }
        if ($child['kind'] -ceq 'nonfactual' -and -not $child['source_unit_id']) {
            if ($child['claim_ids'] -or $child['source_locator'] -or -not $child['reason']) { $errors.Add("nonfactual support $supportId needs rationale and no evidence values") }
            if ($parent['statement_type'] -cnotin @('nonfactual', 'accessibility_copy')) { $errors.Add("support $supportId cannot classify factual or metadata output as nonfactual") }
            continue
        }
        if (-not $units.ContainsKey($child['source_unit_id'])) { $errors.Add("support $supportId references an absent source_unit_id"); continue }
        $unit = $units[$child['source_unit_id']]
        $childClaims = @($child['claim_ids'] -split ';' | ForEach-Object { $_.Trim() } | Where-Object { $_ } | Sort-Object -CaseSensitive -Unique)
        $unitClaims = @($unit['claim_ids'] | Sort-Object -CaseSensitive -Unique)
        $claimsDiffer = ($childClaims.Count -ne $unitClaims.Count) -or @($childClaims | Where-Object { $unitClaims -cnotcontains $_ }).Count
        if ($child['kind'] -cne $unit['kind'] -or $child['source_locator'] -cne $unit['source_locator'] -or $claimsDiffer) { $errors.Add("support $supportId kind, locator and claim_ids must match its exact source unit") }
        if ($parent['statement_type'] -ceq 'source_metadata' -and $child['kind'] -cne 'source_metadata') { $errors.Add("metadata statement $statementId contains non-metadata support") }
        if ($child['kind'] -ceq 'source_metadata' -and (Normalize-LiteralMetadata -Text $child['output_text']) -cne (Normalize-LiteralMetadata -Text $unit['source_text'])) { $errors.Add("metadata support $supportId must reproduce only its literal source field") }
        if ($child['kind'] -ceq 'source_metadata' -and -not (Normalize-LiteralMetadata -Text $parent['output_text']).Contains((Normalize-LiteralMetadata -Text $child['output_text']), [System.StringComparison]::Ordinal)) { $errors.Add("metadata support $supportId must preserve its literal field in canonical output") }
        $useKey = Get-ContractKey -Parts @($child['source_unit_id'], $parent['deliverable_id'])
        if (-not $uses.ContainsKey($useKey)) { $uses.Add($useKey, [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)) }
        [void]$uses[$useKey].Add($statementId)
    }
    foreach ($statementId in $mapped.Keys) {
        $parent = $mapped[$statementId]; $text = Normalize-AccessibleText -Text $parent['output_text']
        $positions = [System.Collections.Generic.HashSet[int]]::new()
        $childClaims = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
        $children = if ($supports.ContainsKey($statementId)) { @($supports[$statementId]) } else { @() }
        foreach ($child in $children) {
            $fragment = if ($child['output_text']) { Normalize-AccessibleText -Text $child['output_text'] } else { '' }
            $occurrence = 0L
            if ($child['output_occurrence'] -match '^[1-9][0-9]*$') { [void][long]::TryParse($child['output_occurrence'], [ref]$occurrence) }
            $matches = if ($fragment) { @([regex]::Matches($text, [regex]::Escape($fragment))) } else { @() }
            if ($occurrence -ge 1 -and $occurrence -le $matches.Count) { $match = $matches[$occurrence - 1]; for ($i = $match.Index; $i -lt $match.Index + $match.Length; $i++) { [void]$positions.Add($i) } }
            foreach ($claim in @($child['claim_ids'] -split ';' | ForEach-Object { $_.Trim() } | Where-Object { $_ })) { [void]$childClaims.Add($claim) }
        }
        for ($i = 0; $i -lt $text.Length; $i++) { if ([char]::IsLetterOrDigit($text[$i]) -and -not $positions.Contains($i)) { $errors.Add("statement $statementId has copy without atomic support records"); break } }
        $parentClaims = @($parent['claim_ids'] -split ';' | ForEach-Object { $_.Trim() } | Where-Object { $_ } | Sort-Object -CaseSensitive -Unique)
        if ($parentClaims.Count -ne $childClaims.Count -or @($parentClaims | Where-Object { -not $childClaims.Contains($_) }).Count) { $errors.Add("statement $statementId claim_ids must equal its atomic support claims") }
    }
    $coverage = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
    if ($inventory['coverage'] -isnot [array]) { $errors.Add('source inventory coverage must be an array') }
    foreach ($entry in @($inventory['coverage'])) {
        if ($entry -isnot [hashtable]) { $errors.Add('source coverage entry must be an object'); continue }
        $unitId = $entry['source_unit_id']; $formatId = $entry['deliverable_id']
        if ($unitId -isnot [string] -or $formatId -isnot [string]) { $errors.Add('source coverage needs string source_unit_id and deliverable_id'); continue }
        $key = Get-ContractKey -Parts @($unitId, $formatId)
        if (-not $unitId -or -not $units.ContainsKey($unitId) -or $FormatIds -cnotcontains $formatId -or -not $coverage.Add($key)) { $errors.Add('source coverage has unknown or duplicate source-unit/format pair'); continue }
        $actual = if ($uses.ContainsKey($key)) { @($uses[$key]) } else { @() }
        $stated = @($entry['statement_ids'])
        if ($entry['statement_ids'] -isnot [array] -or @($stated | Where-Object { $_ -isnot [string] }).Count -or @($stated | Sort-Object -CaseSensitive -Unique).Count -ne $stated.Count) { $errors.Add("source coverage $key needs unique statement_ids"); continue }
        $status = $entry['status']; $omitted = $entry['context_omitted']
        if ($status -ceq 'omitted') {
            if ($stated.Count -or $actual.Count -or $omitted -cne $units[$unitId]['source_text'] -or -not $entry['reason']) { $errors.Add("omitted source coverage $key needs no output, its complete source_text and a reason") }
        } elseif ($status -cin @('used', 'shortened')) {
            if ($actual.Count -eq 0 -or $actual.Count -ne $stated.Count -or @($actual | Where-Object { $stated -cnotcontains $_ }).Count) { $errors.Add("source coverage $key must list exactly its supported output statements") }
            if ($status -ceq 'used' -and $omitted -cne 'none') { $errors.Add("used source coverage $key needs context_omitted none") }
            if ($status -ceq 'shortened' -and ($omitted -isnot [string] -or -not $omitted -or $omitted -ceq 'none' -or -not $units[$unitId]['source_text'].Contains($omitted, [System.StringComparison]::Ordinal) -or -not $entry['reason'])) { $errors.Add("shortened source coverage $key needs literal omitted source text and a reason") }
        } else { $errors.Add("source coverage $key has unsupported status") }
    }
    foreach ($unitId in $units.Keys) { foreach ($formatId in $FormatIds) { if (-not $coverage.Contains((Get-ContractKey -Parts @($unitId, $formatId)))) { $errors.Add("source unit $unitId has no retained/shortened/omitted coverage for $formatId") } } }
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
        $frameContentTypes = @{}
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
            if ($headers -ccontains 'frame_id') {
                $frameId = $row['frame_id'].Trim()
                $contentType = $row['content_type'].Trim()
                foreach ($column in $csvFrameColumns) {
                    if (-not $row[$column].Trim()) { $localErrors.Add("$([System.IO.Path]::GetFileName($Path)): CSV row $lineNumber has empty frame field $column") }
                }
                if ($contentType -cnotin $videoContentTypes) { $localErrors.Add("$([System.IO.Path]::GetFileName($Path)): CSV row $lineNumber has unsupported frame content_type '$contentType'") }
                if ($frameId) {
                    if (-not $frameContentTypes.ContainsKey($frameId)) { $frameContentTypes[$frameId] = [System.Collections.Generic.List[string]]::new() }
                    $frameContentTypes[$frameId].Add($contentType)
                } else { $localErrors.Add("$([System.IO.Path]::GetFileName($Path)): CSV row $lineNumber has an empty frame_id") }
            }
            $statements[$statementId] = $outputText
        }
        if ($headers -ccontains 'frame_id') {
            foreach ($frameId in $frameContentTypes.Keys) {
                $types = @($frameContentTypes[$frameId])
                $transcriptCount = @($types | Where-Object { $_ -ceq 'accessibility_transcript' }).Count
                if ($transcriptCount -ne 1) { $localErrors.Add("$([System.IO.Path]::GetFileName($Path)): frame $frameId needs exactly one accessibility_transcript row") }
                if (-not @($types | Where-Object { $_ -cin @('on_screen_copy', 'narration', 'caption') }).Count) { $localErrors.Add("$([System.IO.Path]::GetFileName($Path)): frame $frameId has no visual or spoken copy row") }
            }
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
    if ($statements.Count -eq 0) {
        if ($extension -in @('.yaml', '.yml') -and $text -match '(?m)^source_report:\s*$') { return @{ Statements = $statements; Errors = $localErrors.ToArray() } }
        $localErrors.Add("$([System.IO.Path]::GetFileName($Path)): no statement_id fields found")
    }
    return @{ Statements = $statements; Errors = $localErrors.ToArray() }
}

function Get-ProvenanceHashes {
    param([Parameter(Mandatory = $true)][string]$Path)
    $extension = [System.IO.Path]::GetExtension($Path).ToLowerInvariant()
    $parentHashes = [System.Collections.Generic.List[string]]::new()
    $deliverableRoles = @{}
    $sourceHash = $null
    $inventoryPointer = $null
    $supportPointer = $null
    if ($extension -eq '.csv') {
        $data = Read-StrictCsv -Path $Path
        $records = @($data.Records)
        if ($records.Count -gt 0) {
            $headers = @($records[0].Fields)
            $hashIndex = [Array]::IndexOf($headers, 'parent_report_hash')
            if ($hashIndex -ge 0) {
                for ($i = 1; $i -lt $records.Count; $i++) {
                    $fields = @($records[$i].Fields)
                    if ($fields.Count -gt $hashIndex -and [string]$fields[$hashIndex]) { $parentHashes.Add(([string]$fields[$hashIndex]).Trim()) }
                }
            }
        }
    } elseif ($extension -eq '.md') {
        $lines = [System.IO.File]::ReadAllLines($Path, [System.Text.Encoding]::UTF8)
        if ($lines.Count -gt 1 -and $lines[0].Trim() -eq '---') {
            $end = -1
            for ($i = 1; $i -lt $lines.Count; $i++) { if ($lines[$i].Trim() -eq '---') { $end = $i; break } }
            if ($end -gt 0) {
                $header = $lines[1..($end - 1)] -join "`n"
                $match = [regex]::Match($header, '(?m)^\s*parent_report_hash:\s*["'']?([^\r\n"'']+)["'']?\s*$')
                if ($match.Success) { $parentHashes.Add($match.Groups[1].Value.Trim()) }
            }
        }
    } elseif ($extension -eq '.json') {
        try {
            $document = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($document.source_report.hash) { $sourceHash = [string]$document.source_report.hash }
            $inventoryPointer = $document.source_inventory
            $supportPointer = $document.statement_support
            foreach ($item in @($document.deliverables)) {
                if ($item.deliverable_id) {
                    if ($deliverableRoles.ContainsKey([string]$item.deliverable_id)) { throw "manifest has duplicate deliverable_id $($item.deliverable_id)" }
                    $deliverableRoles[[string]$item.deliverable_id] = [string]$item.role
                }
            }
            $parentMatches = [regex]::Matches([System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8), '"parent_report_hash"\s*:\s*"([^"]+)"')
            foreach ($match in $parentMatches) { $parentHashes.Add($match.Groups[1].Value.Trim()) }
        } catch { $errors.Add("cannot read JSON provenance: $($_.Exception.Message)") }
    } else {
        $text = [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
        $inventoryMatches = @([regex]::Matches($text, '(?m)^source_inventory:\s*(.*?)\s*$'))
        $supportMatches = @([regex]::Matches($text, '(?m)^statement_support:\s*(.*?)\s*$'))
        if ($inventoryMatches.Count -eq 1) { $inventoryPointer = $inventoryMatches[0].Groups[1].Value.Trim().Trim('"', "'") }
        if ($supportMatches.Count -eq 1) { $supportPointer = $supportMatches[0].Groups[1].Value.Trim().Trim('"', "'") }
        $parentMatches = [regex]::Matches($text, '(?m)^\s*parent_report_hash:\s*["'']?([^\r\n"'']+)["'']?\s*$')
        foreach ($match in $parentMatches) { $parentHashes.Add($match.Groups[1].Value.Trim()) }
        $deliverableSection = [regex]::Match($text, '(?ms)^deliverables:\s*\r?\n(?<section>(?:[ \t]+[^\r\n]*(?:\r?\n|$))*)')
        if ($deliverableSection.Success) {
            $sectionText = $deliverableSection.Groups['section'].Value
            $idMatches = @([regex]::Matches($sectionText, '(?m)^\s*-\s*deliverable_id:\s*["'']?([^\r\n"'']+)["'']?\s*$'))
            for ($index = 0; $index -lt $idMatches.Count; $index++) {
                $idMatch = $idMatches[$index]
                $entryEnd = if ($index + 1 -lt $idMatches.Count) { $idMatches[$index + 1].Index } else { $sectionText.Length }
                $entry = $sectionText.Substring($idMatch.Index + $idMatch.Length, $entryEnd - ($idMatch.Index + $idMatch.Length))
                $roleMatch = [regex]::Match($entry, '(?m)^\s*role:\s*["'']?([^\r\n"'']+)["'']?\s*$')
                $deliverableId = $idMatch.Groups[1].Value.Trim()
                if ($deliverableRoles.ContainsKey($deliverableId)) { throw "manifest has duplicate deliverable_id $deliverableId" }
                $deliverableRoles[$deliverableId] = if ($roleMatch.Success) { $roleMatch.Groups[1].Value.Trim() } else { '' }
            }
        }
        $sourceSection = [regex]::Match($text, '(?ms)^source_report:\s*\r?\n(?<section>(?:[ \t]+[^\r\n]*(?:\r?\n|$))*)')
        if ($sourceSection.Success) {
            $hashMatch = [regex]::Match($sourceSection.Groups['section'].Value, '(?m)^\s+hash:\s*["'']?([^\r\n"'']+)["'']?\s*$')
            if ($hashMatch.Success) { $sourceHash = $hashMatch.Groups[1].Value.Trim() }
        }
    }
    return [pscustomobject]@{ ParentHashes = @($parentHashes | Select-Object -Unique); SourceHash = $sourceHash; DeliverableRoles = $deliverableRoles; SourceInventory = $inventoryPointer; StatementSupport = $supportPointer }
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
    $rowsByStatement = @{}
    foreach ($row in $mapRows) {
        $status = $row['status']
        if ($status -notin @('used', 'shortened', 'omitted')) { $errors.Add("mapping row has unsupported status '$status'"); continue }
        if ($status -eq 'omitted') {
            if ($row['statement_id'] -or $row['output_path'] -or $row['output_text']) { $errors.Add('omitted mapping row must not claim an output statement') }
            if (-not $row['deliverable_id'] -or -not $row['output_location']) { $errors.Add('omitted mapping row needs its deliverable_id and omitted output_location') }
            if ((-not $row['claim_ids'] -and -not $row['source_locator']) -or -not $row['context_omitted'] -or -not $row['reason']) { $errors.Add('omitted mapping row needs claim_ids or source_locator, context_omitted, and reason') }
            if ($row['statement_type'] -cnotin $allowedStatementTypes) { $errors.Add('omitted mapping row needs a supported statement_type') }
            continue
        }
        $statementId = $row['statement_id']
        if (-not $statementId) { $errors.Add('used/shortened mapping row is missing statement_id'); continue }
        if ($expected.ContainsKey($statementId)) { $errors.Add("mapping has duplicate statement_id $statementId"); continue }
        foreach ($field in @('deliverable_id', 'output_path', 'output_location', 'statement_type', 'output_text')) {
            if (-not $row[$field]) { $errors.Add("mapping statement $statementId is missing $field") }
        }
        if ($row['statement_type'] -cnotin $allowedStatementTypes) { $errors.Add("mapping statement $statementId has unsupported statement_type '$($row['statement_type'])'") }
        if ($row['statement_type'] -in @('sourced_fact', 'analysis')) {
            if (-not $row['claim_ids'] -or -not $row['source_locator']) { $errors.Add("factual statement $statementId needs claim_ids and source_locator") }
        }
        if ($row['statement_type'] -eq 'source_metadata') {
            if (-not $row['source_locator']) { $errors.Add("source metadata $statementId needs its exact metadata-field locator") }
            if ($row['claim_ids']) { $errors.Add("source metadata $statementId must not be assigned unrelated claim_ids") }
        }
        if ($row['statement_type'] -eq 'recommendation' -and -not $row['reason']) { $errors.Add("recommendation $statementId needs its rationale") }
        if ($row['statement_type'] -eq 'accessibility_copy' -and (-not $row['visual_unit_id'] -or -not $row['related_statement_ids'])) { $errors.Add("accessibility copy $statementId needs visual_unit_id and related_statement_ids") }
        if ($row['statement_type'] -eq 'accessibility_copy' -and -not $row['source_locator']) { $errors.Add("accessibility copy $statementId needs an exact source locator") }
        if ($row['statement_type'] -in @('sourced_fact', 'analysis', 'recommendation', 'nonfactual') -and -not $row['visual_unit_id']) { $errors.Add("visual content $statementId needs visual_unit_id") }
        if ($row['output_path'].ToLowerInvariant().EndsWith('.md') -and $row['statement_type'] -cne 'accessibility_copy' -and -not $row['visual_unit_id']) { $errors.Add("Markdown copy $statementId needs visual_unit_id") }
        if ($status -eq 'shortened' -and (-not $row['context_omitted'] -or -not $row['reason'])) { $errors.Add("shortened statement $statementId needs omitted context and reason") }
        if (-not $row['context_retained'] -or -not $row['context_omitted']) { $errors.Add("mapping statement $statementId needs explicit context_retained and context_omitted (use 'none' when empty)") }
        $expected[$statementId] = @{ Path = $row['output_path'].Replace('\', '/'); Text = $row['output_text'] }
        $rowsByStatement[$statementId] = $row
    }

    $declared = @{}
    foreach ($relative in ($Deliverables -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })) {
        $target = Resolve-SafeArtifact -Root $root -RelativePath $relative
        $rel = [System.IO.Path]::GetRelativePath($root, $target).Replace('\', '/')
        if ($declared.ContainsKey($rel)) { $errors.Add("duplicate declared deliverable $rel") }
        else { $declared[$rel] = $target }
    }
    if ($declared.Count -eq 0) { $errors.Add('at least one deliverable must be declared') }

    $manifestSourceHashes = [System.Collections.Generic.List[string]]::new()
    $manifestDeliverableRoles = @{}
    $manifestContracts = [System.Collections.Generic.List[hashtable]]::new()
    $provenanceByPath = @{}
    $approvedTitle = $null
    foreach ($relative in $declared.Keys) {
        $provenance = Get-ProvenanceHashes -Path $declared[$relative]
        $provenanceByPath[$relative] = @($provenance.ParentHashes)
        if ($provenance.SourceHash) { $manifestSourceHashes.Add($provenance.SourceHash) }
        if ($provenance.DeliverableRoles.Count) { $manifestContracts.Add(@{ path = $relative; source_inventory = $provenance.SourceInventory; statement_support = $provenance.StatementSupport }) }
        foreach ($deliverableId in $provenance.DeliverableRoles.Keys) {
            if ($manifestDeliverableRoles.ContainsKey([string]$deliverableId)) { $errors.Add('declared manifests repeat deliverable_id entries') }
            $manifestDeliverableRoles[[string]$deliverableId] = [string]$provenance.DeliverableRoles[$deliverableId]
        }
    }
    $manifestSourceHashes = @($manifestSourceHashes | Select-Object -Unique)
    $manifestDeliverableIds = @($manifestDeliverableRoles.Keys)
    foreach ($deliverableId in $manifestDeliverableRoles.Keys) {
        if ($manifestDeliverableRoles[$deliverableId] -cnotin @('requested-format', 'supporting-artifact')) { $errors.Add("manifest deliverable $deliverableId needs role requested-format or supporting-artifact") }
    }
    $requestedFormatIds = @($manifestDeliverableRoles.Keys | Where-Object { $manifestDeliverableRoles[$_] -ceq 'requested-format' })
    $visualScopeIds = if ($requestedFormatIds.Count -gt 0) { $requestedFormatIds } else { $manifestDeliverableIds }
    $sourceHashFromFile = $null
    if ($SourceReport) {
        $sourceReportFull = [System.IO.Path]::GetFullPath($SourceReport)
        if (-not (Test-Path -LiteralPath $sourceReportFull -PathType Leaf)) { throw 'source report must exist as a regular file' }
        $sourceReportItem = Get-Item -LiteralPath $sourceReportFull -Force
        if (($sourceReportItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'source report must not be a link or reparse point' }
        $sourceHash = (Get-FileHash -LiteralPath $sourceReportFull -Algorithm SHA256).Hash.ToLowerInvariant()
        $sourceHashFromFile = "sha256:$sourceHash"
        $sourceText = [System.IO.File]::ReadAllText($sourceReportFull, [System.Text.Encoding]::UTF8)
        $titleMatch = [regex]::Match($sourceText, '(?m)^#\s+(.+?)\s*#*\s*$')
        if ($titleMatch.Success) { $approvedTitle = $titleMatch.Groups[1].Value.Trim() }
        foreach ($manifestHash in $manifestSourceHashes) {
            if ([string]$manifestHash -cne $sourceHashFromFile) { $errors.Add("manifest source hash '$manifestHash' does not match source report bytes") }
        }
    }
    if ($manifestSourceHashes.Count -gt 1) { $errors.Add('declared manifests disagree on the canonical source-report hash') }
    $knownManifestHashes = @($manifestSourceHashes | Where-Object { $_ -cne 'unknown' })
    if ($sourceHashFromFile -or $knownManifestHashes.Count -eq 1) {
        $canonicalHash = if ($sourceHashFromFile) { $sourceHashFromFile } else { [string]$knownManifestHashes[0] }
        foreach ($relative in $provenanceByPath.Keys) {
            foreach ($value in $provenanceByPath[$relative]) {
                if ([string]$value -cne $canonicalHash) { $errors.Add("$relative parent_report_hash '$value' does not match manifest source hash") }
            }
        }
    }
    if ($approvedTitle) {
        $formatRows = @($mapRows | Where-Object {
            $_['status'] -ne 'omitted' -and
            $declared.ContainsKey($_['output_path'].Replace('\', '/')) -and
            -not [System.IO.Path]::GetFileName($_['output_path']).StartsWith('derivative-manifest', [System.StringComparison]::OrdinalIgnoreCase) -and
            ($visualScopeIds.Count -eq 0 -or $visualScopeIds -ccontains $_['deliverable_id'])
        })
        $formatIds = if ($visualScopeIds.Count -gt 0) { $visualScopeIds } else { @($formatRows | ForEach-Object { $_['deliverable_id'] } | Select-Object -Unique) }
        foreach ($formatId in $formatIds) {
            $copyRows = @($formatRows | Where-Object { $_['deliverable_id'] -ceq $formatId -and $_['statement_type'] -cne 'accessibility_copy' })
            $visibleCopy = (@($copyRows | ForEach-Object { $_['output_text'] }) -join "`n")
            if (-not $visibleCopy.Contains($approvedTitle, [System.StringComparison]::Ordinal)) { $errors.Add("deliverable $formatId must include the exact approved report title as visible copy") }
        }
    }

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

    $visualUnits = @{}
    $accessibilityRows = @{}
    foreach ($row in $mapRows) {
        if ($visualScopeIds.Count -gt 0 -and $visualScopeIds -cnotcontains $row['deliverable_id']) { continue }
        $unit = $row['visual_unit_id']
        if (-not $unit -or $row['status'] -eq 'omitted') { continue }
        $unitKey = "$($row['output_path'])::$unit"
        if ($row['statement_type'] -eq 'accessibility_copy') {
            if (-not $accessibilityRows.ContainsKey($unitKey)) { $accessibilityRows[$unitKey] = [System.Collections.Generic.List[hashtable]]::new() }
            $accessibilityRows[$unitKey].Add($row)
        } else {
            if (-not $visualUnits.ContainsKey($unitKey)) { $visualUnits[$unitKey] = [System.Collections.Generic.List[string]]::new() }
            $visualUnits[$unitKey].Add($row['statement_id'])
        }
    }
    foreach ($unitKey in $visualUnits.Keys) {
        $unit = $unitKey.Substring($unitKey.LastIndexOf('::', [System.StringComparison]::Ordinal) + 2)
        if (-not $accessibilityRows.ContainsKey($unitKey)) { $errors.Add("visual unit $unit has no accessibility_copy mapping row"); continue }
        $accessRows = @($accessibilityRows[$unitKey])
        if ($accessRows.Count -ne 1) { $errors.Add("visual unit $unit needs exactly one accessibility_copy mapping row") }
        $expectedRelated = @($visualUnits[$unitKey] | Sort-Object -Unique)
        foreach ($accessRow in $accessRows) {
            $relatedList = @($accessRow['related_statement_ids'] -split ';' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
            $related = @($relatedList | Sort-Object -CaseSensitive -Unique)
            if ($related.Count -ne $relatedList.Count) { $errors.Add("accessibility_copy for visual unit $unit has duplicate related_statement_ids") }
            if (Compare-Object -ReferenceObject $expectedRelated -DifferenceObject $related) { $errors.Add("accessibility_copy for visual unit $unit must reference every visual statement_id exactly") }
            $normalizedAccessText = Normalize-AccessibleText -Text $accessRow['output_text']
            foreach ($sourceStatementId in $visualUnits[$unitKey]) {
                if (-not $expected.ContainsKey($sourceStatementId)) { continue }
                $normalizedSourceText = Normalize-AccessibleText -Text $expected[$sourceStatementId].Text
                if ($normalizedSourceText -and -not $normalizedAccessText.Contains($normalizedSourceText, [System.StringComparison]::Ordinal)) { $errors.Add("accessibility_copy for visual unit $unit must preserve statement $sourceStatementId verbatim") }
            }
            $requiredClaims = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
            foreach ($sourceStatementId in $visualUnits[$unitKey]) {
                if (-not $rowsByStatement.ContainsKey($sourceStatementId)) { continue }
                foreach ($claimId in ($rowsByStatement[$sourceStatementId]['claim_ids'] -split ';')) {
                    if ($claimId.Trim()) { [void]$requiredClaims.Add($claimId.Trim()) }
                }
            }
            $accessClaims = @($accessRow['claim_ids'] -split ';' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
            foreach ($claimId in $requiredClaims) {
                if ($accessClaims -cnotcontains $claimId) { $errors.Add("accessibility_copy for visual unit $unit must carry related claim_id $claimId") }
            }
        }
    }
    foreach ($unitKey in $accessibilityRows.Keys) {
        if (-not $visualUnits.ContainsKey($unitKey)) { $errors.Add("accessibility_copy mapping $($accessibilityRows[$unitKey][0]['statement_id']) has no matching visual copy unit") }
    }

    foreach ($relative in $declared.Keys) {
        if ([System.IO.Path]::GetExtension($declared[$relative]).ToLowerInvariant() -ne '.csv') { continue }
        try {
            $csvData = Read-StrictCsv -Path $declared[$relative]
            $records = @($csvData.Records)
            if ($records.Count -lt 2 -or @($records[0].Fields) -cnotcontains 'frame_id') { continue }
            $headers = @($records[0].Fields)
            $frameIndex = [Array]::IndexOf($headers, 'frame_id')
            $statementIndex = [Array]::IndexOf($headers, 'statement_id')
            $typeIndex = [Array]::IndexOf($headers, 'content_type')
            for ($recordIndex = 1; $recordIndex -lt $records.Count; $recordIndex++) {
                $fields = @($records[$recordIndex].Fields)
                if ($fields.Count -ne $headers.Count) { continue }
                $frameId = [string]$fields[$frameIndex]
                $statementId = [string]$fields[$statementIndex]
                $contentType = [string]$fields[$typeIndex]
                if (-not $rowsByStatement.ContainsKey($statementId)) { continue }
                $mappedRow = $rowsByStatement[$statementId]
                if ($mappedRow['visual_unit_id'] -cne $frameId) { $errors.Add("$relative mapping for $statementId must use frame_id $frameId as visual_unit_id") }
                if ($contentType -ceq 'accessibility_transcript' -and $mappedRow['statement_type'] -cne 'accessibility_copy') { $errors.Add("$relative accessibility_transcript $statementId must be mapped as accessibility_copy") }
                if ($contentType -cne 'accessibility_transcript' -and $mappedRow['statement_type'] -ceq 'accessibility_copy') { $errors.Add("$relative accessibility_copy $statementId must use accessibility_transcript content_type") }
            }
        } catch { $errors.Add("$relative frame cross-check failed: $($_.Exception.Message)") }
    }
    if ($SourceReport) {
        if (-not $SourceInventory) { $SourceInventory = Join-Path $root 'source-inventory.json' }
        if (-not $StatementSupport) { $StatementSupport = Join-Path $root 'statement-support.csv' }
        Test-SourceContract -Root $root -Rows @($mapRows) -FormatIds $requestedFormatIds -SourceText $sourceText -SourceHash $sourceHashFromFile -InventoryPath $SourceInventory -SupportPath $StatementSupport
    }
} catch {
    $errors.Add($_.Exception.Message)
}

if ($errors.Count -gt 0) {
    Write-Output "Derivative traceability validation failed with $($errors.Count) issue(s):"
    foreach ($message in $errors) { Write-Output "- $message" }
    exit 1
}
if ($StructuralOnly) { Write-Output 'Structural checks passed only; source completeness and semantic support NOT VERIFIED; not a handoff pass.' }
else { Write-Output 'Derivative traceability validation passed: declared output and source-inventory records reconcile; semantic support remains the documented manual review.' }
exit 0

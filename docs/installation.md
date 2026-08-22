# Installation

Use the latest stable [GitHub release](https://github.com/swetankz/report-skills/releases) for normal installation. A release tag and matching checksum provide a version-pinned installation target; `main` is the moving development branch. Install a GitHub pre-release only when intentionally evaluating a release candidate.

This guide installs the complete Report Skills plugin into a personal local marketplace for private testing. These steps do not publish or share the plugin.

## Before you begin

You need:

- Codex in the ChatGPT desktop app or Codex CLI.
- The built-in `$plugin-creator` skill.
- Permission to create files in your user profile.
- The Report Skills plugin archive and its matching SHA-256 sidecar.

Choose one release and download both of these files from that same release:

- `report-skills-<version>.zip`
- `report-skills-<version>.zip.sha256`

Do not use `report-skills-source-<version>.zip` for normal plugin installation. The source archive is intended for source inspection and development.

The commands below use `0.2.0-rc.1` as a concrete example. Replace that value when installing another release. For this RC, the published plugin SHA-256 is:

```text
1e4bdb6aa37c61e2232520809a1b87f2345de62799e81b6a00c4ac69eb43b7bc
```

Always verify the downloaded archive against the sidecar from the same release.

Each command block below redeclares the variables it needs, so it can be copied into a fresh shell independently.

## Windows

### Open PowerShell

Open the Downloads folder in File Explorer, right-click an empty area, and select **Open in Terminal**. Confirm that the prompt begins with `PS`; otherwise open a PowerShell tab.

Alternatively, open PowerShell and run:

```powershell
Set-Location -LiteralPath "$env:USERPROFILE\Downloads"
```

If your browser saves downloads elsewhere, including a redirected or OneDrive-managed Downloads folder, replace `$downloadDirectory` in the following blocks with the folder that actually contains the files.

### Verify the checksum

```powershell
$version = "0.2.0-rc.1"
$downloadDirectory = Join-Path $env:USERPROFILE "Downloads"
$pluginZip = Join-Path $downloadDirectory "report-skills-$version.zip"
$pluginSidecar = "$pluginZip.sha256"

$expectedHash = (
    ((Get-Content -Raw -LiteralPath $pluginSidecar).Trim() -split '\s+')[0]
).ToLowerInvariant()

$actualHash = (
    Get-FileHash -LiteralPath $pluginZip -Algorithm SHA256
).Hash.ToLowerInvariant()

if ($actualHash -ne $expectedHash) {
    throw "Checksum verification failed. Do not install this archive."
}

"Checksum verified: $actualHash"
```

If verification fails, stop. Download the ZIP and sidecar again from the same GitHub release.

### Extract the plugin

```powershell
$version = "0.2.0-rc.1"
$downloadDirectory = Join-Path $env:USERPROFILE "Downloads"
$pluginZip = Join-Path $downloadDirectory "report-skills-$version.zip"
$destination = Join-Path $downloadDirectory "report-skills-$version"

if (Test-Path -LiteralPath $destination) {
    throw "The destination already exists. Inspect it or choose a new empty folder."
}

Expand-Archive -LiteralPath $pluginZip -DestinationPath $destination

$manifest = Join-Path $destination ".codex-plugin\plugin.json"
if (-not (Test-Path -LiteralPath $manifest)) {
    throw "Plugin manifest not found. Confirm that you downloaded the plugin archive."
}

"Plugin extracted to:"
(Resolve-Path -LiteralPath $destination).Path
```

Copy the absolute path printed by the final command. You will use it in Codex.

## macOS

### Open Terminal

Open Terminal and move to the directory containing the downloaded files:

```bash
download_directory="$HOME/Downloads"
cd "$download_directory"
```

If your browser uses a different or localized download directory, replace the value of `download_directory`.

### Verify the checksum

```bash
version="0.2.0-rc.1"
download_directory="$HOME/Downloads"
cd "$download_directory"
shasum -a 256 -c "report-skills-${version}.zip.sha256"
```

A successful result ends with:

```text
report-skills-0.2.0-rc.1.zip: OK
```

If verification fails, stop. Download the ZIP and sidecar again from the same GitHub release.

### Extract the plugin

```bash
version="0.2.0-rc.1"
download_directory="$HOME/Downloads"
archive="$download_directory/report-skills-${version}.zip"
destination="$download_directory/report-skills-${version}"

if [ -e "$destination" ]; then
    echo "The destination already exists. Inspect it or choose a new empty folder."
    exit 1
fi

mkdir "$destination"
unzip "$archive" -d "$destination"

if [ ! -f "$destination/.codex-plugin/plugin.json" ]; then
    echo "Plugin manifest not found. Confirm that you downloaded the plugin archive."
    exit 1
fi

echo "Plugin extracted to:"
cd "$destination" && pwd
```

Copy the absolute path printed by the final command.

## Linux

### Open Terminal

Move to the directory containing the downloaded files:

```bash
download_directory="$HOME/Downloads"
cd "$download_directory"
```

If your browser uses a different or localized download directory, replace the value of `download_directory`.

### Verify the checksum

```bash
version="0.2.0-rc.1"
download_directory="$HOME/Downloads"
cd "$download_directory"
sha256sum --check "report-skills-${version}.zip.sha256"
```

A successful result ends with:

```text
report-skills-0.2.0-rc.1.zip: OK
```

If `sha256sum` is unavailable but `shasum` is installed, use:

```bash
version="0.2.0-rc.1"
download_directory="$HOME/Downloads"
cd "$download_directory"
shasum -a 256 -c "report-skills-${version}.zip.sha256"
```

If verification fails, stop. Download the ZIP and sidecar again from the same GitHub release.

### Extract the plugin

```bash
version="0.2.0-rc.1"
download_directory="$HOME/Downloads"
archive="$download_directory/report-skills-${version}.zip"
destination="$download_directory/report-skills-${version}"

if [ -e "$destination" ]; then
    echo "The destination already exists. Inspect it or choose a new empty folder."
    exit 1
fi

mkdir "$destination"
unzip "$archive" -d "$destination"

if [ ! -f "$destination/.codex-plugin/plugin.json" ]; then
    echo "Plugin manifest not found. Confirm that you downloaded the plugin archive."
    exit 1
fi

echo "Plugin extracted to:"
cd "$destination" && pwd
```

If `unzip` is unavailable, install it using your distribution's package manager or extract the archive with your desktop file manager. Copy the absolute extracted path before continuing.

## Add the plugin to a personal marketplace

Open a new Codex task. This step happens in Codex, not in PowerShell or Terminal.

Paste the following prompt and replace the quoted marker with the absolute extracted path printed in the previous section:

```text
$plugin-creator Add the existing Report Skills plugin at
"PASTE_THE_ABSOLUTE_EXTRACTED_PATH_HERE"
to my personal local marketplace for testing.

Preserve the plugin contents unchanged. Do not publish or share it.
```

OpenAI documents `$plugin-creator` as the Codex invocation for the built-in plugin creator. The same skill may appear as `@plugin-creator` on ChatGPT surfaces. It can wire an existing plugin folder into a local marketplace. See [Package your plugin](https://developers.openai.com/plugins/build/plugins).

Review the result before continuing. Confirm that:

- `.codex-plugin/plugin.json` was found and validated.
- The personal marketplace exists at `~/.agents/plugins/marketplace.json`.
- The Report Skills entry records the `source.path` reported by `$plugin-creator`.
- The plugin contents were preserved unchanged.
- No publishing or sharing action occurred.

The plugin directory itself is not a fixed Codex path. Use the destination reported by `$plugin-creator`; the marketplace entry's `source.path` is authoritative. Valid layouts include `~/plugins/report-skills` and `~/.codex/plugins/report-skills` when the marketplace points to them correctly. Here, `~` means the current user's home directory.

### Optional marketplace verification on Windows

```powershell
$marketplacePath = "$env:USERPROFILE\.agents\plugins\marketplace.json"
if (-not (Test-Path -LiteralPath $marketplacePath)) {
    throw "Personal marketplace not found."
}

$entry = (Get-Content -Raw -LiteralPath $marketplacePath | ConvertFrom-Json).plugins |
    Where-Object { $_.name -eq "report-skills" }

if ($null -eq $entry) {
    throw "Report Skills entry not found in the personal marketplace."
}

$sourcePath = if ($entry.source -is [string]) {
    $entry.source
} else {
    $entry.source.path
}

[pscustomobject]@{
    Name = $entry.name
    SourcePath = $sourcePath
}
```

Confirm that `SourcePath` points to the plugin directory reported by `$plugin-creator`.

### Optional marketplace verification on macOS or Linux

```bash
marketplace="$HOME/.agents/plugins/marketplace.json"

if [ ! -f "$marketplace" ]; then
    echo "Personal marketplace not found."
    exit 1
fi

grep -n -A 12 '"name"[[:space:]]*:[[:space:]]*"report-skills"' "$marketplace"
```

Confirm that the output includes the Report Skills entry and the plugin path reported by `$plugin-creator`.

## Install Report Skills

### ChatGPT desktop app

1. Fully quit and reopen the ChatGPT desktop app.
2. Open the **Plugins Directory**.
3. Select **Personal**.
4. Open **Report Skills**.
5. Select the plus button to install it.
6. Start a new Codex task after installation.

The restart reloads the local marketplace. A new task makes the newly installed skills available.

### Codex CLI

Start Codex from Terminal or PowerShell:

```text
codex
```

Then enter this command inside the interactive Codex session:

```text
/plugins
```

If Report Skills appears in the configured personal marketplace, open it and install it. Start a new CLI session before using the skills.

If it does not appear, exit the interactive Codex session or open a second PowerShell/Terminal window. Run this command in the operating-system shell:

```text
codex plugin marketplace list
```

Then use the desktop workflow or follow OpenAI's local marketplace CLI guidance rather than editing Codex configuration by hand.

Codex CLI includes a plugin browser, but plugins are not supported in the Codex IDE extension. See OpenAI's [Plugins guide](https://learn.chatgpt.com/docs/plugins).

## Test the installation

In a new Codex task, run this self-contained synthetic test:

```text
Use $report-skills to create a small source-backed analytical report from this synthetic evidence set:

- Onboarding completion table: 40 of 50 participants completed onboarding.
- Support log summary: 12 of the 50 participants asked for help with account verification.
- Interview notes: 3 participants said the verification instructions were unclear.

Treat these as supplied synthetic sources, state the evidence limitations, work locally, and stop before any external publication.
```

To test one specialist directly, run this separate self-contained prompt:

```text
Use $evidence-first-report to create a source-backed draft from this synthetic evidence set:

- Onboarding completion table: 40 of 50 participants completed onboarding.
- Support log summary: 12 of the 50 participants asked for help with account verification.
- Interview notes: 3 participants said the verification instructions were unclear.

Treat these as supplied synthetic sources, preserve unresolved evidence gaps, state the evidence limitations, and work locally.
```

The complete plugin should expose the `report-skills` router and the ten specialist skills listed in the [skill catalogue](skill-catalogue.md).

### Platform validation status

The personal-marketplace registration and installation flow was verified on Windows using an extracted `v0.2.0-rc.1` source snapshot. The released plugin ZIP's checksum, extraction, and root manifest were clean-smoke-tested separately on Windows. An end-to-end marketplace installation from the plugin ZIP, and the complete macOS and Linux flows, have not yet been recorded as release evidence.

## Troubleshooting

### PowerShell cannot find the archive

List the matching files in Downloads:

```powershell
Get-ChildItem -LiteralPath "$env:USERPROFILE\Downloads" -Filter "report-skills*.zip*"
```

Use the exact filename returned by PowerShell.

### Checksum verification fails

Do not install the archive. Download the ZIP and its sidecar again from the same release.

### The plugin manifest is missing

Confirm that you downloaded `report-skills-<version>.zip`, not the source archive. Also check that extraction did not create an unexpected nested directory above `.codex-plugin/plugin.json`.

### Report Skills does not appear under Personal

Confirm that `~/.agents/plugins/marketplace.json` exists, inspect the Report Skills entry's `source.path`, and verify that the referenced plugin directory contains `.codex-plugin/plugin.json`. Then fully restart the desktop app.

### The plugin is installed but the skills are unavailable

Start a completely new Codex task or CLI session. Existing sessions may not reload newly installed plugin skills.

### The CLI does not show the personal marketplace

Run `codex plugin marketplace list`. If the marketplace is absent, use the desktop workflow or configure the marketplace through the supported Codex CLI marketplace commands.

### Personal plugins are unavailable

An organization-managed environment may restrict personal marketplaces or plugin installation. Contact the workspace administrator if the Personal section is unavailable.

## Uninstall Report Skills

Open Report Skills from a supported plugin browser and select **Uninstall plugin**, when that action is available. Start a new task or CLI session afterward. Workspace-controlled plugins may not expose the uninstall action.

Uninstalling the plugin does not change the public GitHub repository. Removing an extracted archive or personal marketplace source is a separate local cleanup action.

## Install one skill instead

Use a version-pinned release-tag subpath `skills/<skill-name>` through the Codex skill installer. For example, open a new Codex task and run:

```text
$skill-installer Install the Report Skills specialist from
https://github.com/swetankz/report-skills/tree/v0.2.0-rc.1/skills/evidence-first-report
into my personal Codex skills directory.

Install from this exact release tag, not from main. Do not publish or share anything.
```

Replace the release tag and final skill directory when installing another published version or specialist. Each skill folder is self-contained and must work after the rest of the repository is removed. Start a new Codex task after installation.

## Install multiple selected skills

Pass multiple `skills/<skill-name>` paths to the skill installer when the complete plugin is unnecessary. Pin every path to the same published release tag. Do not copy `source/` as a runtime dependency; it exists for maintainers and generation only.

## Preserve a reproducible installation record

For reproducible installation, record the release tag and asset checksum. Release verification covers the published asset, its checksum, the complete plugin package, and representative standalone skill subpaths.

## Validate a standalone skill installation

- Confirm the installed folder contains `SKILL.md` and `agents/openai.yaml`.
- Confirm every local link and script resolves without the source repository.
- Invoke the skill explicitly through its default prompt.
- Confirm sensitive skills stop without approval or verified live state.

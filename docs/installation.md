# Installation

Report Skills is packaged as one plugin with shared skill bodies for Codex and ZCode. The repository carries a Codex manifest at `.codex-plugin/plugin.json`, a ZCode manifest at `.zcode-plugin/plugin.json`, and a root `marketplace.json`. These files define the intended installation paths; they do not establish that either client has passed end-to-end installation and activation checks for the current candidate.

Use a published stable [GitHub release](https://github.com/swetankz/report-skills/releases) for normal installation when one is available. Version `0.2.0` is currently unreleased and awaits fresh qualification. A published release tag and matching checksum provide a version-pinned installation target; `main` is the moving development branch. Install a GitHub pre-release only when intentionally evaluating a release candidate. See [Platform validation status](#platform-validation-status) for the evidence recorded so far.

This guide covers both clients. For ZCode, see [Install in ZCode](#install-in-zcode). The remaining sections walk through the Codex complete-plugin flow on Windows, macOS, and Linux, followed by selected-skill alternatives.

## Install in ZCode

The repository root includes a ZCode plugin marketplace descriptor, and current plugin builds include it alongside both client manifests. The steps below describe the intended flow and still require end-to-end validation against the actual candidate ZIP.

### Marketplace install from GitHub

This path is for development testing unless the client records an exact published release ref. For a reproducible candidate installation, use the checksum-verified release ZIP through the local-directory path below.

1. Open ZCode **Settings → Plugin Management → Discover**.
2. Select **+** and add a marketplace from the GitHub repository `swetankz/report-skills`.
3. Install the `report-skills` plugin from the marketplace entry.

Skills appear namespaced as `report-skills:<skill-name>`, for example `report-skills:evidence-first-report`.

### Local directory install

For a version-pinned candidate, verify and extract its plugin ZIP, then select **+** in the Discover tab, choose a local directory as the marketplace source, and point it at the extracted release folder. Confirm that the folder contains `.zcode-plugin/plugin.json` and `marketplace.json`, then install `report-skills` from it. A checkout of `main` can be used separately for development testing; record its commit rather than treating it as a released version.

### Individual skills and cross-tool use

Copy a self-contained `skills/<skill-name>` folder into `~/.agents/skills/` to use it across tools that share that skill root. Each folder is self-contained and must work after the rest of the repository is removed. The `agents/openai.yaml` file inside each package is Codex-specific metadata; ZCode reads `SKILL.md` and safely ignores it.

### Validate the ZCode installation

- Confirm the plugin appears in **Plugin Management** and its skills are listed as `report-skills:<skill-name>` in **Settings → Skills** and the `/` menu.
- Invoke an ordinary skill with a topical request, and confirm `report-skills`, `sites-release-manager`, and `pencil-safe-editor` activate only for the exact `$report-skills`, `$sites-release-manager`, and `$pencil-safe-editor` tokens.
- Confirm every local link and script resolves without the source repository.
- Confirm sensitive skills stop without approval or verified live state.

## Install the complete plugin in Codex

The following Codex flow installs the complete Report Skills plugin into a personal local marketplace for private testing. These steps do not publish or share the plugin.

## Before you begin

You need:

- Codex in the ChatGPT desktop app or Codex CLI.
- Permission to create local files and register/install a local marketplace plugin.
- The Report Skills plugin archive and its matching SHA-256 sidecar.

The manual route does not require `$plugin-creator` or a model call. The optional creator-assisted route requires that skill to be available. The CLI commands below follow Codex CLI 0.166.0; inspect `codex plugin --help` if your installed version differs.

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

You can create a local marketplace without `$plugin-creator`. Use a new wrapper directory containing a Codex catalog and an unchanged copy of the checksum-verified, extracted plugin. The plugin ZIP is not itself a Codex marketplace: its root `marketplace.json` is the ZCode catalog, not the nested catalog Codex discovers. Do not rename that file or change the plugin payload.

Keep the wrapper directory after installation; Codex needs it to refresh the local source. The example below uses `report-skills-local` as the marketplace name and creates this layout:

```text
report-skills-marketplace/
  .agents/plugins/marketplace.json
  plugins/report-skills/
    .codex-plugin/plugin.json
    skills/
```

The catalog's `source.path` is relative to the wrapper root, not to `.agents/plugins/`. Creating the wrapper only writes local files. Registering or installing it later changes Codex configuration/cache; none of these actions publishes the plugin.

### Create the wrapper on Windows

Replace the quoted source marker with the absolute extracted plugin path from the checksum/extraction steps. Run this in PowerShell. It stops instead of overwriting an existing wrapper:

```powershell
$ErrorActionPreference = "Stop"
$pluginSource = (Resolve-Path -LiteralPath "PASTE_THE_ABSOLUTE_EXTRACTED_PATH_HERE").Path
$marketplaceRoot = Join-Path $env:USERPROFILE "report-skills-marketplace"
$sourceManifest = Join-Path $pluginSource ".codex-plugin/plugin.json"

if (-not (Test-Path -LiteralPath $sourceManifest -PathType Leaf)) {
    throw "The source is not an extracted Report Skills plugin."
}
if (Test-Path -LiteralPath $marketplaceRoot) {
    throw "The marketplace directory already exists. Inspect it or choose a new empty path."
}

$catalogDirectory = Join-Path $marketplaceRoot ".agents/plugins"
[System.IO.Directory]::CreateDirectory($catalogDirectory) | Out-Null
[System.IO.Directory]::CreateDirectory((Join-Path $marketplaceRoot "plugins")) | Out-Null
Copy-Item -LiteralPath $pluginSource -Destination (Join-Path $marketplaceRoot "plugins/report-skills") -Recurse -Force

$catalogJson = @'
{
  "name": "report-skills-local",
  "interface": {"displayName": "Report Skills local"},
  "plugins": [
    {
      "name": "report-skills",
      "source": {"source": "local", "path": "./plugins/report-skills"},
      "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
      "category": "Productivity"
    }
  ]
}
'@
$catalogPath = Join-Path $catalogDirectory "marketplace.json"
[System.IO.File]::WriteAllText($catalogPath, $catalogJson + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
"Marketplace root: $marketplaceRoot"
```

The catalog is written as UTF-8 without a byte-order mark. Confirm that `plugins/report-skills/.codex-plugin/plugin.json` exists beneath the printed root before registering it.

### Create the wrapper on macOS or Linux

Replace the source marker with the absolute extracted plugin path. This block stops on a missing source or an existing wrapper, including a dangling link:

```bash
set -eu
plugin_source='PASTE_THE_ABSOLUTE_EXTRACTED_PATH_HERE'
marketplace_root="$HOME/report-skills-marketplace"

case "$plugin_source" in
  /*) ;;
  *) printf '%s\n' "Use the absolute extracted plugin path."; exit 1 ;;
esac
if [ ! -f "$plugin_source/.codex-plugin/plugin.json" ]; then
    printf '%s\n' "The source is not an extracted Report Skills plugin."
    exit 1
fi
if [ -e "$marketplace_root" ] || [ -L "$marketplace_root" ]; then
    printf '%s\n' "The marketplace directory already exists. Inspect it or choose a new empty path."
    exit 1
fi

mkdir -p "$marketplace_root/.agents/plugins" "$marketplace_root/plugins"
cp -R "$plugin_source" "$marketplace_root/plugins/report-skills"
catalog_path="$marketplace_root/.agents/plugins/marketplace.json"
cat > "$catalog_path" <<'JSON'
{
  "name": "report-skills-local",
  "interface": {"displayName": "Report Skills local"},
  "plugins": [
    {
      "name": "report-skills",
      "source": {"source": "local", "path": "./plugins/report-skills"},
      "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
      "category": "Productivity"
    }
  ]
}
JSON
printf 'Marketplace root: %s\n' "$marketplace_root"
```

Confirm that `plugins/report-skills/.codex-plugin/plugin.json` exists beneath the printed root before registering it.

### Register the manual marketplace

Use the wrapper **directory**, not the JSON file or the extracted plugin directory, as the marketplace source. Replace the root marker below with the exact absolute `Marketplace root` printed by the creation step. If you chose an alternate location, use that new location here; do not reset it to an older default wrapper. Run the matching block in the operating-system shell. Registration writes Codex configuration/cache but does not install or publish Report Skills.

On Windows:

```powershell
$ErrorActionPreference = "Stop"
$marketplaceRoot = (Resolve-Path -LiteralPath "PASTE_THE_ABSOLUTE_MARKETPLACE_ROOT_HERE").Path
$catalogPath = Join-Path $marketplaceRoot ".agents/plugins/marketplace.json"
$pluginManifest = Join-Path $marketplaceRoot "plugins/report-skills/.codex-plugin/plugin.json"
if (-not (Test-Path -LiteralPath $catalogPath -PathType Leaf) -or
    -not (Test-Path -LiteralPath $pluginManifest -PathType Leaf)) {
    throw "This is not the completed wrapper root printed by the creation step."
}
codex plugin marketplace add "$marketplaceRoot" --json
if ($LASTEXITCODE -ne 0) {
    throw "Codex could not register the marketplace. Resolve the reported error before continuing."
}
codex plugin marketplace list
codex plugin list --marketplace report-skills-local --available --json
```

On macOS or Linux:

```bash
set -eu
marketplace_root='PASTE_THE_ABSOLUTE_MARKETPLACE_ROOT_HERE'
case "$marketplace_root" in
  /*) ;;
  *) printf '%s\n' "Use the absolute wrapper root printed by the creation step."; exit 1 ;;
esac
if [ ! -f "$marketplace_root/.agents/plugins/marketplace.json" ] ||
   [ ! -f "$marketplace_root/plugins/report-skills/.codex-plugin/plugin.json" ]; then
    printf '%s\n' "This is not the completed wrapper root printed by the creation step."
    exit 1
fi
codex plugin marketplace add "$marketplace_root" --json
codex plugin marketplace list
codex plugin list --marketplace report-skills-local --available --json
```

Read back the results: the marketplace should resolve to the wrapper root and expose `report-skills`. Stop on a command error or a missing plugin; do not infer success from files existing on disk. This setup has not established activation or behavioral qualification. For an organization-managed restriction, ask the administrator rather than bypass the policy.

### Optional creator-assisted setup

If `$plugin-creator` is available, it can create the personal marketplace instead. Do not run both setup routes for the same plugin unless you deliberately want separate marketplace sources.

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
3. Select the local marketplace created above, or **Personal** for the creator-assisted route.
4. Open **Report Skills**.
5. Select the plus button to install it.
6. Start a new Codex task after installation.

The restart reloads the local marketplace. A new task makes the newly installed skills available.

### Codex CLI

For the manual marketplace above, run these commands in Terminal or PowerShell, outside an interactive Codex session:

```text
codex plugin add report-skills@report-skills-local --json
codex plugin list --marketplace report-skills-local --json
```

Stop if installation reports an error. Read back the installed entry and record the installed version and cache/source information actually returned by the client. Do not count the earlier `--available` listing as an installation. If you used the creator-assisted route, substitute the marketplace name it reported; do not assume it is `report-skills-local`.

Start a new session after installation. You can also inspect the plugin through the interactive browser. Start Codex from Terminal or PowerShell:

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

For the manual route, follow the [registration steps](#register-the-manual-marketplace) and check the `report-skills-local` source. For the creator-assisted route, use its reported marketplace name or the desktop workflow. Do not edit Codex configuration by hand to work around a failed command.

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

Recorded checks cover the earlier `v0.2.0-rc.1` Windows candidate: personal-marketplace registration and installation used an extracted source snapshot, while the released plugin ZIP's checksum, extraction, and root manifest were checked separately. Those checks do not qualify the current unreleased `0.2.0` candidate.

The following checks remain pending for the current candidate:

- Complete Codex marketplace installation and activation from the actual plugin ZIP.
- Complete ZCode installation and activation from the actual plugin ZIP.
- End-to-end macOS and Linux installation flows.
- Representative standalone skills installed from the exact release tag, including helper execution without the source checkout.

Treat these as documented installation paths awaiting validation. Record the exact candidate, client version, operating system, and observed results before claiming a supported release path.

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

For the creator-assisted route, confirm that `~/.agents/plugins/marketplace.json` exists and inspect the Report Skills entry's `source.path`. For the manual route, check the wrapper's `.agents/plugins/marketplace.json`, then follow the [registration steps](#register-the-manual-marketplace) and select that local source rather than assuming it appears under Personal. Verify that the resolved plugin directory contains `.codex-plugin/plugin.json`, then fully restart the desktop app.

### The plugin is installed but the skills are unavailable

Start a completely new Codex task or CLI session. Existing sessions may not reload newly installed plugin skills.

### The CLI does not show the personal marketplace

Run `codex plugin marketplace list`. If the manual `report-skills-local` source is absent, follow the [registration steps](#register-the-manual-marketplace). If registration fails, resolve that error before installing. For a creator-assisted marketplace, use its reported source name or the desktop workflow.

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

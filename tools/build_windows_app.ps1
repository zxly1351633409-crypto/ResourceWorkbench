param(
    [switch]$Clean = $true,
    [string]$AuditArchive = ""
)

$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.IO.Compression.FileSystem

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectRoot

$ForbiddenRuntimeSegments = @(
    "workbench_data",
    ".runtime",
    "reports",
    "staging",
    "previews"
)
$ForbiddenRuntimeFiles = @(
    "settings.json",
    "secret.json",
    "move_log.sqlite",
    "resource_index.sqlite",
    "review_queue.sqlite",
    "card_metadata.sqlite",
    "rename_log.sqlite",
    "upload_log.sqlite"
)
$TextAuditExtensions = @(
    ".bat", ".cfg", ".cmd", ".css", ".csv", ".env", ".htm", ".html",
    ".ini", ".js", ".json", ".log", ".md", ".ps1", ".toml", ".txt",
    ".xml", ".yaml", ".yml"
)
$MachinePathPatterns = @(
    [regex]::new(
        '(?im)(?<![A-Za-z0-9_%])[A-Za-z]:[\\/]+Users[\\/]+[^\r\n"''<>|]{2,}',
        [System.Text.RegularExpressions.RegexOptions]::CultureInvariant
    )
)
$UncPathPattern = [regex]::new(
    '(?im)(?:\\{2,}|(?<!:)//)[^\\/\s"''<>|]+[\\/]+[^\\/\s"''<>|]+',
    [System.Text.RegularExpressions.RegexOptions]::CultureInvariant
)
$CredentialPatterns = @(
    [regex]::new('(?i)\bsk-[A-Za-z0-9_-]{16,}\b'),
    [regex]::new('(?i)\bBearer\s+[A-Za-z0-9._~+/-]{20,}\b'),
    [regex]::new(
        '(?i)(?:api[_-]?key|app[_-]?secret|access[_-]?token|refresh[_-]?token)\s*["'']?\s*[:=]\s*["'']?(?!DEEPSEEK_API_KEY\b|OPENAI_API_KEY\b|P115_|<|\$\{|%)[A-Za-z0-9._~+/-]{16,}'
    )
)
$KnownMachinePaths = @(
    $ProjectRoot,
    $env:USERPROFILE,
    $env:LOCALAPPDATA,
    $env:APPDATA
)
$localSettings = Join-Path $ProjectRoot "workbench_data\settings.json"
if (Test-Path -LiteralPath $localSettings -PathType Leaf) {
    try {
        $settingsObject = Get-Content -Raw -Encoding UTF8 -LiteralPath $localSettings | ConvertFrom-Json
        foreach ($property in $settingsObject.PSObject.Properties) {
            $value = $property.Value
            if ($value -is [string] -and ($value -match '^[A-Za-z]:[\\/]' -or $value -match '^\\\\')) {
                $KnownMachinePaths += $value
            }
        }
    }
    catch {
        # A malformed local settings file is runtime state, never a build input.
    }
}
$KnownMachinePaths = @($KnownMachinePaths | Where-Object { $_ } | Select-Object -Unique)

function Get-NormalizedPackagePath {
    param([string]$Path)
    return ($Path -replace '\\', '/').TrimStart('/')
}

function Test-ForbiddenRuntimePath {
    param([string]$RelativePath)

    $normalized = Get-NormalizedPackagePath $RelativePath
    $parts = @($normalized.Split('/') | Where-Object { $_ })
    foreach ($part in $parts) {
        if ($ForbiddenRuntimeSegments -contains $part.ToLowerInvariant()) {
            return $true
        }
    }
    if ($parts.Count -gt 0) {
        $name = $parts[-1].ToLowerInvariant()
        if ($ForbiddenRuntimeFiles -contains $name -or $name.EndsWith('.log')) {
            return $true
        }
    }
    return $false
}

function Get-KnownBuildSecrets {
    # Values stay in memory and are never included in console/error output.
    $names = @("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "P115_APP_SECRET", "P115_TOKEN")
    $values = @()
    foreach ($name in $names) {
        $value = [Environment]::GetEnvironmentVariable($name)
        if ($value -and $value.Length -ge 12 -and $values -notcontains $value) {
            $values += $value
        }
    }
    return $values
}

function Test-StreamContainsKnownSecret {
    param(
        [System.IO.Stream]$Stream,
        [string[]]$KnownSecrets
    )

    if (-not $KnownSecrets -or $KnownSecrets.Count -eq 0) {
        return $false
    }
    $buffer = New-Object byte[] (1024 * 1024)
    $utf8Tail = ""
    $utf16Tail = ""
    while (($read = $Stream.Read($buffer, 0, $buffer.Length)) -gt 0) {
        $utf8 = $utf8Tail + [Text.Encoding]::UTF8.GetString($buffer, 0, $read)
        $utf16 = $utf16Tail + [Text.Encoding]::Unicode.GetString($buffer, 0, $read)
        foreach ($secret in $KnownSecrets) {
            if ($utf8.Contains($secret) -or $utf16.Contains($secret)) {
                return $true
            }
        }
        $utf8Tail = if ($utf8.Length -gt 512) { $utf8.Substring($utf8.Length - 512) } else { $utf8 }
        $utf16Tail = if ($utf16.Length -gt 512) { $utf16.Substring($utf16.Length - 512) } else { $utf16 }
    }
    return $false
}

function Read-AuditedText {
    param(
        [System.IO.Stream]$Stream,
        [long]$Length
    )

    if ($Length -gt 32MB) {
        throw "Distribution safety gate failed: oversized text payload requires manual review."
    }
    $memory = New-Object System.IO.MemoryStream
    try {
        $Stream.CopyTo($memory)
        $bytes = $memory.ToArray()
        if ($bytes.Length -ge 2 -and $bytes[0] -eq 0xFF -and $bytes[1] -eq 0xFE) {
            return [Text.Encoding]::Unicode.GetString($bytes)
        }
        if ($bytes.Length -ge 2 -and $bytes[0] -eq 0xFE -and $bytes[1] -eq 0xFF) {
            return [Text.Encoding]::BigEndianUnicode.GetString($bytes)
        }
        return [Text.Encoding]::UTF8.GetString($bytes)
    }
    finally {
        $memory.Dispose()
    }
}

function Assert-TextPayloadSafe {
    param([string]$Text)

    $normalizedText = $Text -replace '\\\\', '\'
    foreach ($pattern in $MachinePathPatterns) {
        if ($pattern.IsMatch($normalizedText)) {
            throw "Distribution safety gate failed: machine-specific path detected."
        }
    }
    foreach ($knownPath in $KnownMachinePaths) {
        $normalizedPath = $knownPath -replace '/', '\'
        if ($normalizedPath.Length -ge 3 -and $normalizedText.IndexOf($normalizedPath, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
            throw "Distribution safety gate failed: machine-specific path detected."
        }
    }
    if ($UncPathPattern.IsMatch($normalizedText)) {
        throw "Distribution safety gate failed: machine-specific path detected."
    }
    foreach ($pattern in $CredentialPatterns) {
        if ($pattern.IsMatch($Text)) {
            throw "Distribution safety gate failed: credential-like value detected."
        }
    }
}

function Assert-CleanDistributionArchive {
    param([string]$ArchivePath)

    if (-not (Test-Path -LiteralPath $ArchivePath -PathType Leaf)) {
        throw "Distribution safety gate failed: archive does not exist."
    }
    $knownSecrets = @(Get-KnownBuildSecrets)
    $archive = [IO.Compression.ZipFile]::OpenRead((Resolve-Path -LiteralPath $ArchivePath).Path)
    try {
        foreach ($entry in $archive.Entries) {
            if (-not $entry.Name) {
                continue
            }
            $normalized = Get-NormalizedPackagePath $entry.FullName
            if (Test-ForbiddenRuntimePath $normalized) {
                throw "Distribution safety gate failed: runtime/user-state entry detected."
            }
            Assert-TextPayloadSafe $normalized

            if ($knownSecrets.Count -gt 0) {
                $stream = $entry.Open()
                try {
                    if (Test-StreamContainsKnownSecret $stream $knownSecrets) {
                        throw "Distribution safety gate failed: a configured credential was embedded."
                    }
                }
                finally {
                    $stream.Dispose()
                }
            }

            $extension = [IO.Path]::GetExtension($entry.Name).ToLowerInvariant()
            if ($TextAuditExtensions -contains $extension) {
                $stream = $entry.Open()
                try {
                    $text = Read-AuditedText $stream $entry.Length
                }
                finally {
                    $stream.Dispose()
                }
                Assert-TextPayloadSafe $text
            }
        }
    }
    finally {
        $archive.Dispose()
    }
}

if ($AuditArchive) {
    Assert-CleanDistributionArchive $AuditArchive
    Write-Host "Distribution archive audit passed."
    exit 0
}

if ($Clean) {
    $rootResolved = (Resolve-Path -LiteralPath $ProjectRoot).Path
    foreach ($name in @("build", "dist")) {
        $target = Join-Path $ProjectRoot $name
        if (Test-Path -LiteralPath $target) {
            $targetResolved = (Resolve-Path -LiteralPath $target).Path
            if (-not $targetResolved.StartsWith($rootResolved, [System.StringComparison]::OrdinalIgnoreCase)) {
                throw "Refusing to clean outside project root: $targetResolved"
            }
            Remove-Item -LiteralPath $targetResolved -Recurse -Force
        }
    }
}

$srcPath = Join-Path $ProjectRoot "src"
$assetsPath = Join-Path $ProjectRoot "src\resource_workbench\assets"
$iconPath = Join-Path $assetsPath "logo.ico"
$addData = "$assetsPath;resource_workbench/assets"
$version = "0.3.1"
$versionInfoPath = Join-Path $ProjectRoot "tools\windows_version_info.txt"

if (-not (Test-Path -LiteralPath $versionInfoPath -PathType Leaf)) {
    throw "Windows version resource is missing: $versionInfoPath"
}

$env:PYTHONPATH = $srcPath

$argsList = @(
    "--noconfirm",
    "--windowed",
    "--onedir",
    "--name", "ResourceWorkbench",
    "--version-file", $versionInfoPath,
    "--paths", $srcPath,
    "--add-data", $addData,
    "--collect-submodules", "resource_workbench",
    "--collect-data", "imageio_ffmpeg",
    "--hidden-import", "PIL._tkinter_finder",
    "--hidden-import", "PySide6.QtWebEngineCore",
    "--hidden-import", "PySide6.QtWebEngineWidgets",
    "--hidden-import", "PySide6.QtWebChannel",
    "--exclude-module", "tests"
)

if (Test-Path -LiteralPath $iconPath) {
    $argsList += @("--icon", $iconPath)
}

$argsList += "src\resource_workbench\qt_app.py"

python -m PyInstaller @argsList

$appDir = Join-Path $ProjectRoot "dist\ResourceWorkbench"
if (-not (Test-Path -LiteralPath (Join-Path $appDir "ResourceWorkbench.exe"))) {
    throw "Build finished without ResourceWorkbench.exe"
}
Copy-Item -LiteralPath (Join-Path $ProjectRoot "docs\USER_GUIDE.md") -Destination (Join-Path $appDir "USER_GUIDE.md") -Force

# Distribution safety gate: runtime state is always created on the destination
# computer under %LOCALAPPDATA%; it must never be copied into the package.
$forbidden = @(
    (Join-Path $appDir "workbench_data"),
    (Join-Path $appDir "reports"),
    (Join-Path $appDir "secret.json"),
    (Join-Path $appDir "settings.json")
)
foreach ($path in $forbidden) {
    if (Test-Path -LiteralPath $path) {
        throw "Distribution safety gate failed: runtime/user-state directory detected."
    }
}
$leakedRuntimeFiles = Get-ChildItem -LiteralPath $appDir -Recurse -File -ErrorAction Stop |
    Where-Object {
        $relative = $_.FullName.Substring($appDir.Length).TrimStart('\', '/')
        Test-ForbiddenRuntimePath $relative
    }
if ($leakedRuntimeFiles) {
    throw "Distribution safety gate failed: runtime/user-state file detected."
}

$zipPath = Join-Path $ProjectRoot "dist\ResourceWorkbench-$version-win64.zip"
if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}
Compress-Archive -LiteralPath $appDir -DestinationPath $zipPath -CompressionLevel Optimal
try {
    Assert-CleanDistributionArchive $zipPath
}
catch {
    # Never leave a rejected archive looking like a releasable artifact.
    if (Test-Path -LiteralPath $zipPath) {
        Remove-Item -LiteralPath $zipPath -Force
    }
    throw
}

Write-Host ""
Write-Host "Build complete:"
Write-Host (Join-Path $appDir "ResourceWorkbench.exe")
Write-Host "Clean distribution archive:"
Write-Host $zipPath
Write-Host ""
Write-Host "A directly launched public EXE uses its own persistent profile:"
Write-Host "%LOCALAPPDATA%\ResourceWorkbench\Profiles\Public\Stable\workbench_data"
Write-Host "The repository's formal launcher keeps the existing personal profile separately."

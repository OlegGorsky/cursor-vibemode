param(
    [string]$Model = "gpt-5.4",
    [string]$Models = "auto",
    [string]$BaseUrl = "https://api.vibemod.pro/v1",
    [switch]$SkipApiCheck,
    [switch]$DeepApiCheck,
    [switch]$ReplaceKey,
    [switch]$KeyFromClipboard,
    [switch]$NoWsl,
    [switch]$NoWindows,
    [switch]$SkipAppPatch,
    [switch]$Force,
    [string]$WslDistro,
    [string]$Repo = "OlegGorsky/cursor-vibemode",
    [string]$Ref = "main"
)

$ErrorActionPreference = "Stop"

function Log([string]$Message) { Write-Host $Message }
function Warn([string]$Message) { Write-Warning $Message }
function Die([string]$Message) { Write-Error $Message; exit 1 }

function Test-EnvFlag([string]$Value) {
    return ($Value -match '^(1|true|yes|y|on|да|д)$')
}

function Enable-Tls12 {
    try {
        [Net.ServicePointManager]::SecurityProtocol =
            [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    } catch {}
}

function Read-ClipboardKey {
    try {
        $value = (Get-Clipboard -ErrorAction Stop) -join [Environment]::NewLine
    } catch {
        Die "Не удалось прочитать ключ из буфера обмена."
    }
    if (-not $value -or -not $value.Trim()) { Die "В буфере обмена нет ключа." }
    return $value.Trim()
}

function Read-MaskedInput([string]$Prompt) {
    if ([Console]::IsInputRedirected) {
        $secure = Read-Host -Prompt $Prompt -AsSecureString
        $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
    }

    Write-Host -NoNewline "${Prompt}: "
    $builder = New-Object System.Text.StringBuilder
    while ($true) {
        $key = [Console]::ReadKey($true)
        if ($key.Key -eq [ConsoleKey]::Enter) { Write-Host ""; break }
        if ($key.Key -eq [ConsoleKey]::Backspace) {
            if ($builder.Length -gt 0) {
                [void]$builder.Remove($builder.Length - 1, 1)
                Write-Host -NoNewline "`b `b"
            }
            continue
        }
        if ([char]::IsControl($key.KeyChar)) { continue }
        [void]$builder.Append($key.KeyChar)
        Write-Host -NoNewline "*"
    }
    return $builder.ToString()
}

function Read-ApiKey {
    $replaceFromEnv = Test-EnvFlag $env:CURSOR_VIBEMODE_REPLACE_KEY
    if ($env:CURSOR_VIBEMODE_KEY -and $env:CURSOR_VIBEMODE_KEY.Trim() -and -not $ReplaceKey -and -not $replaceFromEnv) {
        return $env:CURSOR_VIBEMODE_KEY.Trim()
    }
    if ($KeyFromClipboard -or (Test-EnvFlag $env:CURSOR_VIBEMODE_KEY_FROM_CLIPBOARD)) {
        Log "Читаю Vibemode key из буфера обмена"
        return Read-ClipboardKey
    }
    $plain = Read-MaskedInput "Вставь Vibemode API key"
    if (-not $plain -or -not $plain.Trim()) { Die "API-ключ не найден." }
    return $plain.Trim()
}

function Find-Python {
    foreach ($candidate in @("python", "python3")) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($cmd) { return [pscustomobject]@{ Exe = $cmd.Source; Args = @() } }
    }
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) { return [pscustomobject]@{ Exe = $py.Source; Args = @("-3") } }
    Die "Python не найден. Установи Python 3 и повтори запуск."
}

function Download-Repo {
    param([string]$Target)
    Enable-Tls12
    $zip = Join-Path $Target "repo.zip"
    $stamp = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $headers = @{ "Cache-Control" = "no-cache"; "Pragma" = "no-cache" }
    $resolvedRef = $Ref
    try {
        $commit = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/commits/$Ref?v=$stamp" -UseBasicParsing -Headers $headers
        if ($commit.sha) { $resolvedRef = $commit.sha }
    } catch {}
    $url = "https://github.com/$Repo/archive/$resolvedRef.zip?v=$stamp"
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing -Headers $headers
    Expand-Archive -LiteralPath $zip -DestinationPath $Target -Force
    $dir = Get-ChildItem -LiteralPath $Target -Directory |
        Where-Object { $_.Name -like "cursor-vibemode-*" } |
        Select-Object -First 1
    if (-not $dir) { Die "Не удалось распаковать cursor-vibemode." }
    return $dir.FullName
}

function Invoke-CursorSetup {
    param([string]$Root, [string]$DbPath, [string]$ApiKey)
    $python = Find-Python
    $env:PYTHONPATH = Join-Path $Root "src"
    $env:CURSOR_VIBEMODE_KEY = $ApiKey
    $args = @()
    if ($python.Args) { $args += $python.Args }
    $args += @("-m", "cursor_vibemode", "setup", "--non-interactive", "--db", $DbPath)
    $args += @("--model", $Model, "--models", $Models, "--base-url", $BaseUrl)
    if ($SkipApiCheck -or (Test-EnvFlag $env:CURSOR_VIBEMODE_SKIP_API_CHECK)) {
        $args += "--skip-api-check"
    }
    if ($SkipAppPatch -or (Test-EnvFlag $env:CURSOR_VIBEMODE_SKIP_APP_PATCH)) {
        $args += "--skip-app-patch"
    }
    if ($DeepApiCheck -or (Test-EnvFlag $env:CURSOR_VIBEMODE_DEEP_API_CHECK)) {
        $args += "--deep-api-check"
    }
    if ($Force) { $args += "--force" }
    & $python.Exe @args
    if ($LASTEXITCODE -ne 0) { Die "Настройка Cursor не удалась." }
}

function Get-WindowsCursorDb {
    if (-not $env:APPDATA) { return $null }
    return Join-Path $env:APPDATA "Cursor\User\globalStorage\state.vscdb"
}

function Get-WslCommand {
    return Get-Command wsl.exe -ErrorAction SilentlyContinue
}

function Get-WslBaseArgs {
    if ($WslDistro) { return @("--distribution", $WslDistro) }
    return @()
}

function Test-WslReady {
    $wsl = Get-WslCommand
    if (-not $wsl) { return $false }
    $args = @(Get-WslBaseArgs) + @("--", "sh", "-lc", "printf ready")
    $output = & $wsl.Source @args 2>$null
    return ($LASTEXITCODE -eq 0 -and (($output -join "") -eq "ready"))
}

function Convert-ToWslPath([string]$Path) {
    $wsl = Get-WslCommand
    if (-not $wsl -or -not $Path) { return "" }
    $args = @(Get-WslBaseArgs) + @("--", "wslpath", "-a", $Path)
    $output = & $wsl.Source @args 2>$null
    if ($LASTEXITCODE -eq 0) { return (($output -join "").Trim()) }
    return ""
}

function To-Base64([string]$Value) {
    return [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Value))
}

function Invoke-WslSetup {
    param([string]$ApiKey, [string]$WindowsDb)
    if ($NoWsl) { Log "WSL настройка пропущена"; return $false }
    $wsl = Get-WslCommand
    if (-not $wsl) { Log "WSL не найден, пропускаю"; return $false }
    if (-not (Test-WslReady)) { Warn "WSL найден, но default distro не готов"; return $false }

    $dbWsl = Convert-ToWslPath $WindowsDb
    $script = @'
set -euo pipefail
decode() { printf '%s' "$1" | base64 -d; }
need() { command -v "$1" >/dev/null 2>&1 || { echo "missing $1"; exit 42; }; }
need curl
need tar
need python3
need base64

api_key="$(decode '__KEY_B64__')"
repo="$(decode '__REPO_B64__')"
ref="$(decode '__REF_B64__')"
model="$(decode '__MODEL_B64__')"
models="$(decode '__MODELS_B64__')"
base_url="$(decode '__BASE_URL_B64__')"
db_path="$(decode '__DB_B64__')"
tmp="$(mktemp -d)"
cache_buster="$(date +%s)"
trap 'rm -rf "$tmp"' EXIT

curl -fsSL \
  -H 'Cache-Control: no-cache' \
  -H 'Pragma: no-cache' \
  "https://github.com/${repo}/archive/refs/heads/${ref}.tar.gz?v=${cache_buster}" |
  tar -xz -C "$tmp" --strip-components=1

export CURSOR_VIBEMODE_KEY="$api_key"
args=(setup --non-interactive --model "$model" --models "$models" --base-url "$base_url")
args+=(--skip-app-patch)
if [[ -n "$db_path" && -f "$db_path" ]]; then
  args+=(--db "$db_path")
fi
if [[ "__SKIP_API_CHECK__" == "1" ]]; then
  args+=(--skip-api-check)
fi
if [[ "__DEEP_API_CHECK__" == "1" ]]; then
  args+=(--deep-api-check)
fi
if [[ "__FORCE__" == "1" ]]; then
  args+=(--force)
fi
"$tmp/cursor-vibemode" "${args[@]}"
'@
    $script = $script.Replace("__KEY_B64__", (To-Base64 $ApiKey))
    $script = $script.Replace("__REPO_B64__", (To-Base64 $Repo))
    $script = $script.Replace("__REF_B64__", (To-Base64 $Ref))
    $script = $script.Replace("__MODEL_B64__", (To-Base64 $Model))
    $script = $script.Replace("__MODELS_B64__", (To-Base64 $Models))
    $script = $script.Replace("__BASE_URL_B64__", (To-Base64 $BaseUrl))
    $skipFlag = if ($SkipApiCheck -or (Test-EnvFlag $env:CURSOR_VIBEMODE_SKIP_API_CHECK)) { "1" } else { "0" }
    $deepFlag = if ($DeepApiCheck -or (Test-EnvFlag $env:CURSOR_VIBEMODE_DEEP_API_CHECK)) { "1" } else { "0" }
    $forceFlag = if ($Force) { "1" } else { "0" }
    $script = $script.Replace("__DB_B64__", (To-Base64 $dbWsl))
    $script = $script.Replace("__SKIP_API_CHECK__", $skipFlag)
    $script = $script.Replace("__DEEP_API_CHECK__", $deepFlag)
    $script = $script.Replace("__FORCE__", $forceFlag)

    $args = @(Get-WslBaseArgs) + @("--", "bash", "-s")
    $output = $script | & $wsl.Source @args 2>&1
    if ($LASTEXITCODE -eq 0) { Log "WSL настройка завершена"; return $true }
    if ($LASTEXITCODE -eq 42) { Warn "WSL есть, но нет curl/tar/python3/base64"; return $false }
    Warn ("WSL настройка не удалась: " + ($output -join " "))
    return $false
}

$tmp = Join-Path ([IO.Path]::GetTempPath()) ("cursor-vibemode-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
try {
    $root = Download-Repo $tmp
    $apiKey = Read-ApiKey
    $windowsDb = Get-WindowsCursorDb
    $didWork = $false

    if (-not $NoWindows) {
        if ($windowsDb -and (Test-Path -LiteralPath $windowsDb)) {
            Log "Настраиваю Cursor в Windows"
            Invoke-CursorSetup $root $windowsDb $apiKey
            $didWork = $true
        } else {
            Warn "Windows Cursor DB не найден. Открой Cursor один раз и повтори запуск."
        }
    }

    $didWork = $didWork -or (Invoke-WslSetup $apiKey $windowsDb)
    if (-not $didWork) { Die "Ни одна среда не была настроена." }
} finally {
    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
}

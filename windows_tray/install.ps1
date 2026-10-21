# Windows（WSL なし）用セットアップ — Claude Code / Codex を Windows で直接使っている人向け。
#   install.cmd をダブルクリック、または
#   powershell -ExecutionPolicy Bypass -File windows_tray\install.ps1              インストールして起動（ログオン時に自動起動）
#   powershell -ExecutionPolicy Bypass -File windows_tray\install.ps1 -Uninstall   停止して自動起動を解除
# ai_usage_tray.ps1 を %LOCALAPPDATA%\ai-usage-tools にコピーし、スタートアップに非表示で起動する
# ランチャー (.vbs) を置く。ai_usage_tray.ps1 を更新したら再実行すること。
# このファイルは日本語を含むので UTF-8 (BOM 付き) で保存すること（PowerShell 5.1 対策）。
param([switch]$Uninstall)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$script = Join-Path $here "usage_json.py"
$appDir = Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) "ai-usage-tools"
$trayPs1 = Join-Path $appDir "ai_usage_tray.ps1"
$launcher = Join-Path ([Environment]::GetFolderPath("Startup")) "AI Usage Tray.vbs"

function Stop-Tray {
    Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
        Where-Object { $_.CommandLine -like '*ai_usage_tray.ps1*' } |
        ForEach-Object { Invoke-CimMethod -InputObject $_ -MethodName Terminate | Out-Null }
}

if ($Uninstall) {
    Stop-Tray
    Remove-Item $launcher -ErrorAction SilentlyContinue
    Remove-Item $appDir -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "==> 停止して自動起動を解除しました。"
    exit 0
}

# Python 3.8 以上を探す（Microsoft Store の python.exe スタブは実行に失敗するので自然に除外される）
function Find-Python {
    foreach ($cand in @(@("py", "-3"), @("python"), @("python3"))) {
        if (-not (Get-Command $cand[0] -ErrorAction SilentlyContinue)) { continue }
        $extra = @($cand | Select-Object -Skip 1)
        try {
            $out = & $cand[0] @extra -c "import sys; print(sys.executable); print(sys.version_info >= (3, 8))" 2>$null
        } catch { continue }
        if ($LASTEXITCODE -eq 0 -and $out.Count -ge 2 -and $out[1] -eq "True") { return $out[0] }
    }
    return $null
}

Write-Host "==> 事前チェック"
$python = Find-Python
if (-not $python) {
    Write-Host "Python 3.8 以上が見つかりません。次のコマンドで入れてから、もう一度実行してください:" -ForegroundColor Red
    Write-Host "    winget install Python.Python.3.12"
    exit 1
}
Write-Host "    Python: $python"
if (-not (Test-Path (Join-Path $env:USERPROFILE ".claude\.credentials.json"))) {
    Write-Host "    - Claude Code: 未検出（claude を起動して /login すると自動で表示されます）"
}
$codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE ".codex" }
if (-not (Test-Path (Join-Path $codexHome "auth.json"))) {
    Write-Host "    - Codex: 未検出（npm install -g @openai/codex → codex login で使い始めると自動で表示されます）"
}

& $python $script > $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "usage_json.py の実行に失敗しました（終了コード $LASTEXITCODE）。" -ForegroundColor Red
    exit 1
}

Stop-Tray
New-Item -ItemType Directory -Force -Path $appDir | Out-Null
$status = Join-Path $appDir "tray_status.json"
Remove-Item $status -ErrorAction SilentlyContinue  # the tray rewrites it; a fresh last_success proves it works
Copy-Item (Join-Path $here "ai_usage_tray.ps1") $trayPs1 -Force
# UTF-16 で書くとユーザー名などに日本語を含むパスでも wscript が正しく読める
$cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""$trayPs1"" -Mode Native -Python ""$python"" -Script ""$script"""
$vbsCmd = $cmd.Replace('"', '""')  # VBScript escapes quotes by doubling (kept out of the "..." string on purpose)
Set-Content -Path $launcher -Encoding Unicode -Value ('CreateObject("WScript.Shell").Run "' + $vbsCmd + '", 0, False')
Write-Host "==> インストール: $trayPs1"
Write-Host "==> 自動起動を登録: $launcher"

Start-Process wscript.exe -ArgumentList """$launcher"""
Write-Host "==> 起動しました。トレイの最初の取得を待っています..."

# The tray writes tray_status.json after every fetch (see ai_usage_tray.ps1)
for ($i = 0; $i -lt 45; $i++) {
    Start-Sleep -Seconds 1
    if (-not (Test-Path $status)) { continue }
    try { $s = Get-Content $status -Raw -Encoding UTF8 | ConvertFrom-Json } catch { continue }
    if ($s.last_success) {
        Write-Host "==> 動作確認OK: トレイが使用量の取得に成功しました。" -ForegroundColor Green
        Write-Host "    ログイン中のサービスごとにタスクトレイにリングが表示されます。見当たらなければ、トレイの「^」の中を"
        Write-Host "    見るか、設定 → 個人用設定 → タスク バー →「その他のシステム トレイ アイコン」で Windows PowerShell をオンに。"
        exit 0
    }
    if ($s.last_error) {
        Write-Host "!! トレイが取得に失敗しました: $($s.last_error)" -ForegroundColor Red
        Write-Host "   状態ファイル: $status"
        exit 1
    }
}
Write-Host "!! 45 秒待ってもトレイから応答がありません。状態ファイル: $status" -ForegroundColor Red
exit 1

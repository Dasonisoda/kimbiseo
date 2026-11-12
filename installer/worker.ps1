# 김비서 설치 일꾼 — 설치 창(install.ps1)이 창 없이 띄운다. 직접 누르는 파일이 아님.
#   1) 공식 파이썬(embeddable, 판 고정 + sha256) 을 받아 <설치 폴더>\runtime\python-app 에 풀고 pip 를 넣음
#   2) 그 파이썬으로 setup_core.py 를 돌림(나머지 전부). 상태는 -Status 파일(JSON)에, 기록은 <자료>\logs\install.log 에.
param(
  [Parameter(Mandatory = $true)][string]$Prefix,
  [Parameter(Mandatory = $true)][string]$DataDir,
  [Parameter(Mandatory = $true)][string]$Status,
  [string]$Source = "",
  [switch]$LocalBrain,
  [ValidateSet("", "E4B", "E2B")][string]$Gemma = "",
  [string]$DesktopDir = "",
  [string]$StartMenuDir = "",
  [string]$RegKey = "KimBiseo",
  [string]$DisplayName = "김비서",
  [string]$PacksCatalog = "<none>",
  [switch]$NoShortcuts,
  [switch]$NoRegister
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
if (-not $Source) { $Source = Split-Path -Parent $PSScriptRoot }
$utf8 = New-Object System.Text.UTF8Encoding($false)
$logDir = Join-Path $DataDir "logs"
New-Item -ItemType Directory -Force -Path $logDir, (Split-Path -Parent $Status), (Join-Path $Prefix "install\downloads") | Out-Null
$log = Join-Path $logDir "install.log"
function Log([string]$m) { [IO.File]::AppendAllText($log, (Get-Date -Format "yyyy-MM-dd HH:mm:ss ") + $m + "`r`n", $utf8) }

$steps = @(@("python", "파이썬 준비"), @("plan", "이 PC 사양 확인"), @("files", "프로그램 파일"), @("packages", "파이썬 부품"),
           @("brain", "두뇌 프로그램"), @("models", "모델(두뇌·귀·목소리)"), @("pet", "펫"), @("finish", "바탕화면 아이콘·마무리"))
function Write-Status([string]$state, [string]$text, [double]$prog, $err) {
  $list = @()
  foreach ($s in $steps) {
    $st = if ($s[0] -eq "python") { $state } else { "기다림" }
    $list += [ordered]@{ id = $s[0]; "이름" = $s[1]; "상태" = $st; "글" = "" }
  }
  $o = [ordered]@{ "단계" = $list; "지금" = "python"; "글" = $text; "진행" = $prog; "전체" = [math]::Round($prog * 0.02, 1); "끝" = [bool]$err;
                   "성공" = $false; "오류" = $err; "시각" = (Get-Date -Format "HH:mm:ss") }
  $json = $o | ConvertTo-Json -Depth 6
  [IO.File]::WriteAllText($Status + ".tmp", $json, $utf8)
  Move-Item -Force ($Status + ".tmp") $Status
}

$rt = [IO.File]::ReadAllText((Join-Path $PSScriptRoot "runtimes.json"), $utf8) | ConvertFrom-Json
$pyDir = Join-Path $Prefix "runtime\python-app"
$py = Join-Path $pyDir "python.exe"
$mark = Join-Path $pyDir "kimbiseo_python.txt"
$want = $rt.python.version + "+pip" + $rt.pip.version

function Get-Checked([string]$url, [string]$dest, [string]$sha, [long]$size, [string]$label) {
  if ((Test-Path $dest) -and ((Get-FileHash -Algorithm SHA256 $dest).Hash.ToLower() -eq $sha)) { return }
  for ($i = 1; $i -le 5; $i++) {
    try {
      Write-Status "하는 중" "$label 받는 중 ($i 번째)" 10 $null
      Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile ($dest + ".part") -UserAgent "KimBiseo-installer/1"
      $h = (Get-FileHash -Algorithm SHA256 ($dest + ".part")).Hash.ToLower()
      if ($h -ne $sha) { Remove-Item -Force ($dest + ".part"); throw "sha256 다름 $h" }
      if ($size -gt 0 -and (Get-Item ($dest + ".part")).Length -ne $size) { throw "크기 다름" }
      Move-Item -Force ($dest + ".part") $dest
      Log "  받음 $label sha256 맞음"
      return
    } catch {
      Log "  $label 받기 $i 번째 실패: $($_.Exception.Message)"
      Start-Sleep -Seconds ([math]::Min(20, 2 * $i))
    }
  }
  throw "NET:$label"
}

try {
  Log "==== 설치 시작(일꾼 PID $PID) 설치 폴더 $Prefix · 자료 $DataDir · 소스 $Source"
  if ((Test-Path $py) -and (Test-Path $mark) -and ([IO.File]::ReadAllText($mark).Trim() -eq $want)) {
    Log "파이썬: 이미 있음($want)"
  } else {
    Write-Status "하는 중" "공식 파이썬 $($rt.python.version) 받는 중" 5 $null
    $zip = Join-Path $Prefix ("install\downloads\" + [IO.Path]::GetFileName($rt.python.url))
    Get-Checked $rt.python.url $zip $rt.python.sha256 $rt.python.size "파이썬 $($rt.python.version)"
    $md5 = (Get-FileHash -Algorithm MD5 $zip).Hash.ToLower()
    if ($md5 -ne $rt.python.md5_python_org) { throw "HASH:파이썬 md5 가 python.org 값과 다름" }
    if (Test-Path $pyDir) { Remove-Item -Recurse -Force $pyDir }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::ExtractToDirectory($zip, $pyDir)
    $pth = "python311.zip`r`n.`r`nLib\site-packages`r`n..\..\src`r`n# 김비서: 위 줄 = 설치 폴더의 src(본체 코드). 환경변수·레지스트리는 보지 않음`r`nimport site`r`n"
    [IO.File]::WriteAllText((Join-Path $pyDir $rt.python.pth), $pth, $utf8)
    $whl = Join-Path $Prefix ("install\downloads\" + [IO.Path]::GetFileName($rt.pip.url))
    Get-Checked $rt.pip.url $whl $rt.pip.sha256 $rt.pip.size "pip $($rt.pip.version)"
    [IO.Compression.ZipFile]::ExtractToDirectory($whl, (Join-Path $pyDir "Lib\site-packages"))
    [IO.File]::WriteAllText($mark, $want, $utf8)
    Log "파이썬: 풀고 pip 넣음($want)"
  }
  Write-Status "됨" "파이썬 준비 끝" 100 $null
} catch {
  $m = $_.Exception.Message
  Log "!!!! 파이썬 준비 실패: $m"
  $why = if ($m -like "NET:*") { "공식 파이썬을 받지 못했어요. 인터넷 연결을 확인하고 '다시 하기'를 눌러 주세요." }
         elseif ($m -like "HASH:*") { "받은 파이썬이 원본과 달라요. '다시 하기'를 누르면 새로 받아요." }
         else { "파이썬을 준비하지 못했어요. '다시 하기'를 눌러 주세요." }
  Write-Status "실패" $why 0 ([ordered]@{ "단계" = "파이썬 준비"; "이유" = $why; "자세히" = $m; "기록" = $log })
  exit 1
}

$args2 = @("-B", "-X", "utf8", (Join-Path $Source "installer\setup_core.py"), "install", "--prefix", $Prefix, "--data", $DataDir,
           "--status", $Status, "--source", $Source, "--reg-key", $RegKey, "--display-name", $DisplayName)
if ($LocalBrain) { $args2 += "--local-brain" }
if ($Gemma) { $args2 += @("--gemma", $Gemma) }
if ($DesktopDir) { $args2 += @("--desktop-dir", $DesktopDir) }
if ($StartMenuDir) { $args2 += @("--startmenu-dir", $StartMenuDir) }
if ($PacksCatalog -ne "<none>") { $args2 += @("--packs-catalog", $PacksCatalog) }
if ($NoShortcuts) { $args2 += "--no-shortcuts" }
if ($NoRegister) { $args2 += "--no-register" }
# 인자를 안전하게 따옴표로 묶어 넘김(한글·빈칸 경로)
$q = ($args2 | ForEach-Object { '"' + ($_ -replace '"', '\"') + '"' }) -join " "
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $py
$psi.Arguments = $q
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.StandardOutputEncoding = $utf8
$psi.StandardErrorEncoding = $utf8
$psi.EnvironmentVariables["PYTHONUTF8"] = "1"
$psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8"
$p = [Diagnostics.Process]::Start($psi)
Log "설치 본체 PID $($p.Id)"
$errTask = $p.StandardError.ReadToEndAsync()
while (-not $p.StandardOutput.EndOfStream) { $null = $p.StandardOutput.ReadLine() }
$p.WaitForExit()
$errText = $errTask.Result
if ($errText) { Log ("설치 본체 오류 출력: " + $errText.Substring([math]::Max(0, $errText.Length - 2000))) }
Log "설치 본체 끝(코드 $($p.ExitCode))"
if ($p.ExitCode -ne 0) {   # 설치 본체가 상태를 못 남기고 끝났으면(파이썬 오류 등) 여기서 실패로 적음
  $done = $false
  try { $done = ([IO.File]::ReadAllText($Status, $utf8) | ConvertFrom-Json)."끝" } catch { }
  if (-not $done) {
    $why = "설치 도중 프로그램이 멈췄어요. '다시 하기'를 눌러 주세요. 계속되면 기록 파일을 보내 주세요."
    $tail = if ($errText) { $errText.Substring([math]::Max(0, $errText.Length - 600)) } else { "코드 $($p.ExitCode)" }
    Write-Status "됨" $why 100 ([ordered]@{ "단계" = "설치"; "이유" = $why; "자세히" = $tail; "기록" = $log })
  }
}
exit $p.ExitCode

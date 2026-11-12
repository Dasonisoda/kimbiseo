# 김비서 지우기 — 시작 메뉴 '김비서 제거' 또는 윈도우 '앱 및 기능'에서 부른다.
#   -Prefix <설치 폴더>(필수) · -Quiet(묻지 않음, 자료는 남김) · -RemoveData(대화 기억·설정도 지움, -Quiet 와 같이 쓸 때)
# 지우는 것: 설치 폴더 전체(프로그램·파이썬·모델·두뇌 프로그램·펫 틀), 바탕화면·시작 메뉴 아이콘, '앱 및 기능' 항목,
#           펫 옷 파일 연결(.hipcpet — 이 펫이 만든 것일 때만). 자료 폴더(대화 기억·설정·열쇠·펫 옷)는 물어보고.
# 끄는 것: 실행기 기록(<자료>\run\launcher.json)의 PID 와, 실행 파일이 이 설치 폴더 안에 있는 프로세스만(이름으로 끄지 않음).
param([Parameter(Mandatory = $true)][string]$Prefix, [switch]$Quiet, [switch]$RemoveData)
$ErrorActionPreference = "Continue"
Add-Type -AssemblyName System.Windows.Forms
$utf8 = New-Object System.Text.UTF8Encoding($false)
$Prefix = [IO.Path]::GetFullPath($Prefix.TrimEnd('\'))

# 설치 폴더 안에서 돌고 있으면 그 폴더를 지울 수 없음 → 임시 폴더로 나를 복사해 다시 실행
$tmp = [IO.Path]::GetFullPath($env:TEMP)
if (-not $PSCommandPath.StartsWith($tmp, [StringComparison]::OrdinalIgnoreCase)) {
  $copy = Join-Path $tmp ("kimbiseo_uninstall_" + [guid]::NewGuid().ToString("N") + ".ps1")
  Copy-Item -Force $PSCommandPath $copy
  $a = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", "`"$copy`"", "-Prefix", "`"$Prefix`"")
  if ($Quiet) { $a += "-Quiet" }
  if ($RemoveData) { $a += "-RemoveData" }
  Start-Process powershell.exe -ArgumentList ($a -join " ") -WindowStyle Hidden -WorkingDirectory $tmp
  exit 0
}
Set-Location $tmp

$statePath = Join-Path $Prefix "install\state.json"
$state = $null
try { $state = [IO.File]::ReadAllText($statePath, $utf8) | ConvertFrom-Json } catch { }
if (-not $state -and -not (Test-Path (Join-Path $Prefix "src\app\launcher.py"))) {
  if (-not $Quiet) { [Windows.Forms.MessageBox]::Show("김비서 설치 폴더가 아니에요: $Prefix", "김비서 제거") | Out-Null }
  exit 1
}
$name = if ($state -and $state.display_name) { $state.display_name } else { "김비서" }
$data = if ($state -and $state.data) { $state.data } else { Join-Path $env:APPDATA "KimBiseo" }

$delData = [bool]$RemoveData
if (-not $Quiet) {
  $r = [Windows.Forms.MessageBox]::Show("$name 을(를) 이 PC 에서 지울까요?`r`n(프로그램·모델 약 수 GB 가 지워져요)", "$name 제거", "YesNo", "Question")
  if ($r -ne "Yes") { exit 0 }
  $r2 = [Windows.Forms.MessageBox]::Show("대화 기억·설정·펫 옷도 지울까요?`r`n'아니요'를 누르면 남겨 둬요(다시 설치하면 이어서 써요).`r`n$data", "$name 제거", "YesNo", "Question")
  $delData = ($r2 -eq "Yes")
}

$log = Join-Path $tmp "kimbiseo_uninstall.log"
function Log([string]$m) { [IO.File]::AppendAllText($log, (Get-Date -Format "yyyy-MM-dd HH:mm:ss ") + $m + "`r`n", $utf8) }
Log "==== 제거 시작 $Prefix (자료도 지움: $delData)"

# 1) 끄기 — 실행기 기록의 PID(실행 파일 확인) + 실행 파일이 설치 폴더 안인 프로세스
$pids = @()
$run = Join-Path $data "run\launcher.json"
try {
  $r = [IO.File]::ReadAllText($run, $utf8) | ConvertFrom-Json
  $recs = @($r.launcher) + @($r.services.PSObject.Properties | ForEach-Object { $_.Value })
  foreach ($x in $recs) {
    if (-not $x.pid) { continue }
    $p = Get-CimInstance Win32_Process -Filter "ProcessId=$([int]$x.pid)" -ErrorAction SilentlyContinue
    if ($p -and $p.ExecutablePath -and ($p.ExecutablePath -eq $x.exe)) { $pids += [int]$x.pid }
  }
} catch { }
$inside = Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($Prefix + "\", [StringComparison]::OrdinalIgnoreCase) }
$pids += @($inside | ForEach-Object { [int]$_.ProcessId })
foreach ($id in ($pids | Sort-Object -Unique)) {
  if ($id -eq $PID) { continue }
  Log "끔 PID $id"
  & taskkill.exe /PID $id /T /F 2>$null | Out-Null
}
Start-Sleep -Seconds 2

# 2) 아이콘·앱 목록·파일 연결
$links = @()
if ($state -and $state.shortcuts) { $links = @($state.shortcuts) }
foreach ($l in $links) { if ($l -and $l.EndsWith(".lnk") -and (Test-Path -LiteralPath $l)) { Remove-Item -LiteralPath $l -Force; Log "아이콘 지움 $l" } }
if ($state -and $state.menu_dir -and (Test-Path -LiteralPath $state.menu_dir)) {
  if (-not (Get-ChildItem -LiteralPath $state.menu_dir -Force)) { Remove-Item -LiteralPath $state.menu_dir -Force; Log "시작 메뉴 폴더 지움" }
}
$regKey = if ($state -and $state.reg_key) { $state.reg_key } else { "" }
if ($regKey) {
  $k = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$regKey"
  if (Test-Path $k) {
    $loc = (Get-ItemProperty $k -ErrorAction SilentlyContinue).InstallLocation
    if ($loc -and ([IO.Path]::GetFullPath($loc) -eq $Prefix)) { Remove-Item -Recurse -Force $k; Log "앱 목록에서 지움 $regKey" }
  }
}
$prog = "HKCU:\Software\Classes\KimBiseo.PetPack"
$cmdKey = "$prog\shell\open\command"
if (Test-Path $cmdKey) {
  $cmd = (Get-ItemProperty $cmdKey -ErrorAction SilentlyContinue)."(default)"
  if ($cmd -and $cmd.IndexOf($Prefix, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
    Remove-Item -Recurse -Force $prog
    $ext = "HKCU:\Software\Classes\.hipcpet"
    if ((Test-Path $ext) -and ((Get-ItemProperty $ext)."(default)" -eq "KimBiseo.PetPack")) { Remove-Item -Recurse -Force $ext }
    Log "펫 옷 파일 연결 지움"
  }
}

# 3) 설치 폴더(그리고 원하면 자료 폴더)
function Remove-Dir([string]$d) {
  for ($i = 0; $i -lt 5 -and (Test-Path -LiteralPath $d); $i++) {
    Remove-Item -LiteralPath $d -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $d) { Start-Sleep -Seconds 2 }
  }
  return -not (Test-Path -LiteralPath $d)
}
$okP = Remove-Dir $Prefix
Log "설치 폴더 지움: $okP"
$okD = $true
if ($delData) { $okD = Remove-Dir $data; Log "자료 폴더 지움: $okD" }

if (-not $Quiet) {
  $msg = if ($okP -and $okD) { "$name 을(를) 지웠어요." + $(if (-not $delData) { "`r`n대화 기억·설정은 남겨 뒀어요: $data" } else { "" }) }
         else { "일부 파일을 지우지 못했어요(켜져 있는 프로그램이 쓰고 있을 수 있어요). PC 를 다시 켠 뒤 이 폴더를 지워 주세요:`r`n$Prefix" }
  [Windows.Forms.MessageBox]::Show($msg, "$name 제거") | Out-Null
}
Log "==== 제거 끝"
Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
exit $(if ($okP -and $okD) { 0 } else { 1 })

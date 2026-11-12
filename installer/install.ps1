# 김비서 설치 창 — '설치.bat' 이 창 없이(명령창 숨김) 띄운다. 사용자는 '설치' 단추 하나만 누르면 됨.
#   실제 일은 worker.ps1(파이썬 준비) → setup_core.py(나머지)가 창 없이 하고, 이 창은 상태 파일을 0.5초마다 읽어 보여 준다.
#   시험·고급: -Prefix 설치폴더 -DataDir 자료폴더 -DesktopDir 바탕화면 -StartMenuDir 시작메뉴 -RegKey 이름 -DisplayName 이름
#             -PacksCatalog 옷목록주소 -Auto(창이 뜨면 바로 설치) -ShotDir 폴더(창 그림을 단계마다 저장)
#             -Gemma E2B(이 PC 두뇌를 받을 때 작은 판 — 기본 E4B)
param(
  [string]$Prefix = "",
  [string]$DataDir = "",
  [string]$DesktopDir = "",
  [string]$StartMenuDir = "",
  [string]$RegKey = "KimBiseo",
  [string]$DisplayName = "김비서",
  [string]$PacksCatalog = "<none>",
  [switch]$Auto,
  [ValidateSet("", "E4B", "E2B")][string]$Gemma = "",
  [string]$ShotDir = ""
)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()
$utf8 = New-Object System.Text.UTF8Encoding($false)
$Source = Split-Path -Parent $PSScriptRoot
if (-not $Prefix) { $Prefix = Join-Path $env:LOCALAPPDATA "KimBiseo" }
if (-not $DataDir) { $DataDir = Join-Path $env:APPDATA "KimBiseo" }
$script:status = Join-Path $Prefix "install\status.json"
$script:worker = $null
$script:result = $null

# ---------------------------------------------------------------- 사양(창에 보여 주기만 — 실제 구성은 setup_core/plan.py 가 다시 정함)
function Get-Spec {
  $g = $null; $mib = 0
  $fake = $env:KIMBISEO_FAKE_GPU
  if ($fake) {
    if ($fake.Trim().ToLower() -ne "none") { $i = $fake.LastIndexOf(":"); $g = $fake.Substring(0, $i); $mib = [int]$fake.Substring($i + 1) }
  } else {
    $smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if ($smi) {
      try {
        $line = (& $smi.Source --query-gpu=name,memory.total --format=csv,noheader,nounits | Select-Object -First 1)
        $p = $line.Split(","); $g = $p[0].Trim(); $mib = [int][double]$p[1].Trim()
      } catch { }
    }
  }
  $ram = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
  if ($env:KIMBISEO_FAKE_RAM_GB) { $ram = [double]$env:KIMBISEO_FAKE_RAM_GB }
  $root = [IO.Path]::GetPathRoot($Prefix)
  $free = [math]::Round((New-Object IO.DriveInfo($root)).AvailableFreeSpace / 1GB, 1)
  if ($env:KIMBISEO_FAKE_DISK_GB) { $free = [double]$env:KIMBISEO_FAKE_DISK_GB }
  $sub = "클로드 코드·Codex 로그인이 있으면 그것을 두뇌로 쓰고(Gemma 안 받음), 없으면 Gemma 를 받아요."
  if (-not $g) { $kind = "그래픽카드 없음"; $hint = "목소리는 윈도우 음성, 받아쓰기는 작은 귀(CPU). 두뇌는 구독 클로드·GPT 또는 '내 로컬 AI 주소'를 권해요."; $need = 9 }
  elseif ($mib -ge 9216) { $kind = "그래픽 메모리 넉넉함"; $hint = "받아쓰기·김비서 목소리를 그래픽카드로 해요. $sub"; $need = 22 }
  elseif ($mib -ge 6144) { $kind = "그래픽 메모리 8GB 이하"; $hint = "받아쓰기·김비서 목소리를 그래픽카드로 해요. $sub"; $need = 22 }
  else { $kind = "그래픽 메모리 6GB 미만"; $hint = "받아쓰기는 그래픽카드, 목소리는 윈도우 음성. 두뇌는 구독 클로드·GPT 또는 바깥 AI 를 권해요."; $need = 16 }
  return @{ gpu = $g; mib = $mib; ram = $ram; free = $free; kind = $kind; hint = $hint; need = $need }
}
$spec = Get-Spec

# ---------------------------------------------------------------- 창(운영판과 같은 색: 검은 바탕 + 분홍 하나)
$C_BG = [Drawing.Color]::FromArgb(11, 12, 15); $C_CARD = [Drawing.Color]::FromArgb(21, 23, 28); $C_LINE = [Drawing.Color]::FromArgb(38, 41, 50)
$C_TEXT = [Drawing.Color]::FromArgb(236, 236, 241); $C_MUTED = [Drawing.Color]::FromArgb(139, 143, 154)
$C_ACC = [Drawing.Color]::FromArgb(255, 0, 90); $C_ACCINK = [Drawing.Color]::FromArgb(255, 92, 138)
$C_OK = [Drawing.Color]::FromArgb(86, 211, 100); $C_BAD = [Drawing.Color]::FromArgb(255, 138, 138)
$font = New-Object Drawing.Font("Malgun Gothic", 10)
$bold = New-Object Drawing.Font("Malgun Gothic", 10, [Drawing.FontStyle]::Bold)
$form = New-Object Windows.Forms.Form
$form.Text = "$DisplayName 설치"
$form.ClientSize = New-Object Drawing.Size(720, 676)
$form.FormBorderStyle = "FixedDialog"; $form.MaximizeBox = $false
$form.StartPosition = "CenterScreen"
$form.Font = $font
$form.BackColor = $C_BG; $form.ForeColor = $C_TEXT
$ico = Join-Path $Source "pet\renderer\img\icon.ico"
if (Test-Path $ico) { $form.Icon = New-Object Drawing.Icon($ico) }

function Add-Label($text, $x, $y, $w, $h, $f = $font, $color = $null) {
  $l = New-Object Windows.Forms.Label
  $l.Text = $text; $l.Location = New-Object Drawing.Point($x, $y); $l.Size = New-Object Drawing.Size($w, $h); $l.Font = $f
  if ($color) { $l.ForeColor = $color }
  $form.Controls.Add($l); return $l
}
$t = Add-Label "$DisplayName 설치" 24 14 600 36 (New-Object Drawing.Font("Malgun Gothic", 18, [Drawing.FontStyle]::Bold))
$accLine = New-Object Windows.Forms.Panel
$accLine.Location = New-Object Drawing.Point(26, 50); $accLine.Size = New-Object Drawing.Size(36, 3); $accLine.BackColor = $C_ACC
$form.Controls.Add($accLine)
$null = Add-Label "말로 부르는 내 PC 비서와 바탕화면 펫을 이 PC 에 설치해요. '설치'를 누르면 나머지는 저절로 해요." 26 60 680 22 $font $C_MUTED

# '이 PC' 칸 — 진한 판 + 제목(테두리 상자 대신: 어두운 바탕에서 윈도우 기본 테두리가 밝게 튀어서)
$box = New-Object Windows.Forms.Panel
$box.Location = New-Object Drawing.Point(24, 88); $box.Size = New-Object Drawing.Size(672, 152); $box.BackColor = $C_CARD
$form.Controls.Add($box)
$boxT = New-Object Windows.Forms.Label
$boxT.Text = "이 PC"; $boxT.Font = $bold; $boxT.ForeColor = $C_ACCINK; $boxT.Location = New-Object Drawing.Point(14, 8); $boxT.Size = New-Object Drawing.Size(300, 20)
$box.Controls.Add($boxT)
$gtext = if ($spec.gpu) { "$($spec.gpu) ($([math]::Round($spec.mib / 1024)) GB)" } else { "엔비디아 그래픽카드 없음" }
$specLbl = New-Object Windows.Forms.Label
$specLbl.Font = $font; $specLbl.ForeColor = $C_TEXT; $specLbl.Location = New-Object Drawing.Point(14, 30); $specLbl.Size = New-Object Drawing.Size(645, 116)
$specLbl.Text = "그래픽카드: $gtext`r`n메모리(램): $($spec.ram) GB · 남은 디스크: $($spec.free) GB`r`n추천 구성: $($spec.kind)`r`n$($spec.hint)"
$box.Controls.Add($specLbl)

$chkBrain = New-Object Windows.Forms.CheckBox
$chkBrain.Text = "그래도 이 PC 에서 두뇌 돌리기(느림 — 약 5GB 를 더 받아요)"
$chkBrain.Location = New-Object Drawing.Point(26, 246); $chkBrain.Size = New-Object Drawing.Size(600, 24)
$chkBrain.FlatStyle = "Flat"; $chkBrain.ForeColor = $C_TEXT
$chkBrain.Visible = ($spec.kind -eq "그래픽카드 없음" -or $spec.kind -eq "그래픽 메모리 6GB 미만")
$form.Controls.Add($chkBrain)

$locLbl = Add-Label "설치 위치: $Prefix" 26 276 560 22 $font $C_MUTED
function Set-BtnStyle($b, [bool]$primary) {
  $b.FlatStyle = "Flat"; $b.UseVisualStyleBackColor = $false; $b.Cursor = [Windows.Forms.Cursors]::Hand
  $b.FlatAppearance.BorderSize = 1
  if ($primary) {
    $b.BackColor = $C_ACC; $b.ForeColor = [Drawing.Color]::White; $b.FlatAppearance.BorderColor = $C_ACC
    $b.FlatAppearance.MouseOverBackColor = [Drawing.Color]::FromArgb(230, 0, 81); $b.FlatAppearance.MouseDownBackColor = [Drawing.Color]::FromArgb(200, 0, 70)
  } else {
    $b.BackColor = $C_BG; $b.ForeColor = $C_TEXT; $b.FlatAppearance.BorderColor = $C_LINE
    $b.FlatAppearance.MouseOverBackColor = $C_CARD; $b.FlatAppearance.MouseDownBackColor = $C_LINE
  }
}
$locBtn = New-Object Windows.Forms.Button
$locBtn.Text = "바꾸기"; $locBtn.Location = New-Object Drawing.Point(600, 270); $locBtn.Size = New-Object Drawing.Size(96, 30)
Set-BtnStyle $locBtn $false
$form.Controls.Add($locBtn)
$locBtn.Add_Click({
  $d = New-Object Windows.Forms.FolderBrowserDialog
  $d.Description = "김비서를 설치할 폴더(그 안에 KimBiseo 폴더를 만들어요)"
  if ($d.ShowDialog() -eq "OK") {
    $script:Prefix = Join-Path $d.SelectedPath "KimBiseo"; $script:status = Join-Path $script:Prefix "install\status.json"
    $locLbl.Text = "설치 위치: $($script:Prefix)"
  }
})

$stepY = 308
$stepLbls = @{}
$stepNames = @(@("python", "파이썬 준비"), @("plan", "이 PC 사양 확인"), @("files", "프로그램 파일"), @("packages", "파이썬 부품"),
               @("brain", "두뇌 프로그램"), @("models", "모델(두뇌·귀·목소리)"), @("pet", "펫"), @("finish", "바탕화면 아이콘·마무리"))
for ($i = 0; $i -lt $stepNames.Count; $i++) {
  $col = [math]::Floor($i / 4); $row = $i % 4
  $stepLbls[$stepNames[$i][0]] = Add-Label ("○  " + $stepNames[$i][1]) (30 + 340 * $col) ($stepY + 26 * $row) 330 24 $font $C_MUTED
}
# 진행 막대 — 윈도우 기본 막대는 색을 못 바꿔서(초록) 판 두 장으로 그림
$bar = New-Object Windows.Forms.Panel
$bar.Location = New-Object Drawing.Point(26, 424); $bar.Size = New-Object Drawing.Size(670, 8); $bar.BackColor = $C_LINE
$form.Controls.Add($bar)
$barFill = New-Object Windows.Forms.Panel
$barFill.Location = New-Object Drawing.Point(0, 0); $barFill.Size = New-Object Drawing.Size(0, 8); $barFill.BackColor = $C_ACC
$bar.Controls.Add($barFill)
$detail = Add-Label "인터넷에서 약 $($spec.need)GB 를 받아요(python.org · PyPI · PyTorch · GitHub · 허깅페이스 — 공식 배포처에서 이 PC 가 직접 받아요)." 26 448 670 44 $font $C_MUTED
$errLbl = Add-Label "" 26 496 670 96 $font $C_BAD

function Add-Btn($text, $x, $w) {
  $b = New-Object Windows.Forms.Button
  $b.Text = $text; $b.Location = New-Object Drawing.Point($x, 616); $b.Size = New-Object Drawing.Size($w, 40); $b.Font = $bold
  Set-BtnStyle $b ($x -lt 100)
  $form.Controls.Add($b); return $b
}
$btnInstall = Add-Btn "설치" 26 150
$btnRetry = Add-Btn "다시 하기" 26 150; $btnRetry.Visible = $false
$btnRun = Add-Btn "$DisplayName 켜기" 26 180; $btnRun.Visible = $false
$btnLog = Add-Btn "기록 보기" 450 110; $btnLog.Font = $font
$btnClose = Add-Btn "닫기" 576 120; $btnClose.Font = $font
$state0 = Join-Path $Prefix "install\state.json"
if (Test-Path $state0) {
  try { if (([IO.File]::ReadAllText($state0, $utf8) | ConvertFrom-Json).installed_at) { $btnInstall.Text = "다시 설치(고치기)" } } catch { }
}

function Save-Shot([string]$name) {
  if (-not $ShotDir) { return }
  try {
    New-Item -ItemType Directory -Force -Path $ShotDir | Out-Null
    $bmp = New-Object Drawing.Bitmap($form.Width, $form.Height)
    $form.DrawToBitmap($bmp, (New-Object Drawing.Rectangle(0, 0, $form.Width, $form.Height)))
    $bmp.Save((Join-Path $ShotDir "$name.png"), [Drawing.Imaging.ImageFormat]::Png); $bmp.Dispose()
  } catch { }
}

$mark = @{ "기다림" = "○"; "하는 중" = "●"; "됨" = "✔"; "건너뜀" = "–"; "실패" = "✖" }
$script:shotsDone = @{}
function Update-View {
  if (-not (Test-Path $script:status)) { return }
  try { $s = [IO.File]::ReadAllText($script:status, $utf8) | ConvertFrom-Json } catch { return }
  foreach ($st in $s."단계") {
    $l = $stepLbls[$st.id]
    if ($l) {
      $l.Text = ($mark[$st."상태"]) + "  " + $st."이름" + $(if ($st."상태" -eq "하는 중") { " …" } else { "" })
      $l.ForeColor = if ($st."상태" -eq "실패") { $C_BAD } elseif ($st."상태" -eq "됨") { $C_OK } elseif ($st."상태" -eq "하는 중") { $C_ACCINK } elseif ($st."상태" -eq "건너뜀") { $C_MUTED } else { $C_MUTED }
      $l.Font = if ($st."상태" -eq "하는 중") { $bold } else { $font }
    }
  }
  $barFill.Width = [int]([math]::Min(1000, [math]::Max(0, [double]$s."전체" * 10)) * $bar.Width / 1000)
  if ($s."글") { $detail.Text = [string]$s."글" }
  if ($s."구성" -and $s."구성"."이름") {
    $c = $s."구성"
    $specLbl.Text = "그래픽카드: $($c.'그래픽카드')$(if ($c.'그래픽_GB') { ' (' + $c.'그래픽_GB' + ' GB)' })`r`n메모리(램): $($c.'램_GB') GB · 남은 디스크: $($c.'디스크_여유_GB') GB · 필요 약 $($c.'필요_GB') GB`r`n구성: $($c.'이름') · 두뇌: $($c.'두뇌')`r`n" + (($c.'안내' + $c.'경고') -join " ")
  }
  if ($s."지금" -eq "models" -and -not $script:shotsDone["models"]) { $script:shotsDone["models"] = 1; Save-Shot "2_설치중_모델" }
}

function Start-Worker {
  $errLbl.Text = ""; $btnInstall.Visible = $false; $btnRetry.Visible = $false; $locBtn.Enabled = $false; $chkBrain.Enabled = $false
  $a = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", (Join-Path $PSScriptRoot "worker.ps1"),
         "-Prefix", $script:Prefix, "-DataDir", $DataDir, "-Status", $script:status, "-Source", $Source, "-RegKey", $RegKey, "-DisplayName", $DisplayName)
  if ($chkBrain.Checked) { $a += "-LocalBrain" }
  if ($Gemma) { $a += @("-Gemma", $Gemma) }
  if ($DesktopDir) { $a += @("-DesktopDir", $DesktopDir) }
  if ($StartMenuDir) { $a += @("-StartMenuDir", $StartMenuDir) }
  if ($PacksCatalog -ne "<none>") { $a += @("-PacksCatalog", $PacksCatalog) }
  $q = ($a | ForEach-Object { if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ } }) -join " "
  $psi = New-Object Diagnostics.ProcessStartInfo("powershell.exe", $q)
  $psi.UseShellExecute = $false; $psi.CreateNoWindow = $true
  $script:worker = [Diagnostics.Process]::Start($psi)
  $detail.Text = "설치를 시작했어요."
  $timer.Start()
}

$timer = New-Object Windows.Forms.Timer
$timer.Interval = 500
$timer.Add_Tick({
  Update-View
  if ($script:worker -and $script:worker.HasExited) {
    $timer.Stop()
    Update-View
    $s = $null; try { $s = [IO.File]::ReadAllText($script:status, $utf8) | ConvertFrom-Json } catch { }
    $locBtn.Enabled = $true
    if ($s -and $s."성공") {
      $script:result = $s
      $detail.Text = "설치가 끝났어요. 바탕화면의 '$DisplayName' 아이콘으로도 켤 수 있어요."
      $btnRun.Visible = $true
      Save-Shot "3_설치끝"
    } else {
      $e = if ($s) { $s."오류" } else { $null }
      $errLbl.Text = if ($e) { "멈춘 곳: $($e.'단계')`r`n$($e.'이유')`r`n(자세히: $([string]$e.'자세히' | ForEach-Object { $_.Substring(0, [math]::Min(160, $_.Length)) }))" } else { "설치가 끝나지 않았어요. '다시 하기'를 눌러 주세요." }
      $btnRetry.Visible = $true
      Save-Shot "3_설치실패"
    }
  }
})
$btnInstall.Add_Click({ Save-Shot "1_시작"; Start-Worker })
$btnRetry.Add_Click({ Start-Worker })
$btnRun.Add_Click({
  $r = $script:result."실행"
  $q = ($r."인자" | ForEach-Object { if ($_ -match '[\s"]') { '"' + $_ + '"' } else { $_ } }) -join " "
  Start-Process -FilePath $r."파이썬" -ArgumentList $q -WorkingDirectory $r."작업폴더"
  $form.Close()
})
$btnLog.Add_Click({ $lg = Join-Path $DataDir "logs\install.log"; if (Test-Path $lg) { Start-Process notepad.exe -ArgumentList ('"' + $lg + '"') } })
$btnClose.Add_Click({ $form.Close() })
$form.Add_FormClosing({
  param($sender, $e)
  if ($script:worker -and -not $script:worker.HasExited) {
    $r = [Windows.Forms.MessageBox]::Show("설치를 멈출까요? 받은 것은 남아서 '다시 하기' 때 이어서 받아요.", "$DisplayName 설치", "YesNo", "Question")
    if ($r -ne "Yes") { $e.Cancel = $true; return }
    # 이 창이 띄운 일꾼(과 그 아래 프로세스)만 끔
    & taskkill.exe /PID $script:worker.Id /T /F | Out-Null
  }
})
if ($Auto) { $form.Add_Shown({ Save-Shot "1_시작"; Start-Worker }) }
[void]$form.ShowDialog()

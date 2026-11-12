# 김비서 펫 말하기 도우미 — 윈도우 내장 한국어 음성(SAPI)으로 wav + 음소 시각을 만든다.
# 펫(main)이 켜 두고 한 줄씩 일을 준다(표준입력): "<번호>`t<빠르기>"  →  <폴더>\<번호>.txt 를 읽어 <번호>.wav / <번호>.tsv 를 만들고
# 표준출력에 "OK`t<번호>" 또는 "ERR`t<번호>`t<이유>" 를 쓴다. "QUIT" 이나 입력 끝이면 끝냄.
# 이벤트 시각은 음성 엔진 고유 표본율(16kHz) 기준 → wav 도 16kHz.
param([string]$Dir)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Speech
$code = @"
using System; using System.Collections.Generic; using System.Speech.Synthesis; using System.Speech.AudioFormat;
public static class PetTts {
  public static string VoiceName() {
    var s = new SpeechSynthesizer();
    string pick = null;
    foreach (var v in s.GetInstalledVoices()) {
      if (!v.Enabled) continue;
      if (v.VoiceInfo.Name == "Microsoft Heami Desktop") { pick = v.VoiceInfo.Name; break; }
      if (pick == null && v.VoiceInfo.Culture.Name == "ko-KR") pick = v.VoiceInfo.Name;
    }
    s.Dispose();
    return pick ?? "";
  }
  public static List<string> Run(string voice, string text, string wav, int rate) {
    var L = new List<string>();
    var s = new SpeechSynthesizer();
    if (voice.Length > 0) s.SelectVoice(voice);
    s.Rate = rate;
    s.PhonemeReached += (o, e) => L.Add("P\t" + e.AudioPosition.TotalMilliseconds + "\t" + e.Duration.TotalMilliseconds + "\t" + e.Phoneme);
    s.SpeakProgress += (o, e) => L.Add("W\t" + e.AudioPosition.TotalMilliseconds + "\t" + e.CharacterPosition + "\t" + e.CharacterCount);
    s.SetOutputToWaveFile(wav, new SpeechAudioFormatInfo(16000, AudioBitsPerSample.Sixteen, AudioChannel.Mono));
    s.Speak(text);
    s.SetOutputToNull();
    s.Dispose();
    return L;
  }
}
"@
Add-Type -TypeDefinition $code -ReferencedAssemblies System.Speech
$voice = [PetTts]::VoiceName()
[Console]::Out.WriteLine("READY`t$voice")
[Console]::Out.Flush()
$utf8 = New-Object System.Text.UTF8Encoding($false)
while ($true) {
  $line = [Console]::In.ReadLine()
  if ($null -eq $line -or $line -eq 'QUIT') { break }
  $f = $line.Split("`t")
  $id = $f[0]
  if ($id -notmatch '^[0-9]+$') { continue }
  try {
    $rate = 0
    if ($f.Length -gt 1) { $rate = [Math]::Max(-10, [Math]::Min(10, [int]$f[1])) }
    $text = [System.IO.File]::ReadAllText((Join-Path $Dir "$id.txt"), [System.Text.Encoding]::UTF8)
    $L = [PetTts]::Run($voice, $text, (Join-Path $Dir "$id.wav"), $rate)
    [System.IO.File]::WriteAllLines((Join-Path $Dir "$id.tsv"), [string[]]$L, $utf8)
    [Console]::Out.WriteLine("OK`t$id")
  } catch {
    $msg = $_.Exception.Message -replace "[`r`n`t]", " "
    [Console]::Out.WriteLine("ERR`t$id`t$msg")
  }
  [Console]::Out.Flush()
}

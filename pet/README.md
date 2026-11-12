# pet — 김비서 바탕화면 펫

바탕화면 위에 김비서를 띄우는 Electron 프로그램입니다. 본체(`app/`)가 말하는 동안 표정·입 모양·동작·말풍선 신호를 받아 움직입니다.
캐릭터 영상은 프로그램에 들어 있지 않고, **옷 꾸러미(.hipcpet)** 를 따로 받아서 입힙니다.

## 켜기

```
cd pet
npm install            # electron 만 받음(개발용)
npx electron .
```

- 옷이 하나도 없으면 "옷이 아직 없어요" 안내가 뜹니다. 누르면 **옷 받기** 창이 열립니다.
- 오른쪽 클릭 메뉴: 옷 고르기 · 옷 받기 · 파일로 옷 추가 · 크기 · (춤 노래를 켠 판만) 춤 노래 크기 · 항상 위에 두기 · 끝내기
- 사용자 자료(설정·받은 옷·로그)는 `%APPDATA%\KimBiseo\pet` 에 둡니다(`--profile=<폴더>` 로 바꿀 수 있음).

### 켤 때 줄 수 있는 것

| 옵션 | 뜻 |
|---|---|
| `--profile=<폴더>` | 사용자 자료 폴더를 바꿈 |
| `--pack-source=<주소>` | 옷 목록(packs.json) 주소를 이번에만 바꿈 |
| `--add-pack=<파일>` | 옷 꾸러미 파일을 넣음(파일 두 번 누르기와 같음) |
| `--assoc` | `.hipcpet` 파일 연결을 이 펫으로(현재 사용자만, 켤 때만) |
| `--auto-pack` / `--no-auto-pack` | 옷이 없을 때 기본 옷을 저절로 받기 켬/끔(기본 끔) |
| `--lip=off` | 입 맞추기 끔 |

## 설정 (`config.json`)

| 칸 | 기본값 | 뜻 |
|---|---|---|
| `packs_catalog` | 빈칸 | 옷 목록(packs.json) 주소. 비어 있으면 "파일로 옷 추가"만 됩니다 |
| `allowed_hosts` | GitHub 3곳 + 옷 받는 서버 | 옷을 받아도 되는 https 호스트. 이 PC(127.0.0.1·localhost)는 늘 허용 |
| `voice_url` | `http://127.0.0.1:8871` | 김비서 목소리 서버(펫 메뉴의 '말하기 시험'용, 이 PC 주소만) |
| `port` | `17961` | 펫 신호 입구. 쓰는 중이면 +1~+9, 실제 번호는 사용자 자료 폴더의 `speak_port.txt` |
| `default_pack` | `kimbiseo_f` | 기본 옷 id |

옷 목록 주소는 `--pack-source` → 사용자 설정(`packSource`) → `config.json` 의 `packs_catalog` 순서로 먼저 있는 것을 씁니다.

## 신호 입구 (127.0.0.1 만)

`POST` + JSON. `Host` 가 127.0.0.1/localhost 가 아니거나 `Origin` 머리가 있으면(웹페이지에서 부름) 거절합니다.

| 주소 | 보내는 것 |
|---|---|
| `/expr` | `{"name":"보통", "seconds":4}` 표정(보통·기쁨·놀람·졸림·생각·부끄러움·화남, 영어 별칭도 됨) |
| `/emotion` | `{"name":"…"}` 감정 동작(이름 목록 = `GET /emotions`) |
| `/motion` | `{"name":"sit"}` 동작(앉기·눕기·일어나기·인사·손하트·춤 등, 옷에 있는 것 = `GET /extras`) |
| `/mouth`, `/lip` | `{"level":0.0~1.0}` 입 벌림 |
| `/talk` | `{"on":true}` 말하는 중 켬/끔 |
| `/bubble` | `{"text":"…","seconds":4}` 말풍선(300자까지) |
| `/speak` | `{"text":"…"}` 말풍선 + 목소리(목소리 서버가 있을 때) |
| `/skin` | `{"id":"kimbiseo_f"}` 옷 바꾸기 |
| `/packs/auto` | `{}` 옷 목록에서 기본 옷을 받아 입기(처음 화면에서 '옷 받기'에 동의했을 때 본체가 부름). 목록 주소가 없으면 `nosource` |
| `GET /status`, `/extras`, `/emotions` | 상태 · 지금 옷의 동작/춤/자세별 동작 표 · 감정 목록 |

### 자세별 동작

앉거나 누워 있을 때 동작 신호가 오면:

1. 옷 꾸러미에 그 자세용 클립(`sit_<동작>`·`lie_<동작>`·`desk_<동작>` 또는 클립 `motion` 칸 `{"of":"<동작>","pose":"sit"}`)이 있으면 그 자세 그대로 합니다.
2. 없으면 일어나서 서서 합니다.

## 옷 꾸러미 (.hipcpet)

zip 파일입니다.

```
pack.json        {"format":"hipcpet/1","id":…,"name":…,"version":…,"clips":{…},"music":[…],"files":{"<이름>":{"size":…,"sha256":…}}}
signature.json   {"alg":"ed25519","key":"kimbiseo-pack-1","sig":"<pack.json 바이트의 서명>"}
preview.png
clips/*.webm
music/*.mp3      (노래 포함판만)
```

- 서명 있는 꾸러미: 서명이 맞고, 모든 파일의 sha256 이 `pack.json` 과 같고, 목록에 없는 파일이 없어야 들어갑니다. 하나라도 틀리면 거절합니다.
- 서명 없는 꾸러미: "공식 꾸러미가 아니에요" 경고를 띄우고 사용자가 고를 때만 넣습니다.
- 옷 목록에 `"signed": true` 인 옷인데 받은 파일에 서명이 없으면 거절합니다.
- 공개키는 `packs.js` 의 `PUBKEYS` 에 있습니다. 비밀키는 저장소에 없습니다.

### 춤 노래 고르는 순서

> **공개판 기본은 춤 노래 끔**(`config.json` 의 `"dance_music": false`) — 춤은 추되 소리 없이 나오고, `춤노래` 폴더·'춤 노래 크기' 칸도 만들지 않습니다. 기본 옷 꾸러미도 노래가 들어 있지 않은 판입니다. 아래 순서는 `dance_music` 을 켰을 때만 씁니다.

1. 사용자 자료 폴더의 `춤노래` 폴더에 춤 이름으로 시작하는 노래 파일
2. 지금 옷 꾸러미 안의 노래(`music` 칸의 `dance` 가 같은 것)
3. 기본 춤(dance1~3)만: 프로그램에 든 합성 배경음 `renderer/real/music/danceN.mp3`(출처 `SOURCES.txt`)
4. 없으면 노래 없이 춤만

노래 없는 판으로 바꾸면 그 옷의 노래는 함께 사라집니다(사용자 폴더로 복사해 두지 않음).

## 옷 목록 (packs.json)

```json
{
  "format": "kimbiseo-packs/1",
  "packs": [
    {"id": "kimbiseo_f", "name": "김비서(여)", "version": "…", "body": "", "gender": "여성",
     "size": 170181796, "sha256": "…", "signed": true, "url": "kimbiseo_f_….hipcpet",
     "preview": "kimbiseo_f_….preview.png", "default": true, "songs": true, "note": "…"},
    {"id": "kimbiseo_m", "name": "김비서(남)", "gender": "남성", "soon": true, "note": "준비 중이에요"}
  ]
}
```

- `url`·`preview` 는 목록 주소 기준 상대 주소도 됩니다. https + `allowed_hosts` 만 받고, 넘겨주기(redirect)도 매번 다시 봅니다(최대 5번).
- 받은 파일의 sha256 이 목록과 다르거나, 꾸러미 id 가 목록의 id 와 다르면 넣지 않습니다.
- `soon: true` 는 목록에 "준비 중"으로만 보입니다.

## 꾸러미 만들기 (`tools/`)

```
node tools/pack_sign.js keygen <비밀키.pem>        # 저장소 밖에 둘 것
node tools/pack_sign.js pubkey <비밀키.pem>        # packs.js PUBKEYS 에 넣을 공개키
python tools/pack_make.py --src <원본.hipcpet> --out <새.hipcpet> --key <비밀키.pem> --key-id kimbiseo-pack-1 \
       --id kimbiseo_f --name "김비서(여)" --gender 여성 --version <버전> --maker "<만든 곳>" --music keep|none
python tools/make_catalog.py --out packs.json --default <기본 꾸러미 파일 이름> <꾸러미.hipcpet>...
python tools/release_check.py artifact <꾸러미.hipcpet> --manifest <꾸러미>.manifest.json
```

`pack_make.py` 는 정해진 칸만 남기고(내부 메모·경로 버림), PNG 글 묶음을 지우고, 파일 이름을 영어로 바꾸고, 서명합니다.
옷 꾸러미 파일과 노래는 이 저장소에 넣지 않습니다(따로 내려받는 파일).

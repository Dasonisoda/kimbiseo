package kr.kimbiseo.phone

import java.net.URLEncoder

/**
 * 폰 동작 규칙(안드로이드 API 를 안 쓰는 순수 규칙 — JVM 단위 시험 RulesTest).
 *  길안내 주소, 연락처 이름 너그럽게 찾기(운영 폰 앱과 같은 방식: 이모지·호칭·띄어쓰기·받아쓰기 모음 혼동), 앱 이름 찾기.
 */
object NavRules {
    data class Target(val app: String, val pkg: String, val uri: String, val note: String = "")

    const val KAKAOMAP = "net.daum.android.map"
    const val NAVER = "com.nhn.android.nmap"
    const val TMAP = "com.skt.tmap.ku"
    const val GOOGLE = "com.google.android.apps.maps"
    const val KAKAONAVI = "com.locnall.KimGiSa"

    fun enc(s: String): String = URLEncoder.encode(s, "UTF-8").replace("+", "%20")

    /** 고른 앱(없으면 깔린 순서: 카카오맵 → 네이버지도 → 티맵 → 구글지도 → 카카오내비)으로 목적지 검색·길안내 화면 주소.
     *  좌표 없이 이름으로 찾음(공개판은 지도 열쇠가 없음). 아무것도 없으면 웹 카카오맵. */
    fun pick(dest: String, want: String, installed: (String) -> Boolean, appName: String): Target {
        val d = enc(dest)
        val all = listOf("kakaomap", "naver", "tmap", "google", "kakaonavi")
        val order = if (want in all) listOf(want) + all.filter { it != want } else all
        for (a in order) {
            val t = when (a) {
                "kakaomap" -> Target("카카오맵", KAKAOMAP, "kakaomap://search?q=$d", "검색 결과에서 '길찾기'를 눌러 주세요")
                "naver" -> Target("네이버지도", NAVER, "nmap://search?query=$d&appname=" + enc(appName), "검색 결과에서 '길찾기'를 눌러 주세요")
                "tmap" -> Target("티맵", TMAP, "tmap://search?name=$d", "검색 결과에서 목적지를 골라 주세요")
                "google" -> Target("구글지도", GOOGLE, "google.navigation:q=$d")
                "kakaonavi" -> Target("카카오내비", KAKAONAVI, "", "목적지 이름을 복사해 뒀어요 — 검색창에 붙여 넣어 주세요")
                else -> null
            } ?: continue
            if (installed(t.pkg)) return t
        }
        return Target("웹 지도", "", "https://map.kakao.com/?q=$d", "")
    }
}

object NameRules {
    const val STRONG = 75
    const val NEAR = 30
    private val TITLES = listOf("사장님", "대표님", "선생님", "고객님", "부장님", "과장님", "차장님", "실장님", "팀장님", "이사님", "회장님", "원장님",
        "교수님", "소장님", "주임님", "대리님", "기사님", "사모님", "형님", "누님", "사장", "대표", "선생", "손님", "쌤", "님", "씨", "형", "누나",
        "언니", "오빠", "이모", "삼촌", "선배")
    private val CHO_FOLD = intArrayOf(0, 0, 2, 3, 3, 5, 6, 7, 7, 9, 9, 11, 12, 12, 14, 15, 16, 17, 18)
    private val JUNG_FOLD = intArrayOf(0, 1, 0, 1, 4, 1, 4, 1, 8, 9, 10, 10, 8, 13, 14, 10, 16, 13, 18, 20, 20)

    fun digits(s: String?): String {
        var d = (s ?: "").filter { it.isDigit() || it == '+' }
        if (d.startsWith("+82")) d = "0" + d.removePrefix("+82").trimStart('0')
        return d.filter { it.isDigit() }
    }

    fun cleanName(q: String?): String {
        var t = (q ?: "").trim()
        t = t.replace(Regex("(한테|에게|께)$"), "").trim()
        return t.take(30)
    }

    fun normName(s: String?): String {
        val t = s ?: ""; val sb = StringBuilder(); var i = 0
        while (i < t.length) {
            val cp = t.codePointAt(i)
            if (Character.isLetterOrDigit(cp)) sb.appendCodePoint(Character.toLowerCase(cp))
            i += Character.charCount(cp)
        }
        return sb.toString()
    }

    fun stripTitles(n: String): String {
        var t = n
        while (true) {
            val hit = TITLES.firstOrNull { t.endsWith(it) && t.length > it.length } ?: return t
            t = t.dropLast(hit.length)
        }
    }

    fun variants(s: String?): Set<String> {
        val raw = s ?: ""
        val a = normName(raw)
        val b = normName(raw.replace(Regex("\\([^)]*\\)|\\[[^\\]]*\\]"), ""))
        return linkedSetOf(a, b, stripTitles(a), stripTitles(b)).filter { it.isNotEmpty() }.toSet()
    }

    private fun isSyl(c: Char) = c in '가'..'힣'

    fun foldSyl(s: String): String {
        val sb = StringBuilder()
        for (c in s) {
            if (!isSyl(c)) { sb.append(c); continue }
            val i = c - '가'
            sb.append('가' + (CHO_FOLD[i / 588] * 588 + JUNG_FOLD[(i % 588) / 28] * 28 + i % 28))
        }
        return sb.toString()
    }

    fun jamo(s: String): String {
        val sb = StringBuilder()
        for (c in foldSyl(s)) {
            if (!isSyl(c)) { sb.append(c); continue }
            val i = c - '가'
            sb.append('ᄀ' + i / 588).append('ᅡ' + (i % 588) / 28)
            if (i % 28 != 0) sb.append('ᆧ' + i % 28)
        }
        return sb.toString()
    }

    fun lev(a: String, b: String): Int {
        if (a.isEmpty()) return b.length
        if (b.isEmpty()) return a.length
        var prev = IntArray(b.length + 1) { it }; var cur = IntArray(b.length + 1)
        for (i in 1..a.length) {
            cur[0] = i
            for (j in 1..b.length) cur[j] = minOf(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + if (a[i - 1] == b[j - 1]) 0 else 1)
            val t = prev; prev = cur; cur = t
        }
        return prev[b.length]
    }

    private fun pairScore(q: String, d: String): Int {
        if (q.isEmpty() || d.isEmpty()) return 0
        if (q == d) return 100
        val fq = foldSyl(q); val fd = foldSyl(d)
        if (fq == fd) return 95
        if (q.length >= 2) {
            if (d.startsWith(q)) return 88
            if (fd.startsWith(fq)) return 85
            if (d.contains(q)) return 80
            if (fd.contains(fq)) return 78
        }
        if (d.length >= 2 && d.length * 2 >= q.length) {
            if (q.contains(d)) return 76
            if (fq.contains(fd)) return 75
        }
        val jq = jamo(q); val jd = jamo(d)
        var sim = 1.0 - lev(jq, jd).toDouble() / maxOf(jq.length, jd.length)
        if (q.length >= 3 && jd.length > jq.length) sim = maxOf(sim, 0.85 * (1.0 - lev(jq, jd.take(jq.length)).toDouble() / jq.length))
        return if (sim < 0.4) 0 else minOf(72, (sim * 80).toInt())
    }

    fun nameScore(query: String, display: String?): Int {
        var best = 0
        for (q in variants(query)) for (d in variants(display)) best = maxOf(best, pairScore(q, d))
        return best
    }

    data class Ranked(val list: List<Triple<String, String, Int>>, val near: List<Triple<String, String, Int>>)

    fun rank(query: String, contacts: List<Pair<String, String>>): Ranked {
        val all = ArrayList<Triple<String, String, Int>>()
        for ((name, num) in contacts) {
            if (digits(num).isEmpty()) continue
            val sc = nameScore(query, name)
            if (sc >= NEAR) all.add(Triple(name, num, sc))
        }
        val seen = HashSet<String>()
        val uniq = all.sortedByDescending { it.third }.filter { seen.add(digits(it.second)) }
        var strong = uniq.filter { it.third >= STRONG }.take(6)
        if (strong.size >= 2 && strong[0].third >= 95 && strong[1].third <= strong[0].third - 10) strong = strong.take(1)
        val used = strong.map { digits(it.second) }.toSet()
        val near = uniq.filter { it.third < STRONG && digits(it.second) !in used }.take(3)
        return Ranked(strong, near)
    }
}

object AppRules {
    /** 말로 부르는 이름 → 앱 서랍 이름 후보(한국어 폰에서도 영어 이름인 앱들) */
    private val ALIAS = mapOf(
        "유튜브" to listOf("youtube"), "유투브" to listOf("youtube"), "유튜브뮤직" to listOf("youtubemusic"),
        "카톡" to listOf("카카오톡", "kakaotalk"), "카카오톡" to listOf("kakaotalk"), "크롬" to listOf("chrome"),
        "지메일" to listOf("gmail"), "구글지도" to listOf("지도", "maps", "googlemaps"), "플레이스토어" to listOf("playstore", "play스토어"),
        "넷플릭스" to listOf("netflix"), "인스타" to listOf("instagram", "인스타그램"), "인스타그램" to listOf("instagram"),
        "페이스북" to listOf("facebook"), "왓츠앱" to listOf("whatsapp"), "텔레그램" to listOf("telegram"), "스포티파이" to listOf("spotify"),
        "설정" to listOf("settings"), "카메라" to listOf("camera"), "계산기" to listOf("calculator"), "시계" to listOf("clock"),
        "달력" to listOf("캘린더", "calendar"), "캘린더" to listOf("calendar"), "갤러리" to listOf("사진", "photos", "gallery"),
        "사진" to listOf("갤러리", "photos", "gallery"), "메시지" to listOf("문자", "messages"), "문자" to listOf("메시지", "messages"),
        "전화" to listOf("phone", "전화"), "연락처" to listOf("contacts"), "파일" to listOf("내파일", "files"), "녹음기" to listOf("음성녹음", "recorder"))

    /** 앱 이름(말) → (앱 서랍 이름, 패키지) 목록에서 가장 맞는 것의 위치(없으면 -1) */
    fun best(want: String, labels: List<String>): Int {
        val w = NameRules.normName(want).removeSuffix("앱").removeSuffix("어플")
        if (w.isEmpty()) return -1
        val keys = listOf(w) + (ALIAS[w] ?: emptyList()).map { NameRules.normName(it) }
        var bi = -1; var bs = 0
        for ((i, l) in labels.withIndex()) {
            val n = NameRules.normName(l)
            if (n.isEmpty()) continue
            var s = 0
            for ((k, key) in keys.withIndex()) {
                val base = when { n == key -> 100; n.startsWith(key) -> 85; key.length >= 2 && n.contains(key) -> 75; else -> 0 }
                s = maxOf(s, if (k == 0) base else base - 2)
            }
            if (s > bs || (s == bs && s > 0 && n.length < NameRules.normName(labels[bi]).length)) { bs = s; bi = i }
        }
        return if (bs >= 75) bi else -1
    }
}

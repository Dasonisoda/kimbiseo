package kr.kimbiseo.phone

import java.net.URLDecoder

/** PC 화면 QR(kimbiseo://pair?v=1&h=<주소들>&p=<포트>&c=<8자리>&f=<인증서 지문 sha256>&n=<PC 이름>) 또는 직접 넣은 값 */
data class PairInfo(val hosts: List<String>, val port: Int, val code: String, val fp: String, val pcName: String)

/**
 * 연결하기 규칙(안드로이드 API 를 안 쓰는 순수 규칙 — JVM 단위 시험 PairRulesTest).
 *  - 주소는 집 안 네트워크·테일스케일·이 PC 자신 모양만(공인 인터넷 주소·이름은 받지 않음 — PC 도 사설 주소에서 온 연결만 받음).
 *  - 인증서 지문은 64자리(QR) 또는 앞 16자리(직접 넣을 때 PC 화면의 '인증서 확인 글자'). 연결할 때 PC 인증서가 이 지문과 같아야만 함.
 */
object PairRules {
    fun parse(s: String?): PairInfo? {
        val t = (s ?: "").trim()
        if (!t.startsWith("kimbiseo://pair?") || t.length > 1024) return null
        val q = HashMap<String, String>()
        for (kv in t.substringAfter('?').split('&')) {
            val i = kv.indexOf('=')
            if (i <= 0) continue
            q[kv.substring(0, i)] = try { URLDecoder.decode(kv.substring(i + 1).replace("+", "%2B"), "UTF-8") } catch (_: Exception) { return null }
        }
        if (q["v"] != "1") return null
        val hosts = (q["h"] ?: "").split(',').map { it.trim() }.filter { lanHost(it) }.distinct().take(6)
        val port = q["p"]?.toIntOrNull() ?: return null
        if (port !in 1..65535 || hosts.isEmpty()) return null
        val code = cleanCode(q["c"]) ?: return null
        val fp = cleanFp(q["f"]) ?: return null
        if (fp.length != 64) return null
        return PairInfo(hosts, port, code, fp, cleanName(q["n"]))
    }

    /** 8자리 숫자(띄어쓰기·하이픈 허용) */
    fun cleanCode(s: String?): String? {
        val raw = (s ?: "").trim()
        if (raw.any { !(it.isDigit() || it == ' ' || it == '-') }) return null
        val d = raw.filter { it.isDigit() }
        return if (d.length == 8) d else null
    }

    /** 지문: 16진수만 대문자로. 64자리(전체) 또는 16자리(앞부분, 'AB12 CD34 …') */
    fun cleanFp(s: String?): String? {
        val raw = (s ?: "").trim().uppercase()
        if (raw.any { !(it in '0'..'9' || it in 'A'..'F' || it == ' ' || it == ':' || it == '-') }) return null
        val h = raw.filter { it in '0'..'9' || it in 'A'..'F' }
        return if (h.length == 64 || h.length == 16) h else null
    }

    /** 직접 넣은 PC 주소 정리 — 한국어 키보드 쉼표(100,101.1.2)·가운뎃점·띄어쓰기·끝 점을 바로잡음. 모양 검사는 lanHost. */
    fun cleanHost(s: String?): String {
        var t = (s ?: "").trim().replace(" ", "").replace(" ", "")
        if (!t.contains(':')) t = t.replace(',', '.').replace('·', '.').replace('。', '.').replace('．', '.').trim('.')
        return t
    }

    /** 주소가 IPv4 숫자 4묶음인데 사설·테일스케일 범위 밖인지(오류 문구 고르기용) */
    fun publicV4(h: String): Boolean = v4(h) != null && !lanHost(h)

    fun cleanName(s: String?): String = (s ?: "").filter { !it.isISOControl() }.trim().take(30)

    fun words(fp: String): String = fp.take(16).chunked(4).joinToString(" ")

    /** 저장된 지문(64 또는 16자리)과 실제 인증서 지문(64자리)이 맞는지 */
    fun fpMatches(pin: String, actual: String): Boolean {
        val a = actual.uppercase()
        if (a.length != 64) return false
        return when (pin.length) { 64 -> pin == a; 16 -> a.startsWith(pin); else -> false }
    }

    private fun v4(h: String): IntArray? {
        val p = h.split('.')
        if (p.size != 4) return null
        val r = IntArray(4)
        for ((i, x) in p.withIndex()) {
            if (x.isEmpty() || x.length > 3 || x.any { !it.isDigit() }) return null
            r[i] = x.toInt(); if (r[i] > 255) return null
        }
        return r
    }

    /** 집 안 네트워크(10/8·172.16/12·192.168/16·169.254/16)·테일스케일(100.64/10)·이 기기(127/8) IPv4, 또는 사설·링크·테일스케일 IPv6 */
    fun lanHost(h: String): Boolean {
        if (h.isEmpty() || h.length > 45) return false
        val a = v4(h)
        if (a != null) return a[0] == 10 || a[0] == 127 || (a[0] == 172 && a[1] in 16..31) || (a[0] == 192 && a[1] == 168) ||
            (a[0] == 169 && a[1] == 254) || (a[0] == 100 && a[1] in 64..127)
        if (!h.contains(':') || h.any { !(it.isDigit() || it.lowercaseChar() in 'a'..'f' || it == ':' || it == '%') }) return false
        val l = h.lowercase()
        return l.startsWith("fc") || l.startsWith("fd") || l.startsWith("fe8") || l.startsWith("fe9") || l.startsWith("fea") ||
            l.startsWith("feb") || l == "::1"
    }

    fun baseUrl(host: String, port: Int, ws: Boolean = false): String {
        val sch = if (ws) "wss" else "https"
        return if (host.contains(':')) "$sch://[${host.substringBefore('%')}]:$port" else "$sch://$host:$port"
    }
}

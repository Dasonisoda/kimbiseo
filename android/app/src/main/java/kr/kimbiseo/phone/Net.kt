package kr.kimbiseo.phone

import android.os.Build
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.security.MessageDigest
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLContext
import javax.net.ssl.X509TrustManager

/**
 * PC 와의 연결 — 내 PC 가 만든 자체 인증서만 믿는다(인증서 지문 고정).
 *  인증 기관 확인 대신 '짝지을 때 받은 지문과 똑같은 인증서인가'만 본다 → 같은 와이파이의 다른 기기가 PC 인 척해도 연결 안 됨.
 *  주소(IP) 이름 확인은 끈다: 인증서가 정확히 그 PC 의 것인지 지문으로 이미 확인했기 때문(PC 주소는 공유기가 바꿀 수 있음).
 */
class Pinned(private val pin: String) : X509TrustManager {
    @Volatile var seen: String = ""
    override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) { throw CertificateException("client") }
    override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {
        if (chain.isEmpty()) throw CertificateException("인증서 없음")
        val fp = Net.sha256(chain[0].encoded)
        if (!PairRules.fpMatches(pin, fp)) throw CertificateException("인증서 지문이 달라요")
        seen = fp
    }
    override fun getAcceptedIssuers(): Array<X509Certificate> = arrayOf()
}

object Net {
    fun sha256(b: ByteArray): String = MessageDigest.getInstance("SHA-256").digest(b).joinToString("") { "%02X".format(it) }

    fun client(pin: String, ws: Boolean = false): Pair<OkHttpClient, Pinned> {
        val tm = Pinned(pin)
        val ctx = SSLContext.getInstance("TLS")
        ctx.init(null, arrayOf(tm), null)
        val b = OkHttpClient.Builder().sslSocketFactory(ctx.socketFactory, tm).hostnameVerifier { _, _ -> true }
            .connectTimeout(4, TimeUnit.SECONDS).retryOnConnectionFailure(false)
        if (ws) b.readTimeout(0, TimeUnit.MILLISECONDS).pingInterval(15, TimeUnit.SECONDS) else b.readTimeout(10, TimeUnit.SECONDS)
        return Pair(b.build(), tm)
    }

    class PairResult(val ok: Boolean, val msg: String, val host: String = "", val device: String = "", val token: String = "",
                     val fp: String = "", val pcName: String = "")

    /** 연결하기: 주소들을 차례로 — 연결되는 곳에서 코드 보내기. 코드가 틀리면(403) 다른 주소로 다시 보내지 않음(코드는 한 번만). 네트워크 스레드에서 부름.
     *  실패 문구는 까닭별로(PairRules 없이 여기서 고름): 코드 틀림·코드 없음/시간 지남·잠김(PC 가 '왜'·'잠금초'로 알려 줌) /
     *  PC 가 이 주소에서 오는 연결을 안 받음 / 닿지 않음(와이파이·테일스케일 안내) / 인증서 다름. */
    fun pair(info: PairInfo, phoneName: String = deviceName()): PairResult {
        val (http, tm) = client(info.fp)
        var last = unreachable(info.hosts)
        for (h in info.hosts) {
            val body = JSONObject().put("code", info.code).put("name", phoneName).toString().toRequestBody("application/json".toMediaType())
            val req = Request.Builder().url(PairRules.baseUrl(h, info.port) + "/phone/pair").post(body).build()
            try {
                http.newCall(req).execute().use { r ->
                    val j = try { JSONObject(r.body?.string() ?: "{}") } catch (_: Throwable) { JSONObject() }
                    if (r.code == 200 && j.optBoolean("ok")) {
                        return PairResult(true, "연결했어요.", h, j.optString("기기"), j.optString("토큰"), tm.seen, j.optString("PC", info.pcName))
                    }
                    return PairResult(false, pairError(r.code, j, h))
                }
            } catch (e: javax.net.ssl.SSLException) {
                last = "PC 인증서가 연결 코드의 지문과 달라요. PC 화면의 '인증서 확인 글자'와 넣은 글자가 같은지 다시 확인해 주세요."
            } catch (e: Throwable) { /* 다음 주소 */ }
        }
        return PairResult(false, last)
    }

    /** PC 가 답은 했지만 연결이 안 된 까닭 → 사용자 문구 */
    fun pairError(code: Int, j: JSONObject, host: String): String {
        val why = j.optString("왜"); val lock = j.optInt("잠금초", 0); val said = j.optString("오류")
        fun wait(s: Int) = if (s >= 90) "${(s + 59) / 60}분" else "${s}초"
        return when {
            why == "잠김" || (code == 403 && lock > 0 && why.isEmpty()) ->
                "틀린 코드가 여러 번 들어와 잠깐 막혔어요. ${wait(maxOf(lock, 1))} 뒤에 다시 해 주세요."
            why == "잠김_전체" -> "틀린 코드가 너무 많이 들어와 PC 가 연결하기를 잠깐(최대 15분) 막았어요. 조금 뒤에 PC 화면에서 새 코드를 만들어 해 주세요."
            why == "틀림" -> "연결 코드가 PC 화면의 숫자와 달라요. 8자리를 다시 확인해 주세요." + if (lock > 0) " (${wait(lock)} 뒤에 다시)" else ""
            why == "만료" -> "연결 코드 시간(10분)이 지났어요. PC 화면에서 '연결 코드 만들기'를 다시 눌러 새 코드로 해 주세요."
            why == "없음" -> "PC 에 지금 쓸 수 있는 연결 코드가 없어요(이미 썼거나 새로 만들지 않았어요). PC 화면에서 '연결 코드 만들기'를 눌러 주세요."
            why == "주소_거절" || (code == 403 && said.contains("집 안 네트워크")) ->
                if (host.startsWith("100.")) "PC 가 테일스케일 연결을 받지 않게 돼 있어요. PC 김비서 설정 → 폰 연결 → '테일스케일로도 연결 받기'를 켜고 저장해 주세요."
                else "PC 가 이 폰 주소에서 오는 연결을 받지 않았어요. 폰과 PC 가 같은 집 와이파이인지 확인해 주세요."
            code == 403 -> said.ifEmpty { "연결 코드가 맞지 않거나 시간이 지났어요. PC 화면에서 새 코드를 만들어 주세요." }
            else -> said.ifEmpty { "PC 가 연결을 받지 못했어요(응답 $code). PC 김비서를 다시 켜 보세요." }
        }
    }

    /** 어느 주소에도 닿지 않았을 때 — 테일스케일 주소(100.x)면 테일스케일 안내 */
    fun unreachable(hosts: List<String>): String =
        if (hosts.isNotEmpty() && hosts.all { it.startsWith("100.") || it.lowercase().startsWith("fd7a:") })
            "PC(${hosts.first()})에 닿지 않았어요. ① 폰의 테일스케일 앱이 '연결됨'인지 ② PC 도 테일스케일이 켜져 있는지 " +
                "③ PC 김비서가 켜져 있고 설정 → 폰 연결이 켜져 있는지 확인해 주세요."
        else "PC 에 닿지 않았어요. ① 폰과 PC 가 같은 와이파이인지(밖에서는 둘 다 테일스케일을 켜고 PC 의 100.x 주소로) " +
            "② PC 김비서가 켜져 있고 설정 → 폰 연결이 켜져 있는지 확인해 주세요."

    fun deviceName(): String = ((Build.MANUFACTURER ?: "") + " " + (Build.MODEL ?: "")).trim().take(30).ifEmpty { "폰" }
}

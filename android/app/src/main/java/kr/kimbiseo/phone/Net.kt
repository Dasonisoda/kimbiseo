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

    /** 짝짓기: 주소들을 차례로 — 연결되는 곳에서 코드 보내기. 코드가 틀리면(403) 다른 주소로 다시 보내지 않음(코드는 한 번만). 네트워크 스레드에서 부름. */
    fun pair(info: PairInfo, phoneName: String = deviceName()): PairResult {
        val (http, tm) = client(info.fp)
        var last = "PC 에 연결하지 못했어요. 폰과 PC 가 같은 와이파이인지, PC 에서 '폰 연결 켜기'가 켜져 있는지 확인해 주세요."
        for (h in info.hosts) {
            val body = JSONObject().put("code", info.code).put("name", phoneName).toString().toRequestBody("application/json".toMediaType())
            val req = Request.Builder().url(PairRules.baseUrl(h, info.port) + "/phone/pair").post(body).build()
            try {
                http.newCall(req).execute().use { r ->
                    val j = try { JSONObject(r.body?.string() ?: "{}") } catch (_: Throwable) { JSONObject() }
                    if (r.code == 200 && j.optBoolean("ok")) {
                        return PairResult(true, "짝지었어요.", h, j.optString("기기"), j.optString("토큰"), tm.seen, j.optString("PC", info.pcName))
                    }
                    val lock = j.optInt("잠금초", 0)
                    return PairResult(false, j.optString("오류", "짝짓기가 안 됐어요(${r.code}).") + if (lock > 0) " (${lock}초 뒤에 다시)" else "")
                }
            } catch (e: javax.net.ssl.SSLException) {
                last = "PC 인증서가 짝 코드의 지문과 달라요. PC 화면의 '인증서 확인 글자'를 다시 확인해 주세요."
            } catch (e: Throwable) { /* 다음 주소 */ }
        }
        return PairResult(false, last)
    }

    fun deviceName(): String = ((Build.MANUFACTURER ?: "") + " " + (Build.MODEL ?: "")).trim().take(30).ifEmpty { "폰" }
}

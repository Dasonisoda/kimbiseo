package kr.kimbiseo.phone

import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.AudioAttributes
import android.media.AudioDeviceInfo
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.AudioTrack
import android.media.MediaRecorder
import android.media.audiofx.AcousticEchoCanceler
import android.media.audiofx.NoiseSuppressor
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.Looper
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import okio.ByteString.Companion.toByteString
import org.json.JSONObject
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sqrt

/**
 * PC 김비서와의 대화(앞 서비스 — 화면을 꺼도 대화가 이어지고 알림에 '대화 중'이 보임).
 *  연결: 짝지을 때 받은 주소들 중 마지막에 된 곳부터 wss://주소:포트/phone/ws — 인증서 지문이 맞을 때만(Net.kt).
 *  첫 메시지 = 기기 토큰 + 이 앱이 할 수 있는 일(길안내·전화 화면·문자 화면·앱 열기·확인 단추).
 *  소리: 마이크 16kHz → PC(20ms 조각) · PC → 스피커 24kHz. 통화 방식(메아리 제거)으로 열어 김비서 목소리가 마이크로 다시 들어가지 않게.
 *  PC 김비서의 폰 관문(app/core/phone.py)과 이야기하는 쪽. 운영 폰 앱의 대화 연결 방식을 따르되, 서버 주소·열쇠·호출어·음악·통화 기록은 없음.
 */
class TalkService : Service() {
    companion object {
        @Volatile var me: TalkService? = null
        const val CH = "talk"
        const val NID = 1

        fun start(c: Context) { c.startForegroundService(Intent(c, TalkService::class.java)) }
    }

    private val ctl = Handler(HandlerThread("kb-ctl").apply { start() }.looper)
    private val main = Handler(Looper.getMainLooper())
    private var ws: WebSocket? = null
    private var gen = 0
    private var retry = 0
    private var userStop = false
    private var authed = false
    @Volatile var micOn = true
    private var rec: AudioRecord? = null
    private var track: AudioTrack? = null
    private val playQ = LinkedBlockingQueue<ByteArray>()
    private val feed = LinkedBlockingQueue<ShortArray>()     // 시험판(TEST_HOOKS)만: 파일 소리를 마이크 대신
    private var askTimer: Runnable? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        me = this
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CH, "대화 중", NotificationManager.IMPORTANCE_LOW))
        nm.createNotificationChannel(NotificationChannel("ask", "실행 확인", NotificationManager.IMPORTANCE_HIGH))
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val n = Notification.Builder(this, CH).setSmallIcon(R.drawable.ic_note).setContentTitle("김비서와 대화 중")
            .setContentText("PC 의 김비서가 듣고 있어요").setContentIntent(open).setOngoing(true).build()
        try {
            if (Build.VERSION.SDK_INT >= 29) startForeground(NID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE) else startForeground(NID, n)
        } catch (e: Throwable) {
            Bus.line("sys", "마이크 권한이 없어 대화를 시작하지 못했어요.")
            stopSelf(); return START_NOT_STICKY
        }
        ctl.post { if (ws == null) { userStop = false; retry = 0; connect() } }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        me = null
        ctl.post { closeWs("bye"); stopAudio() }
        ctl.looper.quitSafely()
        Bus.post(Bus.Ev.State(false, "대기", micOn))
        super.onDestroy()
    }

    // ---------------------------------------------------------------- 화면에서 부름
    fun stopTalk() = ctl.post { userStop = true; closeWs("bye"); finish("대화를 끝냈어요.") }
    fun sendText(t: String) = ctl.post { send(JSONObject().put("type", "text").put("text", t.take(2000))) }   // 화면 줄은 PC 가 돌려주는 typed 로
    fun setMic(on: Boolean) { micOn = on; Bus.post(Bus.Ev.State(authed, if (on) "듣는 중" else "마이크 꺼짐", on)) }
    fun answer(id: String, ok: Boolean) = ctl.post {
        send(JSONObject().put("type", "confirm_result").put("id", id).put("result", JSONObject().put("ok", ok)))
        Bus.post(Bus.Ev.AskDone(id)); askTimer?.let { ctl.removeCallbacks(it) }
        getSystemService(NotificationManager::class.java).cancel(7)
        Bus.line("sys", if (ok) "실행해요." else "실행하지 않았어요.")
    }
    fun interp(on: Boolean?, lang: String) = ctl.post {
        val o = JSONObject().put("type", "interp").put("lang", lang)
        if (on != null) o.put("on", on)
        send(o)
    }
    fun testFeed(path: String) {
        if (!BuildConfig.TEST_HOOKS) return
        try {
            val b = File(path).readBytes()
            val off = if (b.size > 44 && String(b, 0, 4) == "RIFF") 44 else 0
            val bb = ByteBuffer.wrap(b, off, b.size - off).order(ByteOrder.LITTLE_ENDIAN)
            val all = ShortArray((b.size - off) / 2) { bb.short }
            var i = 0
            while (i < all.size) { feed.offer(all.copyOfRange(i, min(all.size, i + 320))); i += 320 }
            repeat(60) { feed.offer(ShortArray(320)) }   // 말 끝 1.2초 조용
            Bus.line("sys", "시험 소리 %.1f초 넣음".format(all.size / 16000.0))
        } catch (e: Throwable) { Bus.line("sys", "시험 소리를 못 읽었어요: ${e.javaClass.simpleName}") }
    }

    // ---------------------------------------------------------------- 연결
    private fun send(o: JSONObject) { try { ws?.send(o.toString()) } catch (_: Throwable) {} }

    private fun connect() {
        val pc = Store.pc(this)
        if (pc == null) { Bus.line("sys", "먼저 PC 와 연결해 주세요."); finish(null); return }
        Bus.post(Bus.Ev.State(false, "연결 중", micOn))
        val http = Net.client(pc.fp, ws = true).first
        tryHost(pc, http, 0, ++gen)
    }

    private fun tryHost(pc: Store.Pc, http: okhttp3.OkHttpClient, i: Int, g: Int) {
        if (g != gen) return
        if (i >= pc.hosts.size) { lost(null, Net.unreachable(pc.hosts)); return }
        val host = pc.hosts[i]
        var opened = false
        val req = Request.Builder().url(PairRules.baseUrl(host, pc.port, ws = true) + "/phone/ws").build()
        ws = http.newWebSocket(req, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                opened = true
                Store.setLast(this@TalkService, host)
                webSocket.send(JSONObject().put("auth", pc.token).put("device", Net.deviceName())
                    .put("greeting", Store.flag(this@TalkService, "greet", true))
                    .put("navigate", true).put("dial", true).put("sms", true).put("open_app", true).put("confirm", true)
                    .put("app_ver", BuildConfig.VERSION_NAME).toString())
            }
            override fun onMessage(webSocket: WebSocket, text: String) { ctl.post { if (g == gen) onJson(text) } }
            override fun onMessage(webSocket: WebSocket, bytes: ByteString) { if (g == gen) playQ.offer(bytes.toByteArray()) }
            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) { try { webSocket.close(1000, null) } catch (_: Throwable) {} }
            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) { ctl.post { if (g == gen) closed(code) } }
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                ctl.post {
                    if (g != gen) return@post
                    if (!opened) {
                        if (t is javax.net.ssl.SSLException) { lost(null, "PC 인증서가 연결할 때와 달라요. PC 를 바꿨다면 다시 연결해 주세요."); return@post }
                        tryHost(pc, http, i + 1, g)
                    } else closed(-1)
                }
            }
        })
    }

    private fun closeWs(why: String) {
        val w = ws ?: return
        ws = null; gen++
        try { w.send(JSONObject().put("type", "bye").toString()); w.close(1000, why) } catch (_: Throwable) {}
    }

    private fun closed(code: Int) {
        ws = null; gen++
        val was = authed
        authed = false
        stopAudio()
        when {
            userStop -> finish(null)
            code == 4401 -> { Store.clear(this); finish("이 폰의 연결이 PC 에서 지워졌어요. 다시 연결해 주세요.") }
            code == 4403 -> finish("PC 가 이 연결을 받지 않아요. 집 밖이라면 PC 김비서 설정 → 폰 연결 → '테일스케일로도 연결 받기'가 켜져 있는지 확인해 주세요.")
            was && retry < 3 -> {
                retry++
                if (retry == 1) Bus.line("sys", "PC 연결이 끊겨 다시 연결하는 중")
                Bus.post(Bus.Ev.State(false, "다시 연결 중", micOn))
                ctl.postDelayed({ if (ws == null && !userStop) connect() }, longArrayOf(1000, 3000, 6000)[retry - 1])
            }
            else -> finish(if (was) "PC 연결이 끊겼어요." else "PC 에 연결하지 못했어요.")
        }
    }

    private fun lost(t: Throwable?, msg: String) { ws = null; gen++; stopAudio(); finish(msg) }

    private fun finish(msg: String?) {
        if (msg != null) Bus.line("sys", msg)
        Bus.post(Bus.Ev.State(false, "대기", micOn))
        main.post { try { stopForeground(STOP_FOREGROUND_REMOVE) } catch (_: Throwable) {}; stopSelf() }
    }

    private fun onJson(text: String) {
        val m = try { JSONObject(text) } catch (_: Throwable) { return }
        when (m.optString("type")) {
            "auth_ok" -> {
                authed = true; retry = 0
                Bus.post(Bus.Ev.Pc(m))
                Bus.post(Bus.Ev.State(true, if (micOn) "듣는 중" else "마이크 꺼짐", micOn))
                startAudio()
                send(JSONObject().put("type", "interp_get"))
            }
            "auth_fail" -> { userStop = true; Store.clear(this); Bus.line("sys", "이 폰의 연결이 PC 에서 지워졌어요. 다시 연결해 주세요.") }
            "status" -> { val s = m.optString("state"); if (s.isNotEmpty()) Bus.post(Bus.Ev.State(true, s, micOn)) }
            "user", "typed" -> m.optString("text").takeIf { it.isNotBlank() }?.let { Bus.line("me", it) }
            "bot" -> m.optString("text").takeIf { it.isNotBlank() }?.let { Bus.line("bot", it) }
            "brain_error" -> Bus.line("sys", m.optString("text", "김비서 두뇌가 답하지 못했어요."))
            "tool" -> toolLine(m)
            "voice_gate" -> Bus.line("gate", "등록한 목소리가 아니라서 듣지 않았어요" + (m.optString("text").takeIf { it.isNotBlank() }?.let { ": $it" } ?: ""))
            "interp" -> Bus.post(Bus.Ev.Interp(m))
            "clear_audio", "interrupted" -> { playQ.clear(); try { track?.pause(); track?.flush(); track?.play() } catch (_: Throwable) {} }
            "standby" -> { userStop = true; closeWs("standby"); finish("대화를 쉬어요. 다시 말하려면 '대화 시작'을 눌러 주세요.") }
            "kicked" -> { userStop = true; closeWs("kicked"); finish("PC 화면이나 다른 폰에서 대화를 시작해서 여기는 끝났어요.") }
            "confirm" -> ask(m.optString("id"), m.optString("text"))
            "phone_do" -> {
                val id = m.optString("id")
                main.post {
                    val r = Doer(this).run(m)
                    ctl.post { send(JSONObject().put("type", "phone_do_result").put("id", id).put("result", r)) }
                }
            }
        }
    }

    private val TOOLS = mapOf("web_search" to "PC 에서 검색하는 중", "read_page" to "PC 에서 페이지를 읽는 중", "get_weather" to "날씨 보는 중",
        "pc_action" to "PC 에서 여는 중", "type_text" to "PC 메모장에 적는 중", "phone_action" to "폰에서 여는 중")

    private fun toolLine(m: JSONObject) {
        val st = m.optString("state")
        if (st != "start" && st != "") return
        TOOLS[m.optString("name")]?.let { Bus.line("tool", it) }
    }

    /** 위험한 일 '실행할까요?' — 화면 단추(뒤에 있으면 알림으로 화면 열기). PC 가 45초 기다리므로 44초 뒤 단추를 거둠 */
    private fun ask(id: String, text: String) {
        if (id.isEmpty()) return
        Bus.post(Bus.Ev.Ask(id, text))
        if (!Bus.visible) {
            val pi = PendingIntent.getActivity(this, 7, Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
                PendingIntent.FLAG_IMMUTABLE)
            getSystemService(NotificationManager::class.java).notify(7, Notification.Builder(this, "ask").setSmallIcon(R.drawable.ic_note)
                .setContentTitle("실행할까요?").setContentText(text).setContentIntent(pi).setAutoCancel(true).build())
        }
        askTimer?.let { ctl.removeCallbacks(it) }
        val r = Runnable {
            Bus.post(Bus.Ev.AskDone(id)); getSystemService(NotificationManager::class.java).cancel(7)
            Bus.line("sys", "답이 없어 실행하지 않았어요.")
        }
        askTimer = r; ctl.postDelayed(r, 44000)
    }

    // ---------------------------------------------------------------- 소리
    @SuppressLint("MissingPermission")
    private fun startAudio() {
        if (rec != null) return
        val am = getSystemService(AudioManager::class.java)
        try {
            am.mode = AudioManager.MODE_IN_COMMUNICATION
            if (Build.VERSION.SDK_INT >= 31) {
                val devs = am.availableCommunicationDevices
                val head = devs.firstOrNull { it.type in intArrayOf(AudioDeviceInfo.TYPE_WIRED_HEADSET, AudioDeviceInfo.TYPE_BLUETOOTH_SCO,
                    AudioDeviceInfo.TYPE_USB_HEADSET, AudioDeviceInfo.TYPE_BLE_HEADSET) }
                (head ?: devs.firstOrNull { it.type == AudioDeviceInfo.TYPE_BUILTIN_SPEAKER })?.let { am.setCommunicationDevice(it) }
            } else oldSpeaker(am, true)
        } catch (_: Throwable) {}
        val minIn = AudioRecord.getMinBufferSize(16000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val r = try { AudioRecord(MediaRecorder.AudioSource.VOICE_COMMUNICATION, 16000, AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT, max(minIn, 640 * 8)) } catch (_: Throwable) { null }
        if (r == null || r.state != AudioRecord.STATE_INITIALIZED) {
            try { r?.release() } catch (_: Throwable) {}
            Bus.line("sys", "마이크를 열지 못했어요. 글로 대화할 수 있어요.")
        } else {
            try { if (AcousticEchoCanceler.isAvailable()) AcousticEchoCanceler.create(r.audioSessionId)?.enabled = true } catch (_: Throwable) {}
            try { if (NoiseSuppressor.isAvailable()) NoiseSuppressor.create(r.audioSessionId)?.enabled = true } catch (_: Throwable) {}
            rec = r
        }
        val minOut = AudioTrack.getMinBufferSize(24000, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val tb = AudioTrack.Builder()
            .setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION)
                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
            .setAudioFormat(AudioFormat.Builder().setSampleRate(24000).setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                .setEncoding(AudioFormat.ENCODING_PCM_16BIT).build())
            .setBufferSizeInBytes(max(minOut, 24000)).setTransferMode(AudioTrack.MODE_STREAM)
        rec?.let { tb.setSessionId(it.audioSessionId) }
        val tr = try { tb.build().also { it.play() } } catch (_: Throwable) { null }
        track = tr
        playQ.clear()
        val sock = ws
        val mic = rec
        try { mic?.startRecording() } catch (_: Throwable) { Bus.line("sys", "마이크를 열지 못했어요. 글로 대화할 수 있어요.") }
        Thread {   // 마이크 → PC (20ms). 마이크를 끄면 조용한 소리를 보냄(PC 쪽 말 끝 판단이 끊기지 않게)
            val b = ShortArray(320); val bb = ByteBuffer.allocate(640).order(ByteOrder.LITTLE_ENDIAN)
            var lvT = 0L
            try {
                while (ws === sock && sock != null) {
                    val f = if (BuildConfig.TEST_HOOKS) feed.poll() else null
                    if (mic != null && rec === mic) {
                        var g = 0
                        while (g < 320) { val n = mic.read(b, g, 320 - g); if (n <= 0) break; g += n }
                        if (g < 320) { Thread.sleep(10); continue }
                    } else Thread.sleep(20)
                    val src = f ?: b
                    bb.clear()
                    var sum = 0.0
                    if (micOn || f != null) for (v in src) { bb.putShort(v); sum += v.toDouble() * v } else for (i in 0 until 320) bb.putShort(0)
                    sock.send(bb.array().toByteString(0, 640))
                    val now = System.currentTimeMillis()
                    if (now - lvT > 100) { lvT = now; Bus.post(Bus.Ev.Level(min(1f, (sqrt(sum / 320) / 6000).toFloat()))) }
                }
            } catch (_: InterruptedException) {} catch (_: Throwable) {}
        }.apply { name = "kb-mic"; start() }
        if (tr != null) Thread {   // PC → 스피커
            while (track === tr) {
                val d = try { playQ.poll(200, TimeUnit.MILLISECONDS) } catch (_: InterruptedException) { break } ?: continue
                try { tr.write(d, 0, d.size) } catch (_: Throwable) {}
            }
        }.apply { name = "kb-spk"; start() }
    }

    @Suppress("DEPRECATION")
    private fun oldSpeaker(am: AudioManager, on: Boolean) { am.isSpeakerphoneOn = on && !am.isWiredHeadsetOn }

    private fun stopAudio() {
        val r = rec; rec = null
        val t = track; track = null
        try { r?.stop() } catch (_: Throwable) {}
        try { r?.release() } catch (_: Throwable) {}
        try { t?.stop() } catch (_: Throwable) {}
        try { t?.release() } catch (_: Throwable) {}
        playQ.clear(); feed.clear()
        try {
            val am = getSystemService(AudioManager::class.java)
            if (Build.VERSION.SDK_INT >= 31) am.clearCommunicationDevice() else oldSpeaker(am, false)
            am.mode = AudioManager.MODE_NORMAL
        } catch (_: Throwable) {}
    }
}

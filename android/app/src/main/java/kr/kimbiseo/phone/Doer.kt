package kr.kimbiseo.phone

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.provider.ContactsContract
import org.json.JSONArray
import org.json.JSONObject

/**
 * PC 김비서가 보낸 폰 일(phone_do) 하기 — 다른 앱 화면을 '여는' 것까지만.
 *  navigate: 길안내 앱 검색 화면 · dial: 전화 앱에 번호 채우기(걸기는 사용자가) · sms: 문자 앱에 받는 사람·내용 채우기(보내기는 사용자가) · open_app: 앱 열기.
 *  김비서 화면이 앞에 있으면 바로 열고, 뒤에 있으면(안드로이드가 뒤에서 다른 앱 열기를 막음) '눌러서 열기' 알림을 띄운다.
 *  연락처는 이 폰 안에서만 찾고 PC 로는 결과 한 줄(열었음·비슷한 이름)만 보낸다.
 */
class Doer(private val ctx: Context) {
    companion object { const val CH = "open"; private var nid = 100 }

    private fun installed(pkg: String) = try { ctx.packageManager.getPackageInfo(pkg, 0); true } catch (_: Throwable) { false }

    fun run(m: JSONObject): JSONObject = try {
        when (m.optString("do")) {
            "navigate" -> navigate(m.optString("destination").take(80), m.optString("app"))
            "dial", "sms" -> talk(m.optString("do"), m.optString("number"), m.optString("contact"), m.optString("message").take(500))
            "open_app" -> openApp(m.optString("app").take(40))
            else -> res(false, "이 앱이 모르는 일이에요.")
        }
    } catch (e: Throwable) { res(false, "폰에서 열지 못했어요(${e.javaClass.simpleName}).") }

    private fun res(ok: Boolean, said: String) = JSONObject().put("ok", ok).put("말", said)

    /** 앞에 있으면 바로, 아니면 알림. 돌려주는 글은 PC 김비서가 그대로 읽음 */
    private fun open(i: Intent, title: String, done: String): String {
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        if (Bus.visible) {
            ctx.startActivity(i)
            return done
        }
        val nm = ctx.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CH, "다른 앱 열기", NotificationManager.IMPORTANCE_HIGH))
        val id = ++nid
        val pi = PendingIntent.getActivity(ctx, id, i, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        nm.notify(id, Notification.Builder(ctx, CH).setSmallIcon(R.drawable.ic_note).setContentTitle(title)
            .setContentText("눌러서 열기").setContentIntent(pi).setAutoCancel(true).build())
        return "$done 폰 알림을 누르면 열려요."
    }

    private fun navigate(dest: String, app: String): JSONObject {
        if (dest.isEmpty()) return res(false, "목적지가 없어요.")
        val t = NavRules.pick(dest, app, ::installed, ctx.packageName)
        if (t.pkg == NavRules.KAKAONAVI) {
            ctx.getSystemService(ClipboardManager::class.java).setPrimaryClip(ClipData.newPlainText("목적지", dest))
            val li = ctx.packageManager.getLaunchIntentForPackage(t.pkg) ?: return res(false, "카카오내비를 열지 못했어요.")
            return res(true, open(li, "카카오내비: $dest", "카카오내비를 열었어요. ${t.note}."))
        }
        val i = Intent(Intent.ACTION_VIEW, Uri.parse(t.uri))
        if (t.pkg.isNotEmpty()) i.setPackage(t.pkg)
        val note = if (t.note.isNotEmpty()) " ${t.note}." else ""
        Bus.line("sys", "길안내(${t.app}): $dest")
        return res(true, open(i, "길안내: $dest", "${t.app}에서 '$dest'를 열었어요.$note"))
    }

    private fun talk(kind: String, number: String, contact: String, msg: String): JSONObject {
        var num = NameRules.digits(number)
        var who = ""
        if (num.isEmpty()) {
            val q = NameRules.cleanName(contact)
            if (q.isEmpty()) return res(false, "누구에게 할지 이름이 없어요.")
            if (ctx.checkSelfPermission(Manifest.permission.READ_CONTACTS) != PackageManager.PERMISSION_GRANTED) {
                Bus.post(Bus.Ev.NeedPerm(Manifest.permission.READ_CONTACTS, "이름으로 전화·문자 화면을 열려면 연락처 권한이 필요해요"))
                return res(false, "폰에서 연락처 권한을 허용해 주세요. 김비서 앱 화면에 허용 단추가 떠요.")
            }
            val rows = ArrayList<Pair<String, String>>()
            ctx.contentResolver.query(ContactsContract.CommonDataKinds.Phone.CONTENT_URI,
                arrayOf(ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME, ContactsContract.CommonDataKinds.Phone.NUMBER), null, null, null)?.use { c ->
                while (c.moveToNext()) { val n = c.getString(0) ?: continue; val p = c.getString(1) ?: continue; rows.add(Pair(n, p)) }
            }
            val r = NameRules.rank(q, rows)
            if (r.list.size == 1) { who = r.list[0].first; num = NameRules.digits(r.list[0].second) }
            else {
                val cands = (if (r.list.isNotEmpty()) r.list else r.near).map { it.first }.take(3)
                if (cands.isEmpty()) return res(false, "연락처에서 '$q'를 찾지 못했어요.")
                return JSONObject().put("ok", false).put("near", JSONArray(cands)).put("말", "'$q'와 비슷한 이름이 여럿이에요.")
            }
        }
        if (num.length !in 3..15) return res(false, "전화번호 모양이 아니에요.")
        val label = if (who.isNotEmpty()) "$who($num)" else num
        return if (kind == "dial") {
            res(true, open(Intent(Intent.ACTION_DIAL, Uri.fromParts("tel", num, null)), "전화: $label", "$label 번호를 전화 화면에 넣었어요. 통화 단추는 직접 눌러 주세요."))
        } else {
            val i = Intent(Intent.ACTION_SENDTO, Uri.parse("smsto:$num"))
            if (msg.isNotEmpty()) i.putExtra("sms_body", msg)
            res(true, open(i, "문자: $label", "$label 에게 보낼 문자 화면을 열었어요. 보내기는 직접 눌러 주세요."))
        }
    }

    private fun openApp(name: String): JSONObject {
        if (name.isEmpty()) return res(false, "어떤 앱인지 이름이 없어요.")
        val pm = ctx.packageManager
        val acts = pm.queryIntentActivities(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER), 0)
            .filter { it.activityInfo.packageName != ctx.packageName }
        val labels = acts.map { it.loadLabel(pm).toString() }
        val k = AppRules.best(name, labels)
        if (k < 0) return res(false, "폰에서 '$name' 앱을 찾지 못했어요.")
        val ai = acts[k].activityInfo
        val i = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER).setClassName(ai.packageName, ai.name)
        return res(true, open(i, labels[k], "${labels[k]} 앱을 열었어요."))
    }
}

package kr.kimbiseo.phone

import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.text.InputType
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView

/**
 * 화면 재료 — PC 김비서 화면과 같은 차분한 흑연색 바탕 + 분홍 한 가지(주요 단추·선택·듣는 중 표시에만).
 *  간격은 4dp 단위, 글자 무게 400/500, 모서리 단추 10 · 카드 14.
 */
object Ui {
    const val BG = 0xFF141415.toInt()
    const val CARD = 0xFF1B1B1D.toInt()
    const val RAISED = 0xFF252527.toInt()
    const val LINE = 0x17EDEDED            // 글자색 9%
    const val TEXT = 0xFFEDEDED.toInt()
    const val TEXT2 = 0xFFA1A1A6.toInt()
    const val MUTED = 0xFF8A8A90.toInt()
    const val ACCENT = 0xFFFF005A.toInt()  // 분홍 — 점·선택 테두리·소리 막대
    const val ACCENT_FILL = 0xFFD1004A.toInt()  // 흰 글자를 얹을 때(대비 5:1 이상)
    const val OK = 0xFF4CC38A.toInt()
    const val BAD = 0xFFE5484D.toInt()

    fun dp(c: Context, v: Int) = (v * c.resources.displayMetrics.density + 0.5f).toInt()

    fun bg(color: Int, radius: Int, c: Context, stroke: Int = 0, strokeColor: Int = LINE) = GradientDrawable().apply {
        setColor(color); cornerRadius = dp(c, radius).toFloat()
        if (stroke > 0) setStroke(dp(c, stroke), strokeColor)
    }

    fun text(c: Context, s: CharSequence, size: Float = 15f, color: Int = TEXT, medium: Boolean = false): TextView = TextView(c).apply {
        text = s; setTextSize(TypedValue.COMPLEX_UNIT_SP, size); setTextColor(color)
        typeface = if (medium) Typeface.create("sans-serif-medium", Typeface.NORMAL) else Typeface.create("sans-serif", Typeface.NORMAL)
        setLineSpacing(0f, 1.3f)
    }

    fun mono(c: Context, s: CharSequence, size: Float = 15f, color: Int = TEXT): TextView = text(c, s, size, color).apply {
        typeface = Typeface.MONOSPACE; fontFeatureSettings = "tnum"
    }

    enum class Kind { PRIMARY, SECONDARY, QUIET, DANGER }

    fun button(c: Context, label: String, kind: Kind = Kind.SECONDARY, onClick: () -> Unit): Button = Button(c).apply {
        text = label; isAllCaps = false; stateListAnimator = null
        setTextSize(TypedValue.COMPLEX_UNIT_SP, 15f)
        typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
        minHeight = dp(c, 48); minimumHeight = dp(c, 48); minWidth = 0; minimumWidth = 0
        setPadding(dp(c, 20), 0, dp(c, 20), 0)
        val (fill, fg, stroke) = when (kind) {
            Kind.PRIMARY -> Triple(ACCENT_FILL, Color.WHITE, 0)
            Kind.SECONDARY -> Triple(RAISED, TEXT, 1)
            Kind.QUIET -> Triple(Color.TRANSPARENT, TEXT2, 0)
            Kind.DANGER -> Triple(RAISED, BAD, 1)
        }
        setTextColor(fg)
        background = RippleDrawable(ColorStateList.valueOf(0x22FFFFFF), bg(fill, 10, c, stroke), bg(Color.WHITE, 10, c))
        setOnClickListener { onClick() }
    }

    fun field(c: Context, hint: String, digits: Boolean = false, value: String = ""): EditText = EditText(c).apply {
        this.hint = hint; setText(value); setTextColor(TEXT); setHintTextColor(MUTED); setTextSize(TypedValue.COMPLEX_UNIT_SP, 16f)
        background = bg(RAISED, 10, c, 1); setPadding(dp(c, 12), dp(c, 12), dp(c, 12), dp(c, 12))
        inputType = if (digits) InputType.TYPE_CLASS_NUMBER else InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
        isSingleLine = true
    }

    fun col(c: Context, gap: Int = 0): LinearLayout = LinearLayout(c).apply {
        orientation = LinearLayout.VERTICAL
        if (gap > 0) { showDividers = LinearLayout.SHOW_DIVIDER_MIDDLE; dividerDrawable = GradientDrawable().apply { setSize(1, dp(c, gap)) } }
    }

    fun row(c: Context, gap: Int = 0): LinearLayout = LinearLayout(c).apply {
        orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
        if (gap > 0) { showDividers = LinearLayout.SHOW_DIVIDER_MIDDLE; dividerDrawable = GradientDrawable().apply { setSize(dp(c, gap), 1) } }
    }

    fun card(c: Context, gap: Int = 12): LinearLayout = col(c, gap).apply {
        background = bg(CARD, 14, c, 1); setPadding(dp(c, 16), dp(c, 16), dp(c, 16), dp(c, 16))
    }

    /** 연결 상태 점(이 앱의 표시 — 연결됨 초록 · 듣는 중 분홍 · 대기 회색) */
    fun dot(c: Context, color: Int): View = View(c).apply {
        background = GradientDrawable().apply { shape = GradientDrawable.OVAL; setColor(color) }
        layoutParams = LinearLayout.LayoutParams(dp(c, 8), dp(c, 8))
    }

    fun lp(w: Int = LinearLayout.LayoutParams.MATCH_PARENT, h: Int = LinearLayout.LayoutParams.WRAP_CONTENT, weight: Float = 0f) =
        LinearLayout.LayoutParams(w, h, weight)
}

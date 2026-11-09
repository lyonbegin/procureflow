package com.hitel.chatrelay

import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

class MainActivity : Activity() {
    private lateinit var statusView: TextView
    private val uiHandler = Handler(Looper.getMainLooper())
    private val statusUpdate = object : Runnable {
        override fun run() {
            if (::statusView.isInitialized) {
                val prefs = getSharedPreferences("relay", MODE_PRIVATE)
                val enabled = Settings.Secure.getString(contentResolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES)
                    ?.contains("com.hitel.chatrelay", ignoreCase = true) == true
                val service = ChatRelayService.instance != null
                val socket = prefs.getString("socket_state", "연결 기록 없음")
                val reason = prefs.getString("socket_error", "")
                statusView.text = "접근성 설정: ${if (enabled) "활성" else "비활성"}\n" +
                    "접근성 서비스: ${if (service) "실행 중" else "실행 안 됨"}\n" +
                    "WebSocket: $socket\n" +
                    "최근 오류: ${if (reason.isNullOrEmpty()) "없음" else reason}"
            }
            uiHandler.postDelayed(this, 1000)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val prefs = getSharedPreferences("relay", MODE_PRIVATE)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(36, 42, 36, 36)
            setBackgroundColor(Color.WHITE)
        }
        fun label(value: String) = TextView(this).apply {
            text = value
            textSize = 16f
            setTextColor(Color.DKGRAY)
            setPadding(0, 12, 0, 8)
        }
        fun button(value: String, onClick: () -> Unit) = Button(this).apply {
            text = value
            setOnClickListener { onClick() }
        }
        val url = EditText(this).apply {
            setSingleLine()
            hint = "wss://...up.railway.app/ws"
            setText(prefs.getString("url", "").orEmpty().ifBlank { "wss://chatgpt-relay-web-production.up.railway.app/ws" })
        }
        val token = EditText(this).apply {
            setSingleLine()
            hint = "DEVICE_TOKEN"
            inputType = android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_VARIATION_PASSWORD
            setText(prefs.getString("token", "").orEmpty().ifBlank { "dpYZLhnMxOq02PNKGtTnBvzNSBAkLQ2Ip8zTzbEn" })
        }
        root.addView(label("ChatGPT 원격 제어 앱 · 연결 진단"))
        root.addView(label("Railway WebSocket 주소"))
        root.addView(url, ViewGroup.LayoutParams(-1, -2))
        root.addView(label("Android 전용 DEVICE_TOKEN"))
        root.addView(token, ViewGroup.LayoutParams(-1, -2))
        root.addView(button("설정 저장 및 다시 연결") {
            val address = url.text.toString().trim()
            val tokenValue = token.text.toString().trim()
            if (!address.startsWith("wss://") || !address.endsWith("/ws")) {
                url.error = "wss://.../ws 형태로 입력하십시오"
                return@button
            }
            if (tokenValue.length < 12) {
                token.error = "토큰을 확인하십시오"
                return@button
            }
            prefs.edit().putString("url", address).putString("token", tokenValue).apply()
            if (ChatRelayService.instance == null) {
                android.widget.Toast.makeText(this, "접근성 서비스를 먼저 켜주십시오", android.widget.Toast.LENGTH_LONG).show()
            } else {
                ChatRelayService.instance?.connectFromPrefs()
            }
        })
        root.addView(button("접근성 서비스 설정 열기") {
            startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
        })
        root.addView(button("공식 ChatGPT 실행") {
            val intent = packageManager.getLaunchIntentForPackage("com.openai.chatgpt")
            if (intent == null) {
                android.widget.Toast.makeText(this, "공식 ChatGPT 설치가 필요합니다", android.widget.Toast.LENGTH_LONG).show()
            } else startActivity(intent)
        })
        root.addView(label("연결 상태 (1초마다 갱신)"))
        statusView = label("진단 시작 중")
        root.addView(statusView)
        root.addView(label("인증 성공이면 웹에 'Android 연결됨'이 표시됩니다. 미연결이면 접근성 설정과 최근 오류를 확인하십시오."))
        val scroll = ScrollView(this).apply { addView(root) }
        setContentView(scroll)
    }

    override fun onResume() {
        super.onResume()
        uiHandler.removeCallbacks(statusUpdate)
        uiHandler.post(statusUpdate)
    }
    override fun onPause() {
        uiHandler.removeCallbacks(statusUpdate)
        super.onPause()
    }
}

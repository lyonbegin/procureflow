package com.hitel.chatrelay

import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.widget.Button
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
                android.util.Log.i("HITELRelayStatus",
                    "status pid="+android.os.Process.myPid()+
                    " accessibilityEnabled="+enabled+" serviceInstance="+service)
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
        // The AccessibilityService connects automatically in onServiceConnected().
        // No DEVICE_TOKEN, address entry, pairing code or setup-save step on Android.
        root.addView(label("ChatGPT 릴레이 · 자동 연결"))
        root.addView(label("접근성 서비스를 활성화하면 기존 Railway 서버에 자동 연결됩니다."))
        root.addView(button("연결 다시 시도") {
            val service = ChatRelayService.instance
            if (service == null) {
                android.widget.Toast.makeText(this,
                    "접근성 서비스를 먼저 활성화해 주십시오",
                    android.widget.Toast.LENGTH_LONG).show()
                startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
            } else {
                service.connectFromPrefs()
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
        root.addView(label("서버 연결에 성공하면 기존 웹페이지에 'Android 연결됨'이 표시됩니다. 별도의 기기 토큰 입력은 필요하지 않습니다."))
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

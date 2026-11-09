package com.hitel.chatrelay

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.provider.Settings
import android.graphics.Color
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView

class MainActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val prefs = getSharedPreferences("relay", MODE_PRIVATE)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(36, 50, 36, 32)
            setBackgroundColor(Color.WHITE)
        }
        fun label(text: String) = TextView(this).apply { this.text = text; textSize = 16f; setTextColor(Color.DKGRAY); setPadding(0, 12, 0, 8) }
        fun button(text: String, onClick: () -> Unit) = Button(this).apply { this.text=text; setOnClickListener { onClick() } }
        val url = EditText(this).apply { setSingleLine(); hint="wss://...up.railway.app/ws"; setText(prefs.getString("url", "")) }
        val token = EditText(this).apply { setSingleLine(); hint="DEVICE_TOKEN"; inputType=129; setText(prefs.getString("token", "")) }
        root.addView(label("ChatGPT 원격 제어 앱"))
        root.addView(label("Railway WebSocket 주소")); root.addView(url, ViewGroup.LayoutParams(-1,-2))
        root.addView(label("안드로이드 전용 비밀 토큰")); root.addView(token, ViewGroup.LayoutParams(-1,-2))
        root.addView(button("설정 저장 / 소켓 재연결") {
            val address = url.text.toString().trim()
            if (!address.startsWith("wss://") || !address.endsWith("/ws")) { url.error="wss://.../ws 형식이 필요합니다"; return@button }
            if (token.text.toString().length < 12) { token.error="토큰 길이를 확인하십시오"; return@button }
            prefs.edit().putString("url",address).putString("token", token.text.toString()).apply()
            ChatRelayService.instance?.connectFromPrefs()
        })
        root.addView(button("안드로이드 접근성 설정 열기") { startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)) })
        root.addView(button("공식 ChatGPT 실행") {
            val intent = packageManager.getLaunchIntentForPackage("com.openai.chatgpt")
            if (intent == null) {
                android.widget.Toast.makeText(this,"공식 ChatGPT 설치가 필요합니다",android.widget.Toast.LENGTH_LONG).show()
            } else startActivity(intent)
        })
        root.addView(label("① URL/토큰 설정 → ② 접근성 서비스 활성화 → ③ 공식 ChatGPT 로그인 → ④ Railway 웹에서 전송"))
        setContentView(root)
    }
}

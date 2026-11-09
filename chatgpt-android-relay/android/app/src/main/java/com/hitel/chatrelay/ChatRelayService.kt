package com.hitel.chatrelay

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.Intent
import android.graphics.Rect
import android.graphics.Path
import android.os.Bundle
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

class ChatRelayService : AccessibilityService() {
    companion object { @Volatile var instance: ChatRelayService? = null }
    private val main = Handler(Looper.getMainLooper())
    private val client = OkHttpClient.Builder().pingInterval(20, TimeUnit.SECONDS).build()
    private var socket: WebSocket? = null
    private var active = false
    private var pendingSendId: String? = null
    private var lastSnapshot = 0L
    private var generation = 0
    private val chatPackage = "com.openai.chatgpt"

    override fun onServiceConnected() {
        super.onServiceConnected()
        active = true
        instance = this
        setConnectionState("접근성 서비스 실행 중 · 소켓 연결 준비")
        connectFromPrefs()
    }

    private fun setConnectionState(value: String, error: String = "") {
        getSharedPreferences("relay", MODE_PRIVATE).edit()
            .putString("socket_state", value)
            .putString("socket_error", error.take(300)).apply()
    }

    fun connectFromPrefs() {
        generation++
        val g = generation
        socket?.close(1000, "Reconnect")
        socket = null
        val prefs = getSharedPreferences("relay", MODE_PRIVATE)
        val url = prefs.getString("url", "") ?: ""
        val token = prefs.getString("token", "") ?: ""
        if (!url.startsWith("wss://") || !url.endsWith("/ws") || token.length < 12) {
            setConnectionState("설정 미완료", "WebSocket URL 또는 Android 토큰이 없습니다")
            return
        }
        setConnectionState("WebSocket 연결 시도 중")
        val request = Request.Builder().url(url).build()
        socket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                if (g != generation) return
                setConnectionState("WebSocket 개설됨 · 서버 인증 대기")
                webSocket.send(JSONObject().put("type", "auth")
                    .put("role", "device").put("deviceId", "android-main")
                    .put("token", token).toString())
            }
            override fun onMessage(webSocket: WebSocket, text: String) {
                if (g != generation) return
                try {
                    val data = JSONObject(text)
                    when (data.optString("type")) {
                        "auth.ok" -> setConnectionState("연결 성공 · Android 인증 완료")
                        "auth.error" -> {
                            setConnectionState("인증 실패", data.optString("reason", "TOKEN 오류"))
                            webSocket.close(1000, "Auth rejected")
                        }
                        "command" -> main.post { performCommand(data) }
                        else -> { }
                    }
                } catch(e: Exception) {
                    setConnectionState("응답 해석 실패", e.message ?: e.javaClass.simpleName)
                }
            }
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                if (g == generation) {
                    setConnectionState("소켓 연결 실패 · 재연결 예정", "${t.javaClass.simpleName}: ${t.message ?: ""}")
                    scheduleReconnect(g)
                }
            }
            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                if (g == generation) {
                    if (reason == "Auth rejected") return
                    setConnectionState("소켓 종료 · 재연결 예정", "종료 코드 $code: $reason")
                    scheduleReconnect(g)
                }
            }
        })
    }

    private fun scheduleReconnect(g: Int) {
        main.postDelayed({ if(active && g==generation) connectFromPrefs() }, 5000)
    }

    private fun send(packet: JSONObject) { socket?.send(packet.toString()) }
    private fun sendLog(msg:String) { send(JSONObject().put("type","device.log").put("message",msg.take(500))) }
    private fun done(id: String, ok: Boolean, detail: String) {
        val data=JSONObject().put("type",if(ok) "command.result" else "command.error").put("id",id)
        if(ok) data.put("result",JSONObject().put("ok",true).put("stage",detail)) else data.put("reason",detail)
        send(data)
    }

    private fun performCommand(cmd: JSONObject) {
        val id=cmd.optString("id")
        val action=cmd.optString("action")
        val payload=cmd.optJSONObject("payload") ?: JSONObject()
        if(action=="ui.snapshot") { snapshot(); done(id,true,"snapshot_sent"); return }
        if(action=="ui.back") {
            if(rootInActiveWindow?.packageName?.toString()!=chatPackage) { done(id,false,"ChatGPT not foreground"); return }
            done(id,performGlobalAction(GLOBAL_ACTION_BACK),"back_requested"); return
        }
        withChatApp(id) {
            when(action) {
                "chat.send" -> sendChat(id,payload.optString("text"))
                "chat.new" -> clickNamed(id,listOf("new chat","new conversation","새 채팅","새 대화"))
                "chat.stop" -> clickNamed(id,listOf("stop generating","stop response","생성 중지","응답 중지"))
                else -> done(id,false,"Unsupported action")
            }
        }
    }

    private fun withChatApp(id: String, work: () -> Unit) {
        if(rootInActiveWindow?.packageName?.toString()==chatPackage) { work(); return }
        val intent=packageManager.getLaunchIntentForPackage(chatPackage)
        if(intent==null) { done(id,false,"Official ChatGPT is not installed"); return }
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        startActivity(intent)
        fun waitForApp(n: Int) {
            if(rootInActiveWindow?.packageName?.toString()==chatPackage) work()
            else if(n>18) done(id,false,"ChatGPT foreground timeout")
            else main.postDelayed({waitForApp(n+1)},500)
        }
        main.postDelayed({waitForApp(0)},700)
    }

    private fun nodes(root: AccessibilityNodeInfo?): List<AccessibilityNodeInfo> {
        if(root==null) return emptyList()
        val output=ArrayList<AccessibilityNodeInfo>()
        val queue=ArrayDeque<AccessibilityNodeInfo>()
        queue.add(root)
        while(queue.isNotEmpty() && output.size<250) {
            val next=queue.removeFirst()
            output.add(next)
            for(i in 0 until next.childCount) { next.getChild(i)?.let { queue.addLast(it) } }
        }
        return output
    }

    // Both the web submit button and Enter use chat.send. The Android side must
    // resolve the icon in the *current* ChatGPT view, not inject a keyboard key
    // or rely on an English contentDescription that may be absent.
    private fun sendChat(id: String, text: String) {
        if (pendingSendId != null) {
            done(id, false, "Another message is still being submitted")
            return
        }
        if (text.isBlank()) { done(id, false, "Empty input"); return }
        val root = rootInActiveWindow
        if (root?.packageName?.toString() != chatPackage) {
            done(id, false, "ChatGPT window not active")
            return
        }
        val input = composerInput(nodes(root))
        if (input == null) {
            done(id, false, "ChatGPT editable composer not found")
            snapshot()
            return
        }
        pendingSendId = id
        input.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
        val args = Bundle().apply {
            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text)
        }
        if (!input.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)) {
            pendingSendId = null
            done(id, false, "ACTION_SET_TEXT failed")
            return
        }
        sendLog("Composer text inserted; resolving actual ChatGPT submit action")
        main.postDelayed({ submitAfterText(id, text, 0) }, 350)
    }

    private fun composerInput(all: List<AccessibilityNodeInfo>): AccessibilityNodeInfo? {
        return all.filter { it.isEditable && it.isVisibleToUser && it.isEnabled }
            .maxByOrNull { n -> Rect().also { n.getBoundsInScreen(it) }.bottom }
    }

    private fun isClickTarget(n: AccessibilityNodeInfo): Boolean {
        return n.isVisibleToUser && n.isEnabled &&
            (n.isClickable || n.actionList.any { it.id == AccessibilityNodeInfo.ACTION_CLICK })
    }

    private fun accessibleLabel(n: AccessibilityNodeInfo): String {
        return listOf(
            n.contentDescription?.toString() ?: "",
            n.viewIdResourceName ?: "",
            n.text?.toString() ?: "",
            n.actionList.mapNotNull { it.label?.toString() }.joinToString(" ")
        ).joinToString(" ").lowercase()
    }

    private fun findSendTarget(
        all: List<AccessibilityNodeInfo>,
        input: AccessibilityNodeInfo
    ): Pair<AccessibilityNodeInfo, String>? {
        val ir = Rect().also { input.getBoundsInScreen(it) }
        val dp = resources.displayMetrics.density
        val exclusion = listOf("voice", "microphone", "record", "attach", "photo", "camera",
            "stop", "cancel", "close", "back", "dictate", "음성", "녹음", "마이크", "첨부", "취소", "중지")
        fun valid(n: AccessibilityNodeInfo): Boolean {
            val r = Rect().also { n.getBoundsInScreen(it) }
            return isClickTarget(n) && r.width() > 0 && r.height() > 0 &&
                r.bottom >= ir.top - (95 * dp).toInt()
        }
        fun distance(n: AccessibilityNodeInfo): Int {
            val r = Rect().also { n.getBoundsInScreen(it) }
            return kotlin.math.abs(r.centerX() - ir.right) +
                kotlin.math.abs(r.centerY() - ir.bottom)
        }

        // Search labels, resource IDs, and custom action labels, then select
        // the clickable ancestor. Prefer the control adjacent to the composer.
        val named = ArrayList<AccessibilityNodeInfo>()
        for (n in all) {
            val label = accessibleLabel(n)
            if (exclusion.any { label.contains(it) }) continue
            if (listOf("send", "submit", "전송", "보내기", "전달").none { label.contains(it) }) continue
            var clickable: AccessibilityNodeInfo? = n
            var depth = 0
            while (clickable != null && !isClickTarget(clickable) && depth < 4) {
                clickable = clickable.parent
                depth++
            }
            if (clickable != null && valid(clickable)) named.add(clickable)
        }
        val explicit = named.minByOrNull { distance(it) }
        if (explicit != null) return Pair(explicit, "named_or_resource_id")

        // Compose interfaces may publish an icon without a contentDescription.
        // Restrict the fallback to a small, enabled clickable control directly
        // right of and overlapping the bottom of the known input field.
        val nearby = all.filter { n ->
            if (!valid(n) || n.isEditable) return@filter false
            val label = accessibleLabel(n)
            if (exclusion.any { label.contains(it) }) return@filter false
            val r = Rect().also { n.getBoundsInScreen(it) }
            val maxSize = (100 * dp).toInt()
            val nearX = r.centerX() >= ir.right - (140 * dp).toInt() &&
                r.centerX() <= ir.right + (50 * dp).toInt()
            val nearY = r.centerY() >= ir.top - (16 * dp).toInt() &&
                r.centerY() <= ir.bottom + (45 * dp).toInt()
            nearX && nearY && r.width() <= maxSize && r.height() <= maxSize
        }.sortedBy { distance(it) }
        // Do not guess at an ambiguous icon. It might be voice/microphone.
        if (nearby.size == 1) return Pair(nearby.first(), "single_composer_adjacent_icon")
        return null
    }

    private fun submitAfterText(id: String, text: String, attempt: Int) {
        if (pendingSendId != id) return
        val root = rootInActiveWindow
        if (root?.packageName?.toString() != chatPackage) {
            finishSend(id, false, "ChatGPT foreground lost before submit")
            return
        }
        val all = nodes(root)
        val input = composerInput(all)
        if (input == null) {
            if (attempt < 7) main.postDelayed({ submitAfterText(id, text, attempt + 1) }, 300)
            else finishSend(id, false, "Composer unavailable after text insertion")
            return
        }
        val current = input.text?.toString()?.trim() ?: ""
        if (current.isEmpty()) {
            if (attempt < 7) main.postDelayed({ submitAfterText(id, text, attempt + 1) }, 300)
            else finishSend(id, false, "Composer text disappeared before submit; verify manually")
            return
        }
        val candidate = findSendTarget(all, input)
        if (candidate != null) {
            val target = candidate.first
            sendLog("Submit target: " + candidate.second + ", node=" +
                (target.viewIdResourceName ?: "(no-id)") +
                ", desc=" + (target.contentDescription ?: "(no-desc)"))
            if (target.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
                main.postDelayed({ verifySubmission(id, text, 0, candidate.second) }, 450)
                return
            }
            val bounds = Rect().also { target.getBoundsInScreen(it) }
            if (!bounds.isEmpty) {
                val path = Path().apply {
                    moveTo(bounds.exactCenterX(), bounds.exactCenterY())
                }
                val gesture = GestureDescription.Builder()
                    .addStroke(GestureDescription.StrokeDescription(path, 0, 80))
                    .build()
                val requested = dispatchGesture(gesture, object : GestureResultCallback() {
                    override fun onCompleted(gestureDescription: GestureDescription) {
                        main.postDelayed({
                            verifySubmission(id, text, 0, "gesture_" + candidate.second)
                        }, 450)
                    }
                    override fun onCancelled(gestureDescription: GestureDescription) {
                        finishSend(id, false, "Gesture was cancelled; text remains in composer")
                    }
                }, main)
                if (requested) return
            }
            finishSend(id, false, "Clickable send target rejected ACTION_CLICK and gesture")
            return
        }
        if (attempt < 5) {
            main.postDelayed({ submitAfterText(id, text, attempt + 1) }, 350)
            return
        }
        // The IME action works ONLY when the focused editable node exposes it.
        // On multiline chat boxes ordinary Enter may add a newline, so never
        // inject raw key events or an implicit keyboard gesture.
        if (Build.VERSION.SDK_INT >= 30 &&
            input.actionList.any {
                it.id == AccessibilityNodeInfo.AccessibilityAction.ACTION_IME_ENTER.id
            } &&
            input.performAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_IME_ENTER.id)
        ) {
            sendLog("No send icon: explicitly offered ACTION_IME_ENTER requested")
            main.postDelayed({ verifySubmission(id, text, 0, "ime_enter") }, 450)
            return
        }
        sendNodeDiagnostics(all, input)
        finishSend(id, false, "Send control not identified; text entered but NOT sent")
    }

    private fun verifySubmission(id: String, text: String, attempt: Int, method: String) {
        if (pendingSendId != id) return
        val root = rootInActiveWindow
        if (root?.packageName?.toString() == chatPackage) {
            val input = composerInput(nodes(root))
            val actual = input?.text?.toString()?.trim() ?: ""
            // This is observable evidence that the composer cleared after the
            // submit action. performAction returning true alone is insufficient.
            if (input != null && actual.isBlank()) {
                finishSend(id, true, "send_confirmed_composer_cleared_via_" + method)
                main.postDelayed({ snapshot() }, 700)
                return
            }
        }
        if (attempt < 10) {
            main.postDelayed({ verifySubmission(id, text, attempt + 1, method) }, 350)
        } else {
            sendLog("Unverified submit: composer did not clear after " + method)
            finishSend(id, false, "Send action was attempted but message transmission NOT VERIFIED")
            snapshot()
        }
    }

    private fun sendNodeDiagnostics(
        all: List<AccessibilityNodeInfo>,
        input: AccessibilityNodeInfo
    ) {
        val ir = Rect().also { input.getBoundsInScreen(it) }
        val dp = resources.displayMetrics.density
        all.filter { isClickTarget(it) }.filter {
            val r = Rect().also { r -> it.getBoundsInScreen(r) }
            r.bottom > ir.top - (125 * dp).toInt()
        }.takeLast(18).forEach { n ->
            val r = Rect().also { n.getBoundsInScreen(it) }
            sendLog("Composer-near candidate bounds=" + r.toShortString() +
                ", id=" + (n.viewIdResourceName ?: "-") +
                ", desc=" + (n.contentDescription ?: "-") +
                ", class=" + (n.className ?: "-"))
        }
        snapshot()
    }

    private fun finishSend(id: String, ok: Boolean, reason: String) {
        if (pendingSendId != id) return
        pendingSendId = null
        done(id, ok, reason)
    }

    private fun clickNamed(id: String, names: List<String>) {
        val match=nodes(rootInActiveWindow).firstOrNull { n ->
            n.isVisibleToUser && n.isClickable && names.any { word ->
                ((n.text?.toString() ?: "")+" "+(n.contentDescription?.toString() ?: "")).lowercase().contains(word)
            }
        }
        if(match==null) { done(id,false,"Button not identified: ${names.first()}"); snapshot(); return }
        done(id,match.performAction(AccessibilityNodeInfo.ACTION_CLICK),"button_click_requested")
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if(event?.packageName?.toString()!=chatPackage) return
        val now=System.currentTimeMillis()
        if(now-lastSnapshot<800) return
        lastSnapshot=now
        main.postDelayed({snapshot()},350)
    }

    private fun snapshot() {
        val root=rootInActiveWindow ?: return
        if(root.packageName?.toString()!=chatPackage) return
        val listing=JSONArray()
        for(n in nodes(root)) {
            val text=n.text?.toString()?.take(700) ?: ""
            val desc=n.contentDescription?.toString()?.take(300) ?: ""
            if(text.isEmpty() && desc.isEmpty()) continue
            listing.put(JSONObject().put("text",text).put("desc",desc).put("id",n.viewIdResourceName ?: "").put("editable",n.isEditable).put("clickable",n.isClickable))
            if(listing.length()>=130) break
        }
        send(JSONObject().put("type","ui.snapshot").put("nodes",listing))
    }

    override fun onInterrupt() {}
    override fun onDestroy() {
        active=false
        generation++
        socket?.close(1000,"Service ended")
        socket=null
        instance=null
        setConnectionState("접근성 서비스 종료됨", "안드로이드 설정에서 접근성을 다시 확인하십시오")
        super.onDestroy()
    }
}

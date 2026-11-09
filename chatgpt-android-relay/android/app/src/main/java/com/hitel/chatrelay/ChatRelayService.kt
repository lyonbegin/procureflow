package com.hitel.chatrelay

import android.accessibilityservice.AccessibilityService
import android.content.Intent
import android.graphics.Rect
import android.os.Bundle
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
    private var lastSnapshot = 0L
    private var generation = 0
    private val chatPackage = "com.openai.chatgpt"

    override fun onServiceConnected() {
        super.onServiceConnected()
        active = true
        instance = this
        connectFromPrefs()
    }

    fun connectFromPrefs() {
        generation++
        val g = generation
        socket?.close(1000, "Reconnect")
        socket = null
        val prefs = getSharedPreferences("relay", MODE_PRIVATE)
        val url = prefs.getString("url", "") ?: ""
        val token = prefs.getString("token", "") ?: ""
        if (!url.startsWith("wss://") || !url.endsWith("/ws") || token.length < 12) return
        val request = Request.Builder().url(url).build()
        socket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                webSocket.send(JSONObject().put("type","auth").put("role","device").put("deviceId","android-main").put("token",token).toString())
            }
            override fun onMessage(webSocket: WebSocket, text: String) {
                try {
                    val data=JSONObject(text)
                    if (data.optString("type")=="command") main.post { performCommand(data) }
                } catch(e: Exception) { sendLog("Bad server message: ${e.javaClass.simpleName}") }
            }
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) { scheduleReconnect(g) }
            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) { scheduleReconnect(g) }
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

    private fun sendChat(id: String, text: String) {
        if(text.isBlank()) { done(id,false,"Empty input"); return }
        val all=nodes(rootInActiveWindow)
        val inputs=all.filter { it.isEditable && it.isVisibleToUser }
        val input=inputs.maxByOrNull { n -> Rect().also { n.getBoundsInScreen(it) }.bottom }
        if(input==null) { done(id,false,"ChatGPT input field not found; request ui.snapshot"); snapshot(); return }
        val args=Bundle().apply { putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,text) }
        if(!input.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT,args)) { done(id,false,"ACTION_SET_TEXT failed"); return }
        main.postDelayed({
            val candidates=nodes(rootInActiveWindow).filter { n ->
                n.isVisibleToUser && n.isClickable &&
                listOf("send","submit","전송","보내기").any { word ->
                    ((n.contentDescription?.toString() ?: "")+" "+(n.text?.toString() ?: "")).lowercase().contains(word)
                }
            }
            val sendBtn=candidates.lastOrNull()
            if(sendBtn==null) { done(id,false,"Send button not identified; text entered but NOT sent"); snapshot(); return@postDelayed }
            val clicked=sendBtn.performAction(AccessibilityNodeInfo.ACTION_CLICK)
            done(id,clicked,if(clicked) "send_button_click_requested" else "Send button click failed")
            main.postDelayed({snapshot()},1100)
        },450)
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
        super.onDestroy()
    }
}

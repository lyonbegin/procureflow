package com.hitel.chatrelay

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.Intent
import android.content.ClipData
import android.content.ContentValues
import android.os.Environment
import android.provider.MediaStore
import android.net.Uri
import androidx.core.content.FileProvider
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
import java.io.File
import java.security.MessageDigest
import kotlin.concurrent.thread

class ChatRelayService : AccessibilityService() {
    companion object { @Volatile var instance: ChatRelayService? = null }
    private val main = Handler(Looper.getMainLooper())
    private val client = OkHttpClient.Builder().pingInterval(20, TimeUnit.SECONDS).build()
    private var socket: WebSocket? = null
    private var active = false
    private var pendingSendId: String? = null
    private var activeApiJob: JSONObject? = null
    private var currentRoomId: String? = null
    // Process-local identity of the last ChatGPT conversation navigated by
    // the relay. Never persist across service restarts as a confirmed screen.
    private var activeConversationId: String? = null
    private var identityGeneration: Long = 0L
    private var routedIdentityGeneration: Long = -1L
    private var deepLinkRoutedJobId: String? = null
    private var roomLastPrompt: String = ""
    private data class StagedAttachment(
        val id: String, val name: String, val mime: String, val file: File,
        val uri: Uri
    )
    private var shareAttachmentCount = 0
    private var shareRoomAnchor = ""
    private var sharePreviewsBefore = 0
    private var pendingPickerDisplayName: String? = null
    private var pendingPickerUri: Uri? = null
    private val pendingPickerCleanup = ArrayList<Uri>()
    private val chrome = setOf("메뉴","새 채팅","메뉴 편집","ChatGPT에게 답변하기","복사","소리 내어 읽기",
        "공유","추가 작업","좋아요","별로예요","음성 대화 시작","첨부파일","받아쓰기",
        "ChatGPT","Copy","Share","Read aloud","New chat","Menu","Regenerate",
        "Voice mode","Attach files")
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
        val url = prefs.getString("url", "").orEmpty().ifBlank { "wss://chatgpt-relay-web-production.up.railway.app/ws" }
        val token = prefs.getString("token", "").orEmpty()
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
                        "job" -> {
                            val job = data.optJSONObject("job")
                            if (job != null) main.post {
                                try { receiveApiJob(job) }
                                catch (e: Exception) {
                                    finishApiJob(job.optString("id"), false, "Android job exception: " + e.javaClass.simpleName + ": " + (e.message ?: ""))
                                }
                            }
                        }
                        "command" -> {
                            val cmdId = data.optString("id")
                            webSocket.send(JSONObject().put("type", "command.received")
                                .put("id", cmdId).put("stage", "Android 소켓 수신").toString())
                            main.post {
                                try {
                                    progress(cmdId, "Android 접근성 명령 실행 시작")
                                    performCommand(data)
                                } catch (e: Exception) {
                                    pendingSendId = null
                                    done(cmdId, false, "Accessibility execution exception: ${e.javaClass.simpleName}: ${e.message ?: ""}")
                                }
                            }
                        }
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
    private fun progress(id: String, stage: String) {
        if (activeApiJob?.optString("id") == id) {
            send(JSONObject().put("type", "job.progress").put("job_id", id).put("stage", stage.take(100)))
        } else {
            send(JSONObject().put("type", "command.progress").put("id", id).put("stage", stage.take(100)))
        }
    }
    private fun done(id: String, ok: Boolean, detail: String) {
        if (activeApiJob?.optString("id") == id) {
            if (ok && detail.startsWith("send_confirmed")) {
                progress(id, "전송 확인; ChatGPT 답변 추출 대기")
                waitForAnswer(id, activeApiJob?.optString("text") ?: "", 0, "", 0)
            } else {
                finishApiJob(id, false, detail)
            }
            return
        }
        val data=JSONObject().put("type",if(ok) "command.result" else "command.error").put("id",id)
        if(ok) data.put("result",JSONObject().put("ok",true).put("stage",detail)) else data.put("reason",detail)
        send(data)
    }


    // API jobs contain both the user and room IDs. Never send into an
    // unverified room merely because an unrelated ChatGPT chat is open.
    private fun receiveApiJob(job: JSONObject) {
        val id = job.optString("id")
        val room = job.optJSONObject("room")
        val roomId = room?.optString("id") ?: ""
        if (id.isBlank() || roomId.isBlank()) {
            send(JSONObject().put("type","job.error").put("job_id",id)
                .put("reason","Missing job or room identity"))
            return
        }
        if (activeApiJob != null || pendingSendId != null) {
            send(JSONObject().put("type","job.error").put("job_id",id)
                .put("reason","Android controller is busy processing another job"))
            return
        }
        activeApiJob = job
        send(JSONObject().put("type","job.received").put("job_id",id)
            .put("stage","Android job received; room="+roomId))
        if (job.optString("action") == "room.delete") {
            // ChatGPT deletion cannot be asserted from our current accessibility
            // nodes. Return an explicit failure instead of deleting wrong data.
            finishApiJob(id,false,"Room deletion needs verified ChatGPT conversation identity; no deletion attempted")
            return
        }
        if (job.optString("action") == "room.bind") {
            // Explicit user-directed one-time pairing for a legacy chat
            // without enough historical text to locate it automatically.
            // Never launch ChatGPT to an unknown conversation for this action.
            val root=rootInActiveWindow
            if(root?.packageName?.toString()!=chatPackage ||
               searchBarNode()!=null || composerInput(nodes(root))==null) {
                finishApiJob(id,false,
                    "Binding needs the correct ChatGPT conversation already open on Android")
                snapshot()
                return
            }
            progress(id,"현재 Android 대화에 고유 연결 메시지 전송 · 사용자 선택으로 등록")
            sendChat(id,job.optString("text"))
            return
        }
        if (job.optString("action") == "room.open") {
            progress(id,"기존 ChatGPT 대화방 검색 및 이동 시작")
            verifyExistingRoom(job) {
                finishApiJob(id,true,"room_open_verified","",roomId,"active")
            }
            return
        }
        if (job.optString("action") != "chat.send") {
            finishApiJob(id,false,"Unsupported API job action")
            return
        }
        val attachments = job.optJSONArray("attachment_ids") ?: JSONArray()
        if (attachments.length() > 0) {
            progress(id, "파일 "+attachments.length()+"개 Android 저장소로 전송 준비")
            stageFiles(job, attachments)
            return
        }
        val text = job.optString("text")
        if (text.isBlank()) {
            finishApiJob(id,false,"Question text is empty")
            return
        }
        val androidState = room?.optString("android_state","uncreated") ?: "uncreated"
        val targetUrl=targetConversationUrl(job)
        if (androidState == "uncreated" && targetUrl.isBlank()) {
            progress(id,"새 ChatGPT 채팅방 생성 요청: "+roomId)
            withChatApp(id) { createRoomThenSend(id,roomId,text,0) }
        } else {
            verifyExistingRoom(job) {
                progress(id,"대상 ChatGPT 방 확인 후 질문 입력")
                sendChat(id,text)
            }
        }
    }

    // A room ID is not exposed by ChatGPT Accessibility. Recover the mapping
    // only when a distinctive previous completed message from the same Railway
    // room is visible in the foreground Android conversation.
    private fun normalizedRoomText(text: String): String =
        text.replace(Regex("\\s+"), " ").trim().lowercase()

    private fun matchRoomAnchor(job: JSONObject): String? {
        if (rootInActiveWindow?.packageName?.toString() != chatPackage) return null
        // A search result can quote old text; this must be the real composer.
        val all=nodes(rootInActiveWindow)
        if (searchBarNode()!=null || composerInput(all)==null) return null
        val anchors=job.optJSONArray("room_anchors") ?: return null
        if(anchors.length()==0) return null
        val visible=all.mapNotNull { n ->
            val value=if(n.isEditable) "" else n.text?.toString().orEmpty()
            if(value.isBlank() || value.length>50000) null
            else normalizedRoomText(value)
        }
        for(i in 0 until anchors.length()) {
            val anchor=anchors.optJSONObject(i)?.optString("text").orEmpty()
            val normalized=normalizedRoomText(anchor)
            if(normalized.length<12)continue
            // Long messages can be split between Accessibility nodes.
            // A short phrase only matches a fully visible distinct text node.
            val proof=normalized.take(if(normalized.length>=40) 38 else normalized.length)
            if(visible.any { node ->
                 (normalized.length>=40 &&
                     (node.contains(proof) ||
                      (node.length>=35 && normalized.contains(node.take(35))))) ||
                 (normalized.length<40 && (node==normalized ||
                     (normalized.length>=18 && node.contains(normalized))))
            })return anchor
        }
        return null
    }

    private fun visibleRoomAnchor(anchor:String):Boolean {
        val normalized=normalizedRoomText(anchor)
        if(normalized.length<12)return false
        return nodes(rootInActiveWindow).any { n ->
            val value=if(n.isEditable) "" else normalizedRoomText(n.text?.toString().orEmpty())
            if(normalized.length>=40)
                value.contains(normalized.take(38)) ||
                    (value.length>=35 && normalized.contains(value.take(35)))
            else value==normalized ||
                (normalized.length>=18 && value.contains(normalized))
        }
    }

    // Decompiled ChatGPT 1.2026.300 AndroidManifest:
    // com.openai.chatgpt.ChatGptDeeplinkActivity exported ACTION_VIEW,
    // BROWSABLE, HTTPS chatgpt.com with pathPrefix /c/, /c2/, /uc/.
    // This is an app-to-app URL operation, NOT ACTION_SEND.
    // org.json can stringify JSONObject.NULL to literal "null" when
    // optString is used. Treat JSON null and absent fields as empty.
    private fun stringOrEmpty(objectValue:JSONObject?,key:String):String {
        if(objectValue==null || objectValue.isNull(key))return ""
        return objectValue.optString(key).takeUnless{it=="null"} ?: ""
    }
    private fun targetConversationUrl(job:JSONObject):String {
        return stringOrEmpty(job,"target_chatgpt_url").ifBlank {
            stringOrEmpty(job.optJSONObject("room"),"chatgpt_url")
        }
    }

    private fun validChatGptConversationLink(url:String):Boolean {
        return try {
            val uri=Uri.parse(url)
            if(uri.scheme!="https" || uri.host!="chatgpt.com" ||
               uri.port!=-1 || uri.userInfo!=null || uri.fragment!=null)false
            else {
                val seg=uri.pathSegments
                seg.size==2 && seg[0] in listOf("c","c2","uc") &&
                    seg[1].matches(Regex("[A-Za-z0-9_-]{8,128}"))
            }
        }catch(ignored:Exception){false}
    }

    // Sidebar rows in ChatGPT 1.2026.300 can expose a selected state.
    // Read it only when the drawer is already visible; never open the drawer
    // just to identify the current chat, as that costs an extra navigation.
    private fun selectedSidebarConversationTitle(): String? {
        val root=rootInActiveWindow
        if(root?.packageName?.toString()!=chatPackage)return null
        val all=nodes(root)
        val labels=all.mapNotNull {n ->
            if(!n.isVisibleToUser) null else n.text?.toString()?.trim()
        }
        val sidebarVisible=labels.any {it=="라이브러리" || it=="Library"} &&
            labels.any {it=="프로젝트" || it=="Projects"}
        if(!sidebarVisible)return null
        val content=all.filter{it.isVisibleToUser && it.isSelected}
            .mapNotNull{n -> n.text?.toString()?.trim() }
            .filter {it.isNotBlank() && it.length<170}
        // A selected tab/category alone does not identify a conversation.
        val notChats=setOf("ChatGPT","라이브러리","Library","프로젝트",
            "Projects","이미지","Images","채팅","Chats","맞춤 설정",
            "고정됨","Pinned","새 채팅","New Chat")
        return content.firstOrNull{it !in notChats}
    }

    private fun invalidateActiveConversationIdentity(reason:String) {
        // A newly created room has currentRoomId but no extracted ChatGPT URL.
        // It still must be invalidated on manual navigation or app switching.
        if(activeConversationId==null && currentRoomId==null)return
        sendLog("Active ChatGPT conversation cache invalidated: "+reason.take(70))
        activeConversationId=null
        currentRoomId=null
        routedIdentityGeneration=-1
        identityGeneration++
    }

    private fun chatComposerIsVisible(): Boolean {
        val root=rootInActiveWindow
        return root?.packageName?.toString()==chatPackage &&
            searchBarNode()==null && composerInput(nodes(root))!=null
    }

    private fun openExactChatGptConversation(
        job:JSONObject, onTargetReady:()->Unit
    ) {
        val jid=job.optString("id")
        val rid=job.optJSONObject("room")?.optString("id").orEmpty()
        val link=targetConversationUrl(job)
        if(!validChatGptConversationLink(link)) {
            finishApiJob(jid,false,"Target conversation deep link is missing or invalid")
            return
        }
        // A previous result from our app may already have the right chat
        // visible; still navigate if there is no historical content to
        // independently demonstrate that identity. A new intent is an
        // idempotent way to target the specific ChatGPT conversation ID.
        val targetId=Uri.parse(link).lastPathSegment.orEmpty()
        val declaredTargetId=stringOrEmpty(job,"target_conversation_id")
        if(declaredTargetId.isNotBlank() && declaredTargetId!=targetId){
            finishApiJob(jid,false,"Job conversation ID does not match deep-link URL")
            return
        }
        // Use only a title confirmed from ChatGPT itself. The Railway room
        // label may be different from ChatGPT's automatically generated title.
        val expectedTitle=job.optJSONObject("room")?.optString("chatgpt_title").orEmpty()
        val selectedTitle=selectedSidebarConversationTitle()
        if(selectedTitle!=null && expectedTitle.isNotBlank() &&
           normalizedRoomText(selectedTitle)!=normalizedRoomText(expectedTitle)) {
            invalidateActiveConversationIdentity("selected sidebar title changed")
        }
        // Fast path: after a successful /c/{id} navigation, no observed
        // user navigation and a real chat composer is still in foreground.
        // The relay does not open the sidebar or reload the same URL.
        val alreadyHere=activeConversationId==targetId &&
            currentRoomId==rid &&
            routedIdentityGeneration==identityGeneration &&
            chatComposerIsVisible()
        if(alreadyHere){
            deepLinkRoutedJobId=jid
            progress(jid,"동일 conversation_id 확인 · 딥링크 생략 · 현재 대화 그대로 사용")
            onTargetReady()
            return
        }
        val intent=Intent(Intent.ACTION_VIEW,Uri.parse(link)).apply {
            setPackage(chatPackage)
            addCategory(Intent.CATEGORY_BROWSABLE)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or
                     Intent.FLAG_ACTIVITY_SINGLE_TOP or
                     Intent.FLAG_ACTIVITY_CLEAR_TOP)
        }
        try{
            if(intent.resolveActivity(packageManager)==null){
                finishApiJob(jid,false,
                    "ChatGPT APK does not resolve ACTION_VIEW for /c/ conversation links")
                return
            }
            progress(jid,"공식 ChatGPT 대화 URL로 이동 요청 · "+
                Uri.parse(link).lastPathSegment.orEmpty().take(16))
            startActivity(intent)
        }catch(e:Exception){
            finishApiJob(jid,false,
                "ChatGPT ACTION_VIEW deep link launch error: "+
                e.javaClass.simpleName)
            return
        }
        main.postDelayed({
            verifyDeepLinkLanding(job,onTargetReady,0,0)
        },1100)
    }

    private fun verifyDeepLinkLanding(
        job:JSONObject, onTargetReady:()->Unit,
        attempt:Int, stable:Int
    ) {
        val jid=job.optString("id")
        if(activeApiJob?.optString("id")!=jid)return
        val root=rootInActiveWindow
        val blocker=screenBlockReason(root)
        if(blocker!=null) {
            finishApiJob(jid,false,blocker)
            return
        }
        val pkg=root?.packageName?.toString().orEmpty()
        val all=nodes(root)
        val composer=if(pkg==chatPackage && searchBarNode()==null)
            composerInput(all) else null
        val matching=if(composer!=null) matchRoomAnchor(job) else null
        val nextStable=if(composer!=null)stable+1 else 0
        if(matching!=null){
            // A URL intent and a visible composer do not prove the target ID:
            // the old conversation may remain open after a failed deep link.
            val rid=job.optJSONObject("room")?.optString("id").orEmpty()
            currentRoomId=rid
            activeConversationId=Uri.parse(targetConversationUrl(job)).lastPathSegment
            routedIdentityGeneration=identityGeneration
            deepLinkRoutedJobId=jid
            roomLastPrompt=matching
            progress(jid,"딥링크 이후 기존 대화의 실제 메시지 대조 성공")
            onTargetReady()
            return
        }
        if(nextStable>=4 && (job.optJSONArray("room_anchors")?.length() ?: 0)==0){
            finishApiJob(jid,false,
                "UNVERIFIED_CONVERSATION: URL opened a composer but no previously "+
                "confirmed room message exists; not claiming the target chat or sending")
            return
        }
        if(attempt<20){
            if(attempt%4==0)progress(jid,"ChatGPT 딥링크 착지·대화 내용 확인 중 · "+
                (if(pkg.isEmpty())"loading" else pkg))
            main.postDelayed({
                verifyDeepLinkLanding(job,onTargetReady,attempt+1,nextStable)
            },550)
        }else{
            snapshot()
            finishApiJob(jid,false,
                "UNVERIFIED_CONVERSATION: target chat's previously confirmed "+
                "message was not visible after ACTION_VIEW; wrong-room send blocked")
        }
    }

    private fun verifyExistingRoom(job: JSONObject, afterVerification: () -> Unit) {
        val jid = job.optString("id")
        val rid = job.optJSONObject("room")?.optString("id").orEmpty()
        withChatApp(jid) {
            val link=targetConversationUrl(job)
            if(link.isNotBlank() && validChatGptConversationLink(link)){
                openExactChatGptConversation(job,afterVerification)
                return@withChatApp
            }
            // A malformed legacy URL must not dead-end an otherwise
            // recoverable conversation. Continue ONLY to verified message
            // anchors/history search; never guess a room ID.
            if(link.isNotBlank()) progress(jid,
                "이전 대화 URL 형식 오류 · 동일 대화의 이전 메시지로 검증 시도")
            val match = matchRoomAnchor(job)
            if (match != null) {
                currentRoomId = rid
                roomLastPrompt = match
                progress(jid,"기존 대화 내용 검증 성공 · 이미 해당 채팅방 화면")
                afterVerification()
            } else if (currentRoomId == rid &&
                       chatComposerIsVisible() &&
                       (job.optJSONArray("room_anchors")?.length() ?: 0) == 0) {
                // Only a newly created chat within the same process qualifies.
                progress(jid,"현재 프로세스에서 생성한 채팅방 유지")
                afterVerification()
            } else {
                // Unlike the previous implementation, navigate to the correct
                // conversation instead of expecting the human to open it.
                progress(jid,"기존 대화 미표시 · 사이드바 검색으로 이동 시작")
                val queries=buildRoomSearchQueries(job)
                if ((job.optJSONArray("room_anchors")?.length() ?: 0)==0) {
                    finishApiJob(jid,false,
                        "LEGACY_BIND_REQUIRED: this conversation has no distinctive completed text. Open it once in ChatGPT on Android, then press '현재 Android 대화 연결' in the web console.")
                    snapshot()
                } else if(queries.isEmpty()){
                    finishApiJob(jid,false,"ChatGPT history search has no usable query")
                    snapshot()
                }else{
                    navigateToRoomSearch(job,afterVerification,queries.first(),0,0,0)
                }
            }
        }
    }

    // ChatGPT's search matches titles AND message content on Android.
    // Search completed messages from the SAME Railway room, never a failed
    // job or text from another user's conversation. A result is only a
    // candidate: verify its actual conversation content before sending.
    private fun buildRoomSearchQueries(job:JSONObject):List<String> {
        val results=ArrayList<String>()
        val fromServer=job.optJSONArray("room_search_terms") ?: JSONArray()
        val anchors=job.optJSONArray("room_anchors") ?: JSONArray()
        // A marker written by the explicit pairing operation is the most
        // reliable history-search term, even when ChatGPT titles differ.
        for(i in 0 until anchors.length()) {
            val txt=anchors.optJSONObject(i)?.optString("text").orEmpty()
            val id=job.optJSONObject("room")?.optString("id").orEmpty()
            if(txt.contains("HITEL Relay room marker") && id.isNotBlank())
                results.add(id)
        }
        for(i in 0 until fromServer.length()) {
            val txt=fromServer.optString(i).replace(Regex("\\s+")," ").trim()
            if(txt.length>=4)results.add(txt.take(40))
        }
        for(i in 0 until anchors.length()) {
            val txt=anchors.optJSONObject(i)?.optString("text").orEmpty()
                .replace(Regex("\\s+")," ").trim()
            if(txt.length>=12){
                results.add(txt.take(24))
                results.add(txt.take(16))
            }
        }
        val room=job.optJSONObject("room")
        val title=room?.optString("android_title").orEmpty()
        if(title.isNotBlank())results.add(title)
        val webTitle=room?.optString("title").orEmpty()
        if(webTitle.isNotBlank())results.add(webTitle)
        return results.filter {it.length>=2}.distinct().take(12)
    }

    private fun navigationNamedControl(labels: List<String>): AccessibilityNodeInfo? {
        val all=nodes(rootInActiveWindow)
        val matches=all.filter { n ->
            if (!n.isVisibleToUser) return@filter false
            val word=(n.text?.toString().orEmpty()+" "+
                n.contentDescription?.toString().orEmpty()+" "+
                n.viewIdResourceName.orEmpty()).trim().lowercase()
            word.length <= 95 && labels.any { label ->
                word == label || word.startsWith(label+" ") ||
                  word.contains(label)
            }
        }
        for (node in matches) {
            var target: AccessibilityNodeInfo?=node
            for (i in 0..4) {
                if (target==null || isClickTarget(target)) break
                target=target.parent
            }
            if (target?.isVisibleToUser==true && isClickTarget(target)) return target
        }
        return null
    }

    private fun searchBarNode(): AccessibilityNodeInfo? {
        val h=resources.displayMetrics.heightPixels
        val all=nodes(rootInActiveWindow)
        return all.filter { n ->
            if (!n.isEditable || !n.isVisibleToUser || !n.isEnabled) return@filter false
            val bounds=Rect().also { n.getBoundsInScreen(it) }
            val label=(n.hintText?.toString().orEmpty()+" "+
                n.contentDescription?.toString().orEmpty()+" "+
                n.viewIdResourceName.orEmpty()).lowercase()
            val searchNamed=listOf("search","검색","history_search","chat_search")
                .any { label.contains(it) }
            searchNamed || (bounds.top < h*0.55 && bounds.bottom<h*0.70)
        }.minByOrNull { n ->
            Rect().also { n.getBoundsInScreen(it) }.top
        }
    }

    private fun clickUniqueSearchResult(query: String, title: String): Boolean {
        val all=nodes(rootInActiveWindow)
        val screenH=resources.displayMetrics.heightPixels
        val screenW=resources.displayMetrics.widthPixels
        val searchBar=searchBarNode()
        val searchB=Rect().also { searchBar?.getBoundsInScreen(it) }
        val minY=if(searchBar!=null) searchB.bottom else (screenH*0.12).toInt()
        val q=normalizedRoomText(query).take(24)
        val exactTitle=normalizedRoomText(title)
        data class Item(val node:AccessibilityNodeInfo,val strong:Boolean,val rect:Rect)
        val matches=ArrayList<Item>()
        for(n in all) {
            if (!n.isVisibleToUser || n.isEditable) continue
            val label=(n.text?.toString().orEmpty()+" "+
                n.contentDescription?.toString().orEmpty()).trim()
            val norm=normalizedRoomText(label)
            if(norm.length<5 || norm.length>500 || listOf(
                    "search chats","대화 검색","검색","cancel","취소","settings","설정",
                    "new chat","새 채팅","projects","프로젝트","images","이미지")
                    .any { norm==it }) continue
            val rect=Rect().also {n.getBoundsInScreen(it)}
            if(rect.top<minY || rect.bottom>screenH*0.92 || rect.height()>screenH*0.28)
                continue
            val strong=(q.length>=7 && norm.contains(q)) ||
                (exactTitle.length>=3 && norm==exactTitle)
            // Prefer a search hit that contains the distinctive query or a
            // correctly named chat. Otherwise only consider clearly marked
            // conversation/result list nodes, never random screen controls.
            val id=n.viewIdResourceName.orEmpty().lowercase()
            val likely=id.contains("conversation") || id.contains("chat_row") ||
                id.contains("search_result") || id.contains("result_item")
            // Compose frequently exposes no stable resource IDs for search
            // hits. A single unique selectable text row below the search
            // field is still safe to inspect because the real chat history
            // must be VERIFIED before any send.
            val uniqueCandidate=normalizedRoomText(query).length>=7 &&
                norm.length in 7..180 &&
                listOf("all","chats","documents","projects","images","파일",
                    "채팅","전체","문서","프로젝트","결과 없음","no results",
                    "대화 검색","search chats","최근","recent","모두")
                    .none { word -> norm==word }
            if(!strong && !likely && !uniqueCandidate)continue
            var target: AccessibilityNodeInfo?=n
            for(i in 0..4) {
                if(target==null || isClickTarget(target))break
                target=target.parent
            }
            if(target!=null && isClickTarget(target) && target.isVisibleToUser) {
                val targetRect=Rect().also{target.getBoundsInScreen(it)}
                // Search result cards occupy most of the content width.
                // Restrict fallback candidates so unrelated toolbar buttons
                // cannot masquerade as a unique conversation.
                val card=targetRect.width()>=screenW*0.46 &&
                    targetRect.height() in 25..(screenH*0.30).toInt() &&
                    targetRect.top>=minY
                if(card || strong)
                    matches.add(Item(target,strong,targetRect))
            }
        }
        val selected=matches.filter{it.strong}.ifEmpty{matches}
            .distinctBy{it.rect.toShortString()}
        if(selected.size != 1) {
            sendLog("Chat search candidate count="+selected.size+
                ", clickable="+matches.size+", queryLength="+query.length+
                ", screenNodes="+all.size)
            return false
        }
        return selected.first().node.performAction(AccessibilityNodeInfo.ACTION_CLICK)
    }

    private fun navigateToRoomSearch(
        job:JSONObject, afterVerification:()->Unit,
        query:String, phase:Int, attempt:Int, scrolls:Int
    ) {
        val jid=job.optString("id")
        if(activeApiJob?.optString("id")!=jid)return
        val root=rootInActiveWindow
        if(root?.packageName?.toString()!=chatPackage) {
            finishApiJob(jid,false,
                "ChatGPT lost foreground while searching for existing room; no message sent")
            return
        }
        val found=matchRoomAnchor(job)
        if(found!=null) {
            currentRoomId=job.optJSONObject("room")?.optString("id")
            roomLastPrompt=found
            progress(jid,"기존 ChatGPT 대화 검색·이동·내용 검증 완료")
            afterVerification()
            return
        }
        when(phase) {
            0 -> {
                // Search might already be open (e.g. a prior retry).
                if(searchBarNode()!=null){
                    main.postDelayed({
                        navigateToRoomSearch(job,afterVerification,query,1,0,0)
                    },200)
                    return
                }
                // ChatGPT search is in the navigation sidebar, not a normal
                // message composer. Open the sidebar if search is not visible.
                val search=navigationNamedControl(listOf(
                    "대화 검색","채팅 검색","search chats","search history",
                    "search conversations","search_chat","검색"))
                if(search!=null) {
                    if(search.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
                        progress(jid,"ChatGPT 대화 검색 화면 열기")
                        main.postDelayed({
                            navigateToRoomSearch(job,afterVerification,query,1,0,0)
                        },650)
                        return
                    }
                }
                val menu=navigationNamedControl(listOf(
                    "open navigation","navigation drawer","open sidebar",
                    "메뉴 열기","사이드바 열기","menu","sidebar"))
                if(menu!=null && menu.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
                    progress(jid,"ChatGPT 왼쪽 채팅방 목록 열기")
                    main.postDelayed({
                        navigateToRoomSearch(job,afterVerification,query,1,0,0)
                    },650)
                    return
                }
                if(attempt<5) {
                    main.postDelayed({
                        navigateToRoomSearch(job,afterVerification,query,0,attempt+1,0)
                    },400)
                } else {
                    snapshot()
                    finishApiJob(jid,false,
                        "ChatGPT sidebar/search control not found; no wrong-room send attempted")
                }
            }
            1 -> {
                val bar=searchBarNode()
                if(bar!=null) {
                    val args=Bundle().apply {
                        putCharSequence(
                            AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,query)
                    }
                    bar.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
                    if(!bar.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT,args)) {
                        finishApiJob(jid,false,"ChatGPT history search text entry rejected")
                        snapshot()
                        return
                    }
                    progress(jid,"이전 대화 내용으로 검색 중: "+query.take(35))
                    main.postDelayed({
                        navigateToRoomSearch(job,afterVerification,query,2,0,0)
                    },1100)
                    return
                }
                val search=navigationNamedControl(listOf(
                    "대화 검색","채팅 검색","search chats","search history",
                    "search conversations","search_chat","검색"))
                if(search!=null && search.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
                    main.postDelayed({
                        navigateToRoomSearch(job,afterVerification,query,1,attempt+1,0)
                    },550)
                    return
                }
                if(attempt<7)main.postDelayed({
                    navigateToRoomSearch(job,afterVerification,query,1,attempt+1,0)
                },450)
                else {
                    snapshot()
                    finishApiJob(jid,false,
                        "ChatGPT history search field not found in sidebar; no message sent")
                }
            }
            2 -> {
                val title=job.optJSONObject("room")?.optString("android_title").orEmpty()
                    .ifBlank {job.optJSONObject("room")?.optString("title").orEmpty()}
                if(clickUniqueSearchResult(query,title)){
                    progress(jid,"검색 결과 대화 선택 · 실제 메시지 재검증")
                    main.postDelayed({
                        navigateToRoomSearch(job,afterVerification,query,3,0,0)
                    },1100)
                    return
                }
                if(attempt<7)main.postDelayed({
                    navigateToRoomSearch(job,afterVerification,query,2,attempt+1,0)
                },550)
                else {
                    val queries=buildRoomSearchQueries(job)
                    val next=queries.indexOf(query)+1
                    if(next>0 && next<queries.size && next<6) {
                        progress(jid,"검색 결과 없음 · 다른 이전 메시지로 재검색 "+
                            (next+1)+"/"+queries.size)
                        navigateToRoomSearch(job,afterVerification,queries[next],1,0,0)
                    }else{
                        snapshot()
                        finishApiJob(jid,false,
                            "No unique ChatGPT history search result matched 6 candidate queries; " +
                            "open the correct chat on Android and use one-time binding")
                    }
                }
            }
            else -> {
                // The result may open an older part of the conversation.
                // Check completed Railway message content, not just its title.
                val all=nodes(root)
                val scrollable=all.filter{it.isScrollable && it.isVisibleToUser}
                    .maxByOrNull{n ->
                        Rect().also { n.getBoundsInScreen(it) }.height()
                    }
                if(scrollable!=null && scrolls<5 && attempt%3==0) {
                    scrollable.performAction(AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD)
                    progress(jid,"대화 내용 대조를 위해 이전 메시지 확인")
                }
                if(attempt<13)main.postDelayed({
                    navigateToRoomSearch(job,afterVerification,query,3,attempt+1,scrolls+1)
                },600)
                else {
                    snapshot()
                    finishApiJob(jid,false,
                        "Opened a search candidate but did not verify matching room history; no message sent")
                }
            }
        }
    }

    private fun namedControl(labelWords: List<String>): AccessibilityNodeInfo? {
        val all=nodes(rootInActiveWindow)
        for (n in all) {
            val v=(n.text?.toString().orEmpty()+" "+n.contentDescription?.toString().orEmpty()).trim().lowercase()
            if (labelWords.none { v.contains(it) }) continue
            var p: AccessibilityNodeInfo?=n
            var depth=0
            while (p!=null && !isClickTarget(p) && depth<5) {p=p.parent;depth++}
            if (p!=null && isClickTarget(p))return p
        }
        return null
    }

    private fun createRoomThenSend(id: String, roomId: String, text: String, attempt: Int) {
        if (activeApiJob?.optString("id") != id) return
        if (rootInActiveWindow?.packageName?.toString()!=chatPackage) {
            finishApiJob(id,false,"ChatGPT is not in foreground during room creation");return
        }
        val newChat = namedControl(listOf("새 채팅","new chat","new conversation"))
        if(newChat!=null) {
            if (!newChat.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
                finishApiJob(id,false,"Could not click the New Chat control")
                return
            }
            progress(id,"공식 ChatGPT 새 채팅 클릭")
            main.postDelayed({
                if (activeApiJob?.optString("id")!=id)return@postDelayed
                val input=composerInput(nodes(rootInActiveWindow))
                if(input==null){finishApiJob(id,false,"No composer after new-chat action");return@postDelayed}
                // This identifies a fresh composer action, not a stable
                // ChatGPT thread ID. Persisting/reselecting after restart still
                // requires an in-app conversation identity verification.
                currentRoomId=roomId
                activeConversationId=null
                routedIdentityGeneration=-1
                progress(id,"새 대화 입력창 확인")
                sendChat(id,text)
            },800)
            return
        }
        if(attempt==0) {
            val menu=namedControl(listOf("메뉴","menu","sidebar","open navigation"))
            if(menu!=null && menu.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
                progress(id,"채팅방 목록 메뉴 열기")
                main.postDelayed({createRoomThenSend(id,roomId,text,1)},550)
                return
            }
        }
        finishApiJob(id,false,"New-chat button was not identified. Android UI snapshot required.")
        snapshot()
    }

    // Files were already placed on Railway by /api/v1/files. Download each one
    // with its real extension and checksum; .bin would lose MIME semantics.
    private fun stageFiles(job: JSONObject, ids: JSONArray) {
        val jid = job.optString("id")
        val details = job.optJSONArray("attachment_details")
        if (details == null || details.length() != ids.length()) {
            finishApiJob(jid, false, "Android did not receive original attachment metadata")
            return
        }
        val prefs = getSharedPreferences("relay", MODE_PRIVATE)
        val endpoint = prefs.getString("url", "").orEmpty()
            .ifBlank { "wss://chatgpt-relay-web-production.up.railway.app/ws" }
            .replaceFirst("wss://", "https://").removeSuffix("/ws")
        val token = prefs.getString("token", "").orEmpty()
            .ifBlank { "dpYZLhnMxOq02PNKGtTnBvzNSBAkLQ2Ip8zTzbEn" }
        thread(start = true, name = "relay-image-stage") {
            val staged = ArrayList<StagedAttachment>()
            var failure = ""
            try {
                val base = File(filesDir, "relay-attachments").apply { mkdirs() }
                val allowed = setOf("png", "jpg", "jpeg", "webp", "gif", "pdf",
                    "txt", "md", "doc", "docx", "ppt", "pptx", "xls", "xlsx",
                    "csv", "json")
                for (i in 0 until ids.length()) {
                    val fid = ids.getString(i)
                    if (!fid.matches(Regex("file_[0-9a-f]{32}"))) {
                        throw IllegalArgumentException("Invalid file id")
                    }
                    val meta = (0 until details.length())
                        .mapNotNull { details.optJSONObject(it) }
                        .firstOrNull { it.optString("id") == fid }
                        ?: throw IllegalArgumentException("Attachment metadata not found")
                    val name = File(meta.optString("name")).name
                    val ext = name.substringAfterLast('.', "").lowercase()
                    if (ext !in allowed || name.isBlank()) {
                        throw IllegalArgumentException("Unsupported attachment format")
                    }
                    val mime = meta.optString("mime", "application/octet-stream")
                    val expectedHash = meta.optString("sha256")
                    val expectedSize = meta.optLong("size", -1L)
                    if (expectedSize <= 0L || expectedSize > 15L * 1024L * 1024L) {
                        throw IllegalArgumentException("Attachment size outside 15MB limit")
                    }
                    val request = Request.Builder()
                        .url(endpoint + "/api/v1/device/jobs/" + jid + "/files/" + fid)
                        .header("Authorization", "Bearer " + token)
                        .build()
                    client.newCall(request).execute().use { response ->
                        if (!response.isSuccessful) {
                            throw IllegalStateException("Android file GET returned HTTP " + response.code)
                        }
                        val bytes = response.body?.bytes()
                            ?: throw IllegalStateException("Empty response body")
                        if (bytes.size.toLong() != expectedSize) {
                            throw IllegalStateException("File size mismatch after download")
                        }
                        val digest = MessageDigest.getInstance("SHA-256").digest(bytes)
                            .joinToString("") { "%02x".format(it.toInt() and 0xff) }
                        if (!digest.equals(expectedHash, ignoreCase = true)) {
                            throw IllegalStateException("File checksum mismatch after download")
                        }
                        val destination = File(File(base, jid + "/" + fid).apply { mkdirs() }, name)
                        destination.writeBytes(bytes)
                        val uri = FileProvider.getUriForFile(
                            this, "com.hitel.chatrelay.fileprovider", destination)
                        staged.add(StagedAttachment(fid, name, mime, destination, uri))
                    }
                }
            } catch (e: Exception) {
                failure = e.javaClass.simpleName + ": " + (e.message ?: "")
            }
            main.post {
                if (activeApiJob?.optString("id") != jid) return@post
                if (failure.isNotEmpty()) {
                    finishApiJob(jid, false, "Android download: " + failure)
                } else {
                    progress(jid, "파일 " + staged.size + "개 SHA-256 검증 및 원래 MIME 보존 완료")
                    shareFilesIntoChatGpt(job, staged)
                }
            }
        }
    }

    private fun visibleConversationText(): Set<String> {
        return nodes(rootInActiveWindow).mapNotNull { node ->
            val candidate = node.text?.toString()?.trim().orEmpty()
            if (node.isEditable || candidate.length < 6 || candidate.length > 1000 ||
                candidate in chrome) null else candidate
        }.toSet()
    }

    private fun composerAttachmentSignals(): Int {
        val all = nodes(rootInActiveWindow)
        val input = composerInput(all) ?: return 0
        val area = Rect().also { input.getBoundsInScreen(it) }
        val margin = (260 * resources.displayMetrics.density).toInt()
        return all.count { node ->
            if (!node.isVisibleToUser || node.isEditable) return@count false
            val r = Rect().also { node.getBoundsInScreen(it) }
            if (r.isEmpty || r.bottom < area.top - margin || r.top > area.bottom + margin) {
                return@count false
            }
            val desc = node.contentDescription?.toString()?.lowercase().orEmpty()
            val resource = node.viewIdResourceName?.lowercase().orEmpty()
            val words = desc + " " + resource
            listOf("attachment_preview", "attached_image", "remove_attachment",
                "remove_image", "remove_file", "첨부 이미지 제거", "첨부파일 제거",
                "이미지 미리보기", "사진 제거").any { words.contains(it) }
        }
    }


    // Every file is selected through the current ChatGPT composer. ACTION_SEND
    // is deliberately not used: it can create an unrelated new conversation.
    // Choose only our unique MediaStore filename, never an arbitrary photo.
    private fun pickFileInsideExistingRoom(
        job: JSONObject, staged: List<StagedAttachment>, index: Int = 0
    ) {
        val jid = job.optString("id")
        val roomId = job.optJSONObject("room")?.optString("id").orEmpty()
        if (currentRoomId != roomId) {
            finishApiJob(jid, false, "Target ChatGPT room is not verified; no file attached")
            return
        }
        if (index >= staged.size) {
            progress(jid, "파일 " + staged.size + "개 첨부 표시 확인 완료 · 질문 전송")
            val question = activeApiJob?.optString("text").orEmpty()
            if (question.isBlank()) {
                finishApiJob(jid, false, "Question is empty; no attachment-only send")
            } else {
                sendChat(jid, question)
            }
            return
        }
        withChatApp(jid) {
            val fresh = job.optJSONObject("room")?.optString("android_state") == "uncreated" &&
                targetConversationUrl(job).isBlank()
            val anchor = roomLastPrompt
            // A URL-directed job may have no long historical text yet.
            // Its composer was already checked immediately after ACTION_VIEW.
            val verifiedByDeepLink=deepLinkRoutedJobId==jid &&
                rootInActiveWindow?.packageName?.toString()==chatPackage &&
                composerInput(nodes(rootInActiveWindow))!=null &&
                searchBarNode()==null
            if (!fresh && !verifiedByDeepLink && !visibleRoomAnchor(anchor)) {
                finishApiJob(jid,false,
                    "Existing room not visible before Android file picker; no message sent")
                snapshot()
                return@withChatApp
            }
            shareRoomAnchor = if (fresh) "" else anchor
            sharePreviewsBefore = composerAttachmentSignals()
            val stagedFile = staged[index]
            progress(jid, "ChatGPT 채팅방 확인 · 파일 " + (index+1) + "/" + staged.size + " 준비")
            thread(start = true, name = "relay-media-publish") {
                var uri: Uri? = null
                var failed: String? = null
                val extension = stagedFile.name.substringAfterLast('.', "bin")
                val uniqueName = "relay_" + jid.removePrefix("job_").take(8) + "_" +
                    stagedFile.id.takeLast(6) + "." + extension
                try {
                    val content = ContentValues().apply {
                        put(MediaStore.MediaColumns.DISPLAY_NAME, uniqueName)
                        put(MediaStore.MediaColumns.MIME_TYPE, stagedFile.mime)
                        put(MediaStore.MediaColumns.RELATIVE_PATH,
                            Environment.DIRECTORY_DOWNLOADS + "/ChatGPTRelay")
                        put(MediaStore.MediaColumns.IS_PENDING, 1)
                    }
                    uri = contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, content)
                        ?: throw IllegalStateException("Cannot insert into Android Downloads")
                    contentResolver.openOutputStream(uri!!)?.use { output ->
                        stagedFile.file.inputStream().use { input -> input.copyTo(output) }
                    } ?: throw IllegalStateException("Android Downloads output unavailable")
                    contentResolver.update(uri!!,
                        ContentValues().apply { put(MediaStore.MediaColumns.IS_PENDING, 0) },
                        null, null)
                } catch (e: Exception) {
                    failed = e.javaClass.simpleName + ": " + (e.message ?: "")
                }
                main.post {
                    if (activeApiJob?.optString("id") != jid) return@post
                    if (failed != null) {
                        finishApiJob(jid, false, "Android file publish failed: " + failed)
                        return@post
                    }
                    uri?.let { pendingPickerCleanup.add(it) }
                    pendingPickerUri = uri
                    pendingPickerDisplayName = uniqueName
                    progress(jid, "Android Downloads에 고유 파일 저장 · ChatGPT 첨부 열기")
                    val attach = findComposerAttachButton()
                    if (attach == null || !attach.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
                        snapshot()
                        finishApiJob(jid, false,
                            "ChatGPT input-area attachment (+) button was not found/clickable")
                        return@post
                    }
                    main.postDelayed({ waitInChatPicker(jid, staged, index, 0, 0) }, 500)
                }
            }
        }
    }

    private fun createRoomForAttachments(
        job: JSONObject, staged: List<StagedAttachment>, attempt: Int
    ) {
        val jid = job.optString("id")
        val rid = job.optJSONObject("room")?.optString("id").orEmpty()
        if (activeApiJob?.optString("id") != jid) return
        if (rootInActiveWindow?.packageName?.toString() != chatPackage) {
            finishApiJob(jid, false, "ChatGPT not foreground for fresh attachment room")
            return
        }
        val newChat = namedControl(listOf("새 채팅","new chat","new conversation"))
        if (newChat != null && newChat.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
            progress(jid, "새 ChatGPT 채팅 버튼 클릭")
            main.postDelayed({
                if (activeApiJob?.optString("id") != jid) return@postDelayed
                if (composerInput(nodes(rootInActiveWindow)) == null) {
                    finishApiJob(jid,false,"No chat composer after New Chat click")
                    return@postDelayed
                }
                currentRoomId = rid
                roomLastPrompt = ""
                pickFileInsideExistingRoom(job,staged)
            },800)
            return
        }
        if (attempt == 0) {
            val menu = namedControl(listOf("메뉴","menu","sidebar","open navigation"))
            if (menu?.performAction(AccessibilityNodeInfo.ACTION_CLICK) == true) {
                main.postDelayed({ createRoomForAttachments(job,staged,1) },650)
                return
            }
        }
        finishApiJob(jid,false,"Cannot open fresh ChatGPT conversation for file attachment")
        snapshot()
    }

    private fun findComposerAttachButton(): AccessibilityNodeInfo? {
        val all = nodes(rootInActiveWindow)
        val composer = composerInput(all) ?: return null
        val ir = Rect().also { composer.getBoundsInScreen(it) }
        val px = resources.displayMetrics.density
        return all.filter { n ->
            if (!n.isVisibleToUser) return@filter false
            val labels = accessibleLabel(n)
            val words = listOf("첨부파일", "파일 추가", "파일 첨부", "첨부", "사진 추가",
                "attach files", "add attachment", "add photos", "add files",
                "attach", "plus_button", "add_button", "attachment_button")
            if (words.none { labels.contains(it) }) return@filter false
            val bounds = Rect().also { n.getBoundsInScreen(it) }
            bounds.bottom >= ir.top - (140 * px).toInt() &&
                bounds.top <= ir.bottom + (90 * px).toInt()
        }.mapNotNull { n ->
            var p: AccessibilityNodeInfo? = n
            for (i in 0..4) {
                if (p == null || isClickTarget(p)) break
                p = p.parent
            }
            if (p != null && isClickTarget(p)) p else null
        }.minByOrNull { n ->
            val rect = Rect().also { n.getBoundsInScreen(it) }
            kotlin.math.abs(rect.centerX() - ir.left) +
                kotlin.math.abs(rect.centerY() - ir.bottom)
        } ?: run {
            // Some ChatGPT versions expose the + glyph as an unlabeled icon.
            // Only select it if precisely one small clickable node is placed
            // immediately LEFT of the known composer. Never guess when several
            // controls (camera, voice, navigation) overlap that region.
            val candidates = all.filter { n ->
                if (!n.isVisibleToUser || !isClickTarget(n) || n.isEditable) return@filter false
                val label = accessibleLabel(n)
                if (listOf("voice","record","microphone","camera","send","submit",
                        "전송","음성","녹음","마이크","카메라","뒤로","back").any {
                        label.contains(it) }) return@filter false
                val b = Rect().also { n.getBoundsInScreen(it) }
                val maxSize = (88 * px).toInt()
                val centerX = b.centerX()
                val centerY = b.centerY()
                b.width() in 1..maxSize && b.height() in 1..maxSize &&
                    centerX >= ir.left - (100 * px).toInt() &&
                    centerX <= ir.left + (30 * px).toInt() &&
                    centerY >= ir.top - (15 * px).toInt() &&
                    centerY <= ir.bottom + (26 * px).toInt()
            }.distinctBy { n ->
                Rect().also { n.getBoundsInScreen(it) }.toShortString()
            }
            if (candidates.size == 1) candidates.first() else null
        }
    }

    private fun pickerClickByNames(all: List<AccessibilityNodeInfo>,
                                   names: List<String>): Boolean {
        val match = all.firstOrNull { n ->
            n.isVisibleToUser && names.any { key ->
                val v = (n.text?.toString().orEmpty() + " " +
                    n.contentDescription?.toString().orEmpty()).trim()
                v.equals(key, ignoreCase = true) ||
                    (key.length >= 8 && v.contains(key, ignoreCase = true))
            }
        } ?: return false
        var target: AccessibilityNodeInfo? = match
        for (depth in 0..5) {
            if (target == null || isClickTarget(target)) break
            target = target.parent
        }
        return target?.performAction(AccessibilityNodeInfo.ACTION_CLICK) == true
    }

    // Only ever select the unique file name we inserted into MediaStore.
    // No blind clicks at "the first photo" (could leak another user's picture).
    // The picker can be ChatGPT's own attachment menu or the Android
    // DocumentsUI/file browser. Keep the file identity bound to job + index.
    private fun waitInChatPicker(
        jid: String, staged: List<StagedAttachment>, index: Int,
        attempt: Int, menuStage: Int
    ) {
        if (activeApiJob?.optString("id") != jid) return
        val root = rootInActiveWindow
        val pkg = root?.packageName?.toString().orEmpty()
        val all = nodes(root)
        val expected = pendingPickerDisplayName.orEmpty()
        if (expected.isBlank()) {
            finishApiJob(jid, false, "No expected filename for file picker")
            return
        }
        if (pkg.isNotEmpty() && pkg != chatPackage) {
            if (pickerClickByNames(all, listOf(expected))) {
                progress(jid, "시스템 파일 선택기에서 고유 이름 " + expected + " 선택")
                main.postDelayed({ verifyPickerAttachment(jid,staged,index,0) },900)
                return
            }
            if (menuStage == 1 &&
                pickerClickByNames(all, listOf("다운로드","Downloads","Download"))) {
                progress(jid, "Android Downloads 폴더 선택")
                main.postDelayed({ waitInChatPicker(jid,staged,index,attempt+1,2) },650)
                return
            }
            if (menuStage == 2 &&
                pickerClickByNames(all, listOf("ChatGPTRelay"))) {
                progress(jid, "ChatGPTRelay 전용 폴더 선택")
                main.postDelayed({ waitInChatPicker(jid,staged,index,attempt+1,3) },650)
                return
            }
            if (menuStage <= 1 && attempt >= 3 &&
                pickerClickByNames(all, listOf("파일","Browse","문서",
                    "Browse files","Files"))) {
                progress(jid, "Android 시스템 파일 탐색으로 전환")
                main.postDelayed({ waitInChatPicker(jid,staged,index,attempt+1,1) },600)
                return
            }
        } else if (pkg == chatPackage) {
            if (menuStage == 0) {
                if (pickerClickByNames(all, listOf(
                    "파일 업로드","기기에서 파일","기기에서 업로드",
                    "Browse files","Upload files","Files","파일","문서"))) {
                    progress(jid, "ChatGPT 첨부 메뉴에서 파일 선택")
                    main.postDelayed({ waitInChatPicker(jid,staged,index,attempt+1,1) },650)
                    return
                }
            } else {
                // Selecting a file can return immediately to the composer.
                val signals = composerAttachmentSignals()
                val named = all.any { n ->
                    n.isVisibleToUser && !n.isEditable &&
                    ((n.text?.toString() ?: "").contains(expected,ignoreCase=true) ||
                     (n.contentDescription?.toString() ?: "").contains(expected,ignoreCase=true))
                }
                if (signals > sharePreviewsBefore || named) {
                    verifyPickerAttachment(jid,staged,index,0)
                    return
                }
            }
        }
        if (attempt % 5 == 0)
            progress(jid, "파일 " + (index+1) + "/" + staged.size +
                " 선택기 확인 중 · 화면=" + pkg + ", 단계=" + menuStage)
        if (attempt < 30) {
            main.postDelayed({
                waitInChatPicker(jid,staged,index,attempt+1,menuStage)
            },500)
        } else {
            snapshot()
            finishApiJob(jid,false,
                "Android file picker could not locate this job's unique filename: " + expected)
        }
    }

    private fun verifyPickerAttachment(
        jid: String, staged: List<StagedAttachment>, index: Int, attempt: Int
    ) {
        if (activeApiJob?.optString("id") != jid) return
        val root = rootInActiveWindow
        val pkg = root?.packageName?.toString()
        if (pkg == chatPackage) {
            if (shareRoomAnchor.isNotEmpty() && !visibleRoomAnchor(shareRoomAnchor)) {
                finishApiJob(jid,false,
                    "ChatGPT conversation changed after selecting attachment. No question sent")
                snapshot()
                return
            }
            val all = nodes(root)
            val input = composerInput(all)
            val file = staged[index]
            val names = listOf(file.name,pendingPickerDisplayName.orEmpty()).filter { it.length>=5 }
            val named = all.any { n ->
                if (!n.isVisibleToUser || n.isEditable) return@any false
                val label = (n.text?.toString().orEmpty()+" "+
                    n.contentDescription?.toString().orEmpty()).lowercase()
                names.any { name -> label.contains(name.lowercase()) }
            }
            val previews = composerAttachmentSignals()
            if (input != null && (named || previews > sharePreviewsBefore)) {
                progress(jid,"ChatGPT 입력창에서 파일 " + (index+1) +
                    "/" + staged.size + " 첨부 확인")
                pendingPickerDisplayName = null
                pendingPickerUri = null
                // Every file must be confirmed before a single text send.
                main.postDelayed({
                    activeApiJob?.let { pickFileInsideExistingRoom(it,staged,index+1) }
                },450)
                return
            }
        } else if (pkg?.contains("documentsui",ignoreCase=true)==true && attempt==4) {
            // Some DocumentsUI variants require a final confirmation after
            // choosing a file; never select an arbitrary other file.
            val all=nodes(root)
            if (pickerClickByNames(all,listOf("열기","Open","선택","Select"))) {
                progress(jid,"선택한 Android 파일 열기 확인")
            }
        }
        if (attempt % 6 == 0)
            progress(jid,"ChatGPT 첨부 미리보기 검증 중 · " + (index+1) +
                "/" + staged.size + ", 화면=" + (pkg ?: "(없음)"))
        if (attempt < 25) {
            main.postDelayed({
                verifyPickerAttachment(jid,staged,index,attempt+1)
            },500)
        } else {
            snapshot()
            finishApiJob(jid,false,
                "File was downloaded but ChatGPT composer attachment NOT VERIFIED; question not sent")
        }
    }

    private fun shareFilesIntoChatGpt(job: JSONObject, staged: List<StagedAttachment>) {
        val jid = job.optString("id")
        val state = job.optJSONObject("room")?.optString("android_state","uncreated")
            ?: "uncreated"
        if (staged.isEmpty()) {
            finishApiJob(jid,false,"No verified Android download")
            return
        }
        val targetUrl=targetConversationUrl(job)
        when {
            state == "uncreated" && targetUrl.isBlank() -> withChatApp(jid) {
                createRoomForAttachments(job,staged,0)
            }
            state in listOf("active","unverified") || targetUrl.isNotBlank() ->
                verifyExistingRoom(job) {
                    pickFileInsideExistingRoom(job,staged,0)
                }
            else -> finishApiJob(jid,false,
                "Room is not verified for ChatGPT attachment: "+state)
        }
    }

    private fun responseCandidate(question: String): String {
        val data=nodes(rootInActiveWindow)
        val normalizedQuestion=normalizedRoomText(question)
        if(normalizedQuestion.length<2)return ""
        val questionPrefix=normalizedQuestion.take(90)
        // A stable toolbar or login label is not an assistant response.
        // First require the actual submitted user message in the conversation
        // accessibility tree. This deliberately favors an explicit failure
        // over falsely reporting a successful ChatGPT reply.
        val promptIndex=data.indexOfLast { n ->
            if(n.isEditable || !n.isVisibleToUser)return@indexOfLast false
            val value=normalizedRoomText(n.text?.toString().orEmpty())
            value==normalizedQuestion ||
                (normalizedQuestion.length>=40 && value.contains(questionPrefix))
        }
        if(promptIndex<0)return ""
        val others=data.drop(promptIndex+1).mapNotNull { n ->
            val value=n.text?.toString()?.trim().orEmpty()
            val normalized=normalizedRoomText(value)
            if(!n.isVisibleToUser || value.isBlank() || n.isEditable ||
               n.isClickable || normalized==normalizedQuestion ||
               normalized.contains(questionPrefix) ||
               value in chrome || value.length>7000) null
            else if(value.contains("메뉴") && value.length<22) null
            else if(listOf("chatgpt can make mistakes",
                    "chatgpt는 실수를 할 수 있습니다",
                    "check important info","중요한 정보는 확인").any {
                    normalized.contains(it)
                }) null
            else value
        }
        return others.lastOrNull().orEmpty()
    }

    private fun waitForAnswer(id: String, question: String, attempt: Int, previous: String, stable: Int) {
        if (activeApiJob?.optString("id") != id) return
        if(rootInActiveWindow?.packageName?.toString()!=chatPackage) {
            finishApiJob(id,false,"ChatGPT foreground lost before response extraction")
            return
        }
        val candidate=responseCandidate(question)
        val nextStable=if(candidate.isNotBlank() && candidate==previous)stable+1 else 0
        val hasStop=nodes(rootInActiveWindow).any { n ->
            val label=accessibleLabel(n)
            n.isVisibleToUser && n.isClickable &&
                listOf("stop generating","stop response","생성 중지","응답 중지").any {label.contains(it)}
        }
        if(candidate.isNotBlank() && nextStable>=3 && !hasStop && attempt>=4) {
            val rid=activeApiJob?.optJSONObject("room")?.optString("id").orEmpty()
            roomLastPrompt=if (candidate.length >= 24) candidate.take(200)
                else question
            finishApiJob(id,true,"assistant_reply_stable",candidate,rid,"active")
            return
        }
        if(attempt>=115) {
            finishApiJob(id,false,"Message was submitted but assistant response was NOT verified within timeout")
            return
        }
        if(attempt%5==0) progress(id,"답변 추출 확인 중 ("+attempt+"회, "+candidate.length+"자)")
        main.postDelayed({waitForAnswer(id,question,attempt+1,candidate,nextStable)},950)
    }

    private fun finishApiJob(id:String, verified:Boolean, stage:String,
                             resultText:String?=null,roomId:String?=null,roomState:String?=null) {
        if(activeApiJob?.optString("id")!=id)return
        val message=JSONObject().put("type",if(verified)"job.result" else "job.error")
            .put("job_id",id).put("verified",verified).put("stage",stage.take(100))
        if(verified){
            message.put("result_text",resultText ?: "")
            if(roomId!=null){message.put("room_id",roomId);message.put("room_state",roomState)}
        }else{
            message.put("reason",stage.take(400))
        }
        send(message)
        val cleanup = ArrayList<Uri>(pendingPickerCleanup)
        pendingPickerCleanup.clear()
        if (cleanup.isNotEmpty()) {
            main.postDelayed({
                for (uri in cleanup) {
                    try { contentResolver.delete(uri, null, null) }
                    catch (ignored: Exception) { }
                }
            }, 90000)
        }
        pendingPickerUri = null
        pendingPickerDisplayName = null
        // Do not erase a verified room mapping because a file-picker or
        // attachment verification failed. That was cascading all subsequent
        // messages into "Wrong chat room" after the first failure.
        activeApiJob=null
        deepLinkRoutedJobId=null
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

    private fun screenBlockReason(root: AccessibilityNodeInfo?): String? {
        val pkg=root?.packageName?.toString().orEmpty()
        val labels=nodes(root).take(150).map { n ->
            (n.text?.toString().orEmpty()+" "+
             n.contentDescription?.toString().orEmpty()).lowercase()
        }.joinToString(" ")
        // A launcher ANR obscured the actual ChatGPT screen in the 2026-11-10
        // Android 15 emulator evidence. Do not treat the underlying activity
        // as an operable ChatGPT chat when this system dialog is on top.
        if(pkg=="android" && listOf(
            "isn't responding","is not responding","응답하지 않습니다"
        ).any { labels.contains(it) }) {
            return "EMULATOR_SYSTEM_ANR: system dialog obstructs ChatGPT; no action sent"
        }
        // A login entry in the top bar is not sufficient: demand the login
        // sheet's distinctive heading and Google-authentication button.
        if(pkg==chatPackage &&
           (labels.contains("log in or create an account") ||
            labels.contains("로그인하거나 계정을 만드세요")) &&
           (labels.contains("continue with google") ||
            labels.contains("google로 계속"))) {
            return "CHATGPT_LOGIN_REQUIRED: login sheet is active; chat IDs not verified"
        }
        return null
    }

    private fun withChatApp(id: String, work: () -> Unit) {
        val blocker=screenBlockReason(rootInActiveWindow)
        if(activeApiJob?.optString("id")==id && blocker!=null) {
            done(id,false,blocker)
            return
        }
        if(rootInActiveWindow?.packageName?.toString()==chatPackage) {
            progress(id, "공식 ChatGPT 화면 확인")
            work()
            return
        }
        // Once the official app left foreground we cannot prove that its
        // previously active conversation survived. Do not reuse the cache
        // after a launcher/app switch; deep-link again if needed.
        invalidateActiveConversationIdentity("ChatGPT foreground was lost")
        progress(id, "ChatGPT 앱 실행 요청")
        val intent=packageManager.getLaunchIntentForPackage(chatPackage)
        if(intent==null) { done(id,false,"Official ChatGPT is not installed"); return }
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        try {
            startActivity(intent)
        } catch (e: Exception) {
            done(id,false,"Android blocked ChatGPT launch: " + e.javaClass.simpleName)
            return
        }
        fun waitForApp(n: Int) {
            val blocker=screenBlockReason(rootInActiveWindow)
            if(activeApiJob?.optString("id")==id && blocker!=null) {
                done(id,false,blocker)
                return
            }
            if(rootInActiveWindow?.packageName?.toString()==chatPackage) {
                progress(id, "ChatGPT 실행 화면 활성")
                work()
            }
            else if(n>18) {
                val actual = rootInActiveWindow?.packageName?.toString() ?: "no-active-window"
                done(id,false,"ChatGPT foreground timeout, actual active package=" + actual)
            }
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
        // Direct console commands must obey the same dialog guard as API jobs.
        // An email field on the login sheet must never be mistaken for chat input.
        val blocker = screenBlockReason(root)
        if (blocker != null) {
            done(id, false, blocker)
            return
        }
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
        progress(id, "ChatGPT 입력창 발견")
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
        progress(id, "질문 텍스트 입력 완료")
        sendLog("Composer text inserted; resolving actual ChatGPT submit action")
        main.postDelayed({ submitAfterText(id, text, 0) }, 350)
    }

    private fun composerInput(all: List<AccessibilityNodeInfo>): AccessibilityNodeInfo? {
        // A login screen may expose an editable email/password field in the
        // same ChatGPT package. That field is NEVER a message composer.
        return all.filter { n ->
            if(!n.isEditable || !n.isVisibleToUser || !n.isEnabled) return@filter false
            val hint=(n.hintText?.toString().orEmpty()+" "+
                n.contentDescription?.toString().orEmpty()+" "+
                n.viewIdResourceName.orEmpty()).lowercase()
            if(listOf("email","e-mail","password","이메일","비밀번호",
                "전화번호","phone number","search history","대화 검색",
                "검색어").any {hint.contains(it)}) return@filter false
            val variant=n.inputType and android.text.InputType.TYPE_MASK_VARIATION
            val forbidden=setOf(
                android.text.InputType.TYPE_TEXT_VARIATION_EMAIL_ADDRESS,
                android.text.InputType.TYPE_TEXT_VARIATION_PASSWORD,
                android.text.InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD,
                android.text.InputType.TYPE_TEXT_VARIATION_WEB_EMAIL_ADDRESS,
                android.text.InputType.TYPE_TEXT_VARIATION_WEB_PASSWORD
            )
            variant !in forbidden
        }.maxByOrNull { n -> Rect().also { n.getBoundsInScreen(it) }.bottom }
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
        val distinct = nearby.distinctBy { n ->
            Rect().also { n.getBoundsInScreen(it) }.toShortString()
        }
        if (distinct.size == 1) return Pair(distinct.first(), "single_composer_adjacent_icon")
        if (distinct.size > 1) {
            val closest = distance(distinct[0])
            val second = distance(distinct[1])
            if (second - closest > (22 * dp).toInt()) {
                return Pair(distinct.first(), "clearly_nearest_composer_icon")
            }
        }
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
            progress(id, "전송 버튼 탐색 성공: " + candidate.second)
            val target = candidate.first
            sendLog("Submit target: " + candidate.second + ", node=" +
                (target.viewIdResourceName ?: "(no-id)") +
                ", desc=" + (target.contentDescription ?: "(no-desc)"))
            if (target.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
                progress(id, "전송 버튼 클릭 요청 완료")
                main.postDelayed({ verifySubmission(id, text, 0, candidate.second) }, 450)
                return
            }
            val bounds = Rect().also { target.getBoundsInScreen(it) }
            if (!bounds.isEmpty()) {
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
            if (attempt == 0) progress(id, "전송 버튼 노드 재탐색")
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
                progress(id, "전송 확인 · 입력창 비워짐")
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
        // Manual in-app chat switches invalidate the last relay-directed
        // conversation. Content/typing updates are NOT navigation.
        if(event.eventType==AccessibilityEvent.TYPE_VIEW_CLICKED &&
            (activeConversationId!=null || currentRoomId!=null)) {
            val n=event.source
            val label=listOf(n?.text?.toString().orEmpty(),
                n?.contentDescription?.toString().orEmpty(),
                n?.viewIdResourceName.orEmpty()).joinToString(" ").lowercase()
            val navigationButton=listOf("새 채팅","new chat","new conversation",
                "conversation_row","conversation_item","chat_history",
                "chat_row","history_item","new_chat")
                .any{label.contains(it)}
            val sidebarRow=selectedSidebarConversationTitle()!=null &&
                n?.isVisibleToUser==true && n.isClickable &&
                (n.text?.toString()?.trim()?.length ?: 0) in 3..170 &&
                n.text?.toString()?.trim() !in listOf("공유","복사","ChatGPT")
            if(navigationButton || sidebarRow)
                invalidateActiveConversationIdentity("manual sidebar/chat navigation")
        }
        if(event.eventType==AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED &&
            activeApiJob==null &&
            (activeConversationId!=null || currentRoomId!=null))
            invalidateActiveConversationIdentity("window navigation outside relay")
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
            listing.put(JSONObject().put("text",text).put("desc",desc)
                .put("id",n.viewIdResourceName ?: "")
                .put("selected",n.isSelected).put("checked",n.isChecked)
                .put("focused",n.isFocused)
                .put("stateDescription",
                    if(Build.VERSION.SDK_INT>=30)
                        n.stateDescription?.toString() ?: "" else "")
                .put("editable",n.isEditable).put("clickable",n.isClickable))
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

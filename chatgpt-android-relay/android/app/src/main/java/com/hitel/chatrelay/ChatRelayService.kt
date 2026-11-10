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
        val token = prefs.getString("token", "").orEmpty().ifBlank { "dpYZLhnMxOq02PNKGtTnBvzNSBAkLQ2Ip8zTzbEn" }
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
        if (currentRoomId == roomId) {
            progress(id,"현재 확인된 방에서 대화 이어가기: "+roomId)
            withChatApp(id) { sendChat(id,text) }
        } else if (androidState == "uncreated") {
            progress(id,"새 ChatGPT 채팅방 생성 요청: "+roomId)
            withChatApp(id) { createRoomThenSend(id,roomId,text,0) }
        } else {
            finishApiJob(id,false,"Existing Android conversation is not verified. Requested room="+roomId+
                "; current="+(currentRoomId ?: "unknown")+
                ". Exact in-app room switching must be mapped before sending.")
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


    // For an *existing* conversation, ACTION_SEND opens ChatGPT's general
    // intake rather than reliably attaching to the current thread. Use the
    // in-chat attachment menu and Android DocumentsUI instead.
    private fun pickFileInsideExistingRoom(job: JSONObject, staged: List<StagedAttachment>) {
        val jid = job.optString("id")
        val roomId = job.optJSONObject("room")?.optString("id").orEmpty()
        if (staged.size != 1) {
            finishApiJob(jid, false,
                "In-chat picker currently supports one file per job; submit individual files separately")
            return
        }
        if (currentRoomId != roomId) {
            finishApiJob(jid, false, "Target room is not current; in-chat picker refused")
            return
        }
        withChatApp(jid) {
            val anchor = roomLastPrompt
            if (anchor.length < 6 || anchor !in visibleConversationText()) {
                finishApiJob(jid, false,
                    "Cannot verify target conversation before opening its attachment picker")
                snapshot()
                return@withChatApp
            }
            shareRoomAnchor = anchor
            sharePreviewsBefore = composerAttachmentSignals()
            val stagedFile = staged[0]
            progress(jid, "기존 대화방 확인 완료 · Android 파일 선택기 준비")
            thread(start = true, name = "relay-media-publish") {
                var uri: Uri? = null
                var failed: String? = null
                val uniqueName = "relay_" + jid.removePrefix("job_").take(8) + "_" +
                    stagedFile.id.takeLast(6) + "_" + stagedFile.name
                try {
                    val content = ContentValues().apply {
                        put(MediaStore.MediaColumns.DISPLAY_NAME, uniqueName)
                        put(MediaStore.MediaColumns.MIME_TYPE, stagedFile.mime)
                        put(MediaStore.MediaColumns.RELATIVE_PATH,
                            Environment.DIRECTORY_DOWNLOADS + "/ChatGPTRelay")
                        put(MediaStore.MediaColumns.IS_PENDING, 1)
                    }
                    uri = contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, content)
                        ?: throw IllegalStateException("MediaStore Downloads insertion returned null")
                    contentResolver.openOutputStream(uri!!)?.use { output ->
                        stagedFile.file.inputStream().use { input -> input.copyTo(output) }
                    } ?: throw IllegalStateException("MediaStore output stream not available")
                    contentResolver.update(uri!!,
                        ContentValues().apply { put(MediaStore.MediaColumns.IS_PENDING, 0) },
                        null, null)
                } catch (e: Exception) {
                    failed = e.javaClass.simpleName + ": " + (e.message ?: "")
                }
                main.post {
                    if (activeApiJob?.optString("id") != jid) return@post
                    if (failed != null) {
                        finishApiJob(jid, false, "Could not stage file in Android Downloads: " + failed)
                        return@post
                    }
                    pendingPickerUri = uri
                    pendingPickerDisplayName = uniqueName
                    progress(jid, "Downloads/ChatGPTRelay에 파일 공개 · 첨부 버튼 탐색")
                    val attach = findComposerAttachButton()
                    if (attach == null || !attach.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
                        snapshot()
                        finishApiJob(jid, false, "ChatGPT attachment button was not found or not clickable")
                        return@post
                    }
                    main.postDelayed({ waitInChatPicker(jid, staged, 0, 0) }, 500)
                }
            }
        }
    }

    private fun findComposerAttachButton(): AccessibilityNodeInfo? {
        val all = nodes(rootInActiveWindow)
        val composer = composerInput(all) ?: return null
        val ir = Rect().also { composer.getBoundsInScreen(it) }
        val px = resources.displayMetrics.density
        return all.filter { n ->
            if (!n.isVisibleToUser) return@filter false
            val labels = accessibleLabel(n)
            val words = listOf("첨부파일", "파일 추가", "파일 첨부", "attach files",
                "add attachment", "add photos", "add files")
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
    private fun waitInChatPicker(jid: String, staged: List<StagedAttachment>,
                                 attempt: Int, menuStage: Int) {
        if (activeApiJob?.optString("id") != jid) return
        val root = rootInActiveWindow
        val pkg = root?.packageName?.toString().orEmpty()
        val all = nodes(root)
        val expected = pendingPickerDisplayName.orEmpty()
        if (pkg.isNotEmpty() && pkg != chatPackage) {
            if (pickerClickByNames(all, listOf(expected))) {
                progress(jid, "Android 파일 선택기에서 고유 파일명 확인 후 선택")
                main.postDelayed({ verifyFileShare(jid, staged, 0) }, 900)
                return
            }
            if (menuStage == 1 && pickerClickByNames(all,
                    listOf("다운로드", "Downloads", "Download"))) {
                progress(jid, "시스템 파일 선택기 Downloads 폴더 선택")
                main.postDelayed({ waitInChatPicker(jid, staged, attempt + 1, 2) }, 700)
                return
            }
            if (menuStage == 2 && pickerClickByNames(all, listOf("ChatGPTRelay"))) {
                progress(jid, "ChatGPTRelay 전용 폴더 선택")
                main.postDelayed({ waitInChatPicker(jid, staged, attempt + 1, 3) }, 700)
                return
            }
        } else if (pkg == chatPackage) {
            if (menuStage == 0) {
                // Prefer the system files picker over thumbnail grids, where
                // identifying a particular private upload is unreliable.
                if (pickerClickByNames(all, listOf("파일 업로드", "기기에서 파일",
                        "기기에서 업로드", "Browse files", "Upload files",
                        "Files", "파일", "문서"))) {
                    progress(jid, "ChatGPT 첨부 메뉴의 파일 선택 실행")
                    main.postDelayed({ waitInChatPicker(jid, staged, attempt + 1, 1) }, 650)
                    return
                }
            }
            if (menuStage > 0 && attempt > 3) {
                // ChatGPT has returned; the selected file may already appear
                // in the composer. Verify preview before submitting.
                val signals = composerAttachmentSignals()
                if (signals > sharePreviewsBefore) {
                    progress(jid, "ChatGPT에 첨부 미리보기 발견")
                    verifyFileShare(jid, staged, 0)
                    return
                }
            }
        }
        if (attempt % 5 == 0) {
            progress(jid, "첨부파일 선택기 탐색 · 화면=" + pkg + ", 단계=" + menuStage)
        }
        if (attempt < 24) {
            main.postDelayed({ waitInChatPicker(jid, staged, attempt + 1, menuStage) }, 500)
        } else {
            // Diagnostics are sent, but unknown UI controls are never clicked.
            snapshot()
            finishApiJob(jid, false,
                "In-chat file picker could not identify the uploaded filename. No question sent")
        }
    }

    private fun shareFilesIntoChatGpt(job: JSONObject, staged: List<StagedAttachment>) {
        val jid = job.optString("id")
        val room = job.optJSONObject("room")
        val roomId = room?.optString("id").orEmpty()
        val state = room?.optString("android_state", "uncreated").orEmpty()
        if (staged.isEmpty()) {
            finishApiJob(jid, false, "No files staged for sharing")
            return
        }
        if (state != "uncreated" && currentRoomId != roomId) {
            finishApiJob(jid, false, "Wrong chat room: cannot share into an unverified existing conversation")
            return
        }
        if (state == "active") {
            pickFileInsideExistingRoom(job, staged)
            return
        }
        withChatApp(jid) {
            if (state == "uncreated") {
                // Avoid carrying an attachment into a prior user's room.
                // ACTION_SEND opens ChatGPT's inbound share composer.
                shareRoomAnchor = ""
                progress(jid, "새 채팅방 이미지 공유 준비")
            } else {
                val anchor = roomLastPrompt
                if (anchor.length < 6 || visibleConversationText().none { it == anchor }) {
                    finishApiJob(jid, false,
                        "Prior room identity is not visible. Refusing unsafe attachment to another chat")
                    snapshot()
                    return@withChatApp
                }
                shareRoomAnchor = anchor
                progress(jid, "이전 대화 내용으로 대상 방 확인")
            }
            sharePreviewsBefore = composerAttachmentSignals()
            shareAttachmentCount = staged.size
            try {
                val uris = ArrayList<Uri>(staged.map { it.uri })
                val multiple = uris.size > 1
                val intent = Intent(if (multiple) Intent.ACTION_SEND_MULTIPLE else Intent.ACTION_SEND)
                intent.setClassName("com.openai.chatgpt", "com.openai.chatgpt.MainActivity")
                intent.type = if (staged.all { it.mime.startsWith("image/") }) "image/*"
                    else if (!multiple) staged[0].mime else "*/*"
                if (multiple) intent.putParcelableArrayListExtra(Intent.EXTRA_STREAM, uris)
                else intent.putExtra(Intent.EXTRA_STREAM, uris[0])
                val clip = ClipData.newUri(contentResolver, staged[0].name, uris[0])
                for (i in 1 until staged.size) {
                    clip.addItem(ClipData.Item(uris[i]))
                }
                intent.clipData = clip
                intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or
                    Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
                for (uri in uris) {
                    grantUriPermission("com.openai.chatgpt", uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
                }
                progress(jid, "ACTION_SEND로 ChatGPT에 이미지 및 읽기 권한 전달")
                startActivity(intent)
                main.postDelayed({ verifyFileShare(jid, staged, 0) }, 900)
            } catch (e: Exception) {
                finishApiJob(jid, false,
                    "Android ACTION_SEND failed: " + e.javaClass.simpleName + ": " + (e.message ?: ""))
            }
        }
    }

    private fun verifyFileShare(jid: String, staged: List<StagedAttachment>, attempt: Int) {
        if (activeApiJob?.optString("id") != jid) return
        val root = rootInActiveWindow
        val foreground = root?.packageName?.toString()
        if (foreground != chatPackage) {
            if (attempt < 24) {
                main.postDelayed({ verifyFileShare(jid, staged, attempt + 1) }, 500)
                return
            }
            finishApiJob(jid, false, "ChatGPT did not open after ACTION_SEND; foreground=" +
                (foreground ?: "(none)"))
            return
        }
        val all = nodes(root)
        val input = composerInput(all)
        val visible = visibleConversationText()
        if (shareRoomAnchor.isNotEmpty() && shareRoomAnchor !in visible) {
            // Share intent can open a different conversation. Do not leak data
            // across the user's separate chat sessions.
            finishApiJob(jid, false,
                "Share changed the active ChatGPT conversation. Original room not verified; question NOT sent")
            snapshot()
            return
        }
        val names = staged.map { it.name.lowercase() } +
            listOfNotNull(pendingPickerDisplayName?.lowercase())
        val strongLabel = all.any { n ->
            if (!n.isVisibleToUser || n.isEditable) return@any false
            val label = (n.text?.toString().orEmpty() + " " +
                n.contentDescription?.toString().orEmpty() + " " +
                n.viewIdResourceName.orEmpty()).lowercase()
            names.any { name ->
                name.length >= 5 && label.contains(name) &&
                !label.contains("relay-attachments")
            }
        }
        val signals = composerAttachmentSignals()
        val recognizableAttachment = strongLabel || (signals > sharePreviewsBefore)
        if (input != null && recognizableAttachment) {
            val rid = activeApiJob?.optJSONObject("room")?.optString("id").orEmpty()
            currentRoomId = rid
            progress(jid, "ChatGPT 접근성 화면에서 첨부 표시 확인")
            val text = activeApiJob?.optString("text").orEmpty()
            if (text.isNotBlank()) {
                sendChat(jid, text)
            } else {
                // An attachment without a prompt may only be staged, not sent.
                finishApiJob(jid, false,
                    "Attachment preview visible, but no question text to submit")
            }
            return
        }
        if (attempt % 5 == 0) {
            progress(jid, "ChatGPT 첨부 표시 확인 중: " + attempt +
                ", filename=" + strongLabel + ", preview=" + signals)
        }
        if (attempt < 24) {
            main.postDelayed({ verifyFileShare(jid, staged, attempt + 1) }, 500)
        } else {
            sendLog("Attachment verification timeout; please inspect ChatGPT share screen")
            snapshot()
            finishApiJob(jid, false,
                "ACTION_SEND delivered but ChatGPT attachment preview not verified. Question NOT sent")
        }
    }

    private fun responseCandidate(question: String): String {
        val data=nodes(rootInActiveWindow)
        val others=data.mapNotNull { n ->
            val value=n.text?.toString()?.trim().orEmpty()
            if(value.isBlank()||n.isEditable||n.isClickable||value==question.trim()||
                value in chrome||value.length>7000) null
            else if(value.contains("메뉴") && value.length<22) null
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
            roomLastPrompt=question
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
        val cleanup = pendingPickerUri
        if (cleanup != null) {
            main.postDelayed({
                try { contentResolver.delete(cleanup, null, null) }
                catch (ignored: Exception) { }
            }, 90000)
        }
        pendingPickerUri = null
        pendingPickerDisplayName = null
        if(!verified && currentRoomId==activeApiJob?.optJSONObject("room")?.optString("id"))
            currentRoomId=null
        activeApiJob=null
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
        if(rootInActiveWindow?.packageName?.toString()==chatPackage) {
            progress(id, "공식 ChatGPT 화면 확인")
            work()
            return
        }
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

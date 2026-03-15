package com.syncme.app

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED) return
        val prefs = context.getSharedPreferences("syncme", Context.MODE_PRIVATE)
        val server = prefs.getString(MainActivity.PREF_SERVER, "") ?: ""
        if (server.isEmpty()) return
        val svc = Intent(context, SyncMEService::class.java).apply {
            putExtra("server", server)
            putExtra("token",  prefs.getString(MainActivity.PREF_TOKEN, MainActivity.DEFAULT_TOKEN))
            putExtra("name",   prefs.getString(MainActivity.PREF_NAME,  Build.MODEL))
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O)
            context.startForegroundService(svc)
        else
            context.startService(svc)
    }
}

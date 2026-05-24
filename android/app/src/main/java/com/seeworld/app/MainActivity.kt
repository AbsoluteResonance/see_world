package com.seeworld.app

import android.Manifest
import android.app.AlertDialog
import android.content.Context
import android.content.pm.PackageManager
import android.os.Bundle
import android.webkit.*
import android.widget.EditText
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat

class MainActivity : AppCompatActivity() {
    private lateinit var webView: WebView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        webView = WebView(this)
        setContentView(webView)
        setupWebView()
        checkCameraPermission()
        loadSavedUrl()
    }

    private fun getSavedUrl(): String {
        val prefs = getPreferences(Context.MODE_PRIVATE)
        return prefs.getString("server_url", "") ?: ""
    }

    private fun saveUrl(url: String) {
        getPreferences(Context.MODE_PRIVATE).edit().putString("server_url", url).apply()
    }

    private fun loadSavedUrl() {
        var url = getSavedUrl()
        if (url.isBlank()) {
            url = "https://cluster-texts-edit-earnings.trycloudflare.com"
            showUrlDialog(url)
        } else {
            webView.loadUrl(url)
        }
    }

    private fun showUrlDialog(defaultUrl: String) {
        val input = EditText(this).apply { setText(defaultUrl) }
        AlertDialog.Builder(this)
            .setTitle("服务器地址")
            .setMessage("输入 MASt3R-SLAM 服务器地址")
            .setView(input)
            .setPositiveButton("确认") { _, _ ->
                val url = input.text.toString().trim()
                saveUrl(url)
                webView.loadUrl(url)
            }
            .setNegativeButton("默认") { _, _ ->
                saveUrl(defaultUrl)
                webView.loadUrl(defaultUrl)
            }
            .setCancelable(false)
            .show()
    }

    private fun setupWebView() {
        val settings = webView.settings
        settings.javaScriptEnabled = true
        settings.domStorageEnabled = true
        settings.allowFileAccess = true
        settings.mediaPlaybackRequiresUserGesture = false
        settings.cacheMode = WebSettings.LOAD_NO_CACHE

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            settings.safeBrowsingEnabled = false
        }

        webView.webViewClient = object : WebViewClient() {
            override fun onPageFinished(view: WebView?, url: String?) {
                super.onPageFinished(view, url)
            }
        }
        webView.webChromeClient = object : WebChromeClient() {
            override fun onPermissionRequest(request: PermissionRequest) {
                request.grant(request.resources)
            }
        }
    }

    private fun checkCameraPermission() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
            != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.CAMERA), 100)
        }
    }

    override fun onBackPressed() {
        if (webView.canGoBack()) webView.goBack()
        else super.onBackPressed()
    }
}

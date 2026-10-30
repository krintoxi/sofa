package uk.edgeventure.sofa

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.view.KeyEvent
import android.webkit.CookieManager
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import org.json.JSONArray
import org.json.JSONObject
import kotlin.concurrent.thread

/**
 * Sofa for Fire TV: Sofa's own TV pages in a full-screen web view (so it looks and works like Sofa,
 * remote and all), with videos handed to Android's own player (PlayerActivity), which plays MKV,
 * HEVC and Dolby sound as they are: the Sofa computer hardly ever has to convert anything.
 *
 * The first time, it finds Sofa on the network by itself (Discovery) or takes a typed address.
 */
class MainActivity : Activity() {
    private lateinit var web: WebView
    private lateinit var discovery: Discovery
    private val prefs by lazy { getSharedPreferences("sofa", MODE_PRIVATE) }

    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        discovery = Discovery(this)
        web = WebView(this)
        setContentView(web)
        with(web.settings) {
            javaScriptEnabled = true
            domStorageEnabled = true
            mediaPlaybackRequiresUserGesture = false
            loadWithOverviewMode = true
            useWideViewPort = true
            userAgentString = "$userAgentString SofaApp/1 (FireTV)"
        }
        CookieManager.getInstance().setAcceptCookie(true)
        web.webChromeClient = WebChromeClient()
        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val scheme = request.url.scheme ?: ""
                return scheme != "http" && scheme != "https" && scheme != "file"     // stay inside Sofa
            }

            override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
                if (request.isForMainFrame && !(request.url.scheme ?: "").startsWith("file")) {
                    showStart("Sofa didn't answer at ${server() ?: "that address"}. Is the Sofa computer on?")
                }
            }
        }
        web.addJavascriptInterface(Bridge(), "SofaNative")
        web.isFocusable = true
        web.isFocusableInTouchMode = true
        val saved = server()
        if (saved != null) open(saved) else showStart(null)
    }

    private fun server(): String? = prefs.getString("server", null)

    private fun open(base: String) {
        discovery.stop()
        web.loadUrl(base.trimEnd('/') + "/?tv=1")
        web.requestFocus()
    }

    private fun showStart(problem: String?) {
        web.loadUrl("file:///android_asset/start.html" + if (problem != null) "#" + Uri.encode(problem) else "")
        web.requestFocus()
        discovery.start()
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent): Boolean {
        if (keyCode == KeyEvent.KEYCODE_BACK) {
            if (web.canGoBack()) web.goBack() else moveTaskToBack(true)
            return true
        }
        return super.onKeyDown(keyCode, event)
    }

    override fun onDestroy() {
        discovery.stop()
        super.onDestroy()
    }

    @Deprecated("Activity results: the player says where it stopped")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        val result = data?.getStringExtra("result") ?: return
        web.evaluateJavascript("window.sofaNativeDone && window.sofaNativeDone($result)", null)
    }

    /** What Sofa's web app can ask of the app (window.SofaNative). Called off the main thread. */
    inner class Bridge {
        @JavascriptInterface
        fun version(): String = "1"

        @JavascriptInterface
        fun caps(): String = Codecs.caps().toString()

        @JavascriptInterface
        fun play(json: String) {
            runOnUiThread {
                val base = server() ?: return@runOnUiThread
                val intent = Intent(this@MainActivity, PlayerActivity::class.java)
                    .putExtra("payload", json)
                    .putExtra("base", base)
                    .putExtra("cookie", CookieManager.getInstance().getCookie(base) ?: "")
                @Suppress("DEPRECATION")
                startActivityForResult(intent, 1)
            }
        }

        @JavascriptInterface
        fun control(json: String) {
            runOnUiThread { PlayerActivity.current?.control(JSONObject(json)) }
        }

        @JavascriptInterface
        fun status(): String = PlayerActivity.status

        @JavascriptInterface
        fun servers(): String {
            val out = JSONArray()
            for ((name, url) in discovery.found()) out.put(JSONObject().put("name", name).put("url", url))
            return out.toString()
        }

        @JavascriptInterface
        fun choose(address: String) {
            thread {
                val base = Api.findSofa(address)
                runOnUiThread {
                    if (base != null) {
                        prefs.edit().putString("server", base).apply()
                        open(base)
                    } else {
                        web.evaluateJavascript("window.chooseFailed && window.chooseFailed()", null)
                    }
                }
            }
        }

        @JavascriptInterface
        fun forget() {
            runOnUiThread {
                prefs.edit().remove("server").apply()
                showStart(null)
            }
        }
    }
}

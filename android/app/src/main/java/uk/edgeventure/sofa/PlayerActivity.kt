package uk.edgeventure.sofa

import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.KeyEvent
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.FrameLayout
import android.widget.Toast
import androidx.annotation.OptIn
import androidx.media3.common.MediaItem
import androidx.media3.common.MimeTypes
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.ui.PlayerView
import org.json.JSONArray
import org.json.JSONObject
import kotlin.concurrent.thread

/**
 * Android's own player for Sofa's videos: the file as it is (MKV, HEVC, Dolby sound) when the device
 * plays it, Sofa's converted stream when it doesn't. Skip Intro, the remote's buttons, subtitles,
 * and watch progress saved to Sofa every 10 seconds.
 *
 * The payload (from Sofa's web app): {"item", "url", "title", "start", "offset", "duration", "subtitles":
 * [{"url", "lang", "label"}], "markers": [{"kind", "start", "end"}]}. Converted video starts where the person
 * left off: `offset` seconds into the episode is 0 in the stream, and `duration` is the whole episode's.
 */
@OptIn(UnstableApi::class)
class PlayerActivity : Activity() {
    companion object {
        var current: PlayerActivity? = null
        @Volatile var status: String = "{}"
    }

    private lateinit var player: ExoPlayer
    private lateinit var view: PlayerView
    private lateinit var skip: Button
    private val handler = Handler(Looper.getMainLooper())
    private var base = ""
    private var cookie = ""
    private var item = ""
    private var markers = JSONArray()
    private var offset = 0.0
    private var length = 0.0
    private var lastSave = 0L
    private var skipShownFor = ""
    private var finished = false

    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val payload = JSONObject(intent.getStringExtra("payload") ?: "{}")
        base = (intent.getStringExtra("base") ?: "").trimEnd('/')
        cookie = intent.getStringExtra("cookie") ?: ""
        item = payload.optString("item")
        markers = payload.optJSONArray("markers") ?: JSONArray()
        offset = payload.optDouble("offset", 0.0)
        length = payload.optDouble("duration", 0.0)

        val headers = HashMap<String, String>()
        if (cookie.isNotEmpty()) headers["Cookie"] = cookie
        val http = DefaultHttpDataSource.Factory()
            .setUserAgent("SofaApp/1")
            .setAllowCrossProtocolRedirects(true)
            .setDefaultRequestProperties(headers)
        player = ExoPlayer.Builder(this).setMediaSourceFactory(DefaultMediaSourceFactory(http)).build()

        view = PlayerView(this)
        view.player = player
        view.controllerShowTimeoutMs = 4000
        view.setShowSubtitleButton(true)
        view.keepScreenOn = true
        skip = Button(this).apply {
            text = "Skip Intro"
            setTextColor(Color.parseColor("#1A1405"))
            textSize = 20f
            isAllCaps = false
            background = GradientDrawable().apply { setColor(Color.parseColor("#F4B740")); cornerRadius = 40f }
            setPadding(48, 20, 48, 20)
            visibility = View.GONE
            setOnClickListener { skipPast() }
        }
        val root = FrameLayout(this)
        root.setBackgroundColor(Color.BLACK)
        root.addView(view, FrameLayout.LayoutParams(-1, -1))
        root.addView(skip, FrameLayout.LayoutParams(-2, -2, Gravity.BOTTOM or Gravity.END).apply { setMargins(0, 0, 80, 160) })
        setContentView(root)

        val subs = ArrayList<MediaItem.SubtitleConfiguration>()
        val list = payload.optJSONArray("subtitles") ?: JSONArray()
        for (i in 0 until list.length()) {
            val s = list.getJSONObject(i)
            subs.add(
                MediaItem.SubtitleConfiguration.Builder(Uri.parse(absolute(s.optString("url"))))
                    .setMimeType(MimeTypes.TEXT_VTT)
                    .setLanguage(s.optString("lang").ifEmpty { null })
                    .setLabel(s.optString("label").ifEmpty { null })
                    .build()
            )
        }
        val url = absolute(payload.optString("url"))
        val media = MediaItem.Builder()
            .setUri(url)
            .setSubtitleConfigurations(subs)
            .apply { if (url.contains(".m3u8")) setMimeType(MimeTypes.APPLICATION_M3U8) }
            // Sofa's converted video is a playlist that grows: never speed up to catch a "live" edge.
            .setLiveConfiguration(MediaItem.LiveConfiguration.Builder().setMinPlaybackSpeed(1f).setMaxPlaybackSpeed(1f).build())
            .build()
        player.setMediaItem(media, (payload.optDouble("start", 0.0) * 1000).toLong())
        player.addListener(object : Player.Listener {
            override fun onPlaybackStateChanged(state: Int) {
                if (state == Player.STATE_ENDED) done(true)
            }

            override fun onPlayerError(error: PlaybackException) {
                Toast.makeText(this@PlayerActivity, "This video can't play here: " + error.errorCodeName, Toast.LENGTH_LONG).show()
                done(false)
            }
        })
        player.prepare()
        player.playWhenReady = true
        current = this
        handler.post(ticker)
    }

    private fun absolute(u: String): String = if (u.startsWith("http")) u else base + u

    /** Where we are in the whole video, and how long it is (seconds). */
    private fun position(): Double = offset + player.currentPosition / 1000.0
    private fun total(): Double = if (length > 0) length else if (player.duration > 0) offset + player.duration / 1000.0 else 0.0

    private fun seekToAbsolute(t: Double) {
        player.seekTo(((t - offset) * 1000).toLong().coerceAtLeast(0))
    }

    private val ticker = object : Runnable {
        override fun run() {
            if (finished) return
            val t = position()
            val d = total()
            status = JSONObject().put("item", item).put("t", t.toInt()).put("d", d.toInt()).put("paused", !player.isPlaying).toString()
            val intro = activeMarker(t)
            if (intro != null) {
                if (skip.visibility != View.VISIBLE) {
                    skip.text = if (intro.optString("kind") == "recap") "Skip Recap" else "Skip Intro"
                    skip.visibility = View.VISIBLE
                    val key = intro.optString("kind") + intro.optDouble("start")
                    if (skipShownFor != key) { skipShownFor = key; skip.requestFocus() }
                }
            } else if (skip.visibility == View.VISIBLE) {
                skip.visibility = View.GONE
            }
            if (d > 0 && System.currentTimeMillis() - lastSave > 10_000) {
                lastSave = System.currentTimeMillis()
                save(t, d, false)
            }
            handler.postDelayed(this, 1000)
        }
    }

    private fun activeMarker(t: Double): JSONObject? {
        for (i in 0 until markers.length()) {
            val m = markers.getJSONObject(i)
            val kind = m.optString("kind")
            if ((kind == "intro" || kind == "recap") && t >= m.optDouble("start") && t < m.optDouble("end") - 1) return m
        }
        return null
    }

    private fun skipPast() {
        val m = activeMarker(position()) ?: return
        seekToAbsolute(m.optDouble("end"))
        skip.visibility = View.GONE
    }

    private fun save(t: Double, d: Double, done: Boolean) {
        val (b, c, i) = Triple(base, cookie, item)
        thread { Api.progress(b, c, i, t, d, done) }
    }

    private fun seekBy(seconds: Int) {
        player.seekTo((player.currentPosition + seconds * 1000L).coerceAtLeast(0))
    }

    /** From Sofa's web app (the phone remote). */
    fun control(c: JSONObject) {
        when (c.optString("cmd")) {
            "toggle" -> player.playWhenReady = !player.playWhenReady
            "pause" -> player.pause()
            "resume" -> player.play()
            "seek" -> seekToAbsolute(c.optDouble("t", 0.0))
            "skip" -> seekBy(c.optInt("by", 0))
            "next" -> done(true)
            "stop" -> done(false)
        }
    }

    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        if (event.action == KeyEvent.ACTION_DOWN) {
            val controls = view.isControllerFullyVisible
            when (event.keyCode) {
                KeyEvent.KEYCODE_BACK -> {
                    if (controls) view.hideController() else done(false)
                    return true
                }
                KeyEvent.KEYCODE_MEDIA_FAST_FORWARD -> { seekBy(30); return true }
                KeyEvent.KEYCODE_MEDIA_REWIND -> { seekBy(-10); return true }
                KeyEvent.KEYCODE_DPAD_RIGHT -> if (!controls && !skip.isFocused) { seekBy(30); return true }
                KeyEvent.KEYCODE_DPAD_LEFT -> if (!controls && !skip.isFocused) { seekBy(-10); return true }
            }
        }
        return view.dispatchKeyEvent(event) || super.dispatchKeyEvent(event)
    }

    private fun done(ended: Boolean) {
        if (finished) return
        finished = true
        val t = position()
        val d = total()
        val watched = ended || (d > 0 && t > d * 0.95)
        if (d > 0) save(if (watched) d else t, d, watched)
        status = "{}"
        setResult(RESULT_OK, Intent().putExtra("result",
            JSONObject().put("item", item).put("t", t).put("d", d).put("ended", ended).put("done", watched).toString()))
        finish()
    }

    override fun onPause() {
        super.onPause()
        if (!finished) player.pause()
    }

    override fun onDestroy() {
        handler.removeCallbacks(ticker)
        if (!finished) {
            finished = true
            val d = total()
            if (d > 0) save(position(), d, false)
        }
        if (current === this) current = null
        status = "{}"
        player.release()
        super.onDestroy()
    }
}

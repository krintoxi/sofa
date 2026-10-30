package uk.edgeventure.sofa

import android.media.MediaCodecList
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/** The few calls the app makes itself (the rest is Sofa's own pages). */
object Api {
    /** Sofa's /api/info at `base`, or null when it isn't Sofa (or doesn't answer). */
    fun info(base: String): JSONObject? = try {
        val c = URL(base.trimEnd('/') + "/api/info").openConnection() as HttpURLConnection
        c.connectTimeout = 3000
        c.readTimeout = 3000
        c.inputStream.use { stream ->
            val json = JSONObject(stream.bufferedReader().readText())
            if (json.optBoolean("sofa")) json else null
        }
    } catch (e: Exception) {
        null
    }

    /** A typed address ("192.168.1.20", "imac.local:8090", "http://…") -> the Sofa it points at, or null. */
    fun findSofa(typed: String): String? {
        var t = typed.trim().trimEnd('/')
        if (t.isEmpty()) return null
        if (!t.startsWith("http://") && !t.startsWith("https://")) t = "http://$t"
        val candidates = if (Regex(":\\d+$").containsMatchIn(t)) listOf(t) else listOf("$t:8090", t)
        return candidates.firstOrNull { info(it) != null }
    }

    /** Save watch progress (the player does this itself, so it's kept even if the app is closed). */
    fun progress(base: String, cookie: String, item: String, t: Double, d: Double, done: Boolean) {
        try {
            val c = URL(base.trimEnd('/') + "/api/progress/" + URLEncoder.encode(item, "UTF-8")).openConnection() as HttpURLConnection
            c.requestMethod = "POST"
            c.doOutput = true
            c.connectTimeout = 4000
            c.readTimeout = 4000
            c.setRequestProperty("Content-Type", "application/json")
            c.setRequestProperty("X-Sofa", "1")
            if (cookie.isNotEmpty()) c.setRequestProperty("Cookie", cookie)
            c.outputStream.use { it.write(JSONObject().put("t", t).put("d", d).put("done", done).toString().toByteArray()) }
            c.responseCode
            c.disconnect()
        } catch (e: Exception) {
        }
    }
}

/** What this device's own player handles, so Sofa only converts what it really has to. */
object Codecs {
    fun caps(): JSONObject {
        val types = HashSet<String>()
        try {
            for (info in MediaCodecList(MediaCodecList.REGULAR_CODECS).codecInfos) {
                if (!info.isEncoder) types.addAll(info.supportedTypes.map { it.lowercase() })
            }
        } catch (e: Exception) {
        }
        return JSONObject()
            .put("mkv", true)
            .put("hevc", "video/hevc" in types)
            .put("ac3", "audio/ac3" in types || "audio/eac3" in types)
            .put("vp9", "video/x-vnd.on2.vp9" in types)
    }
}

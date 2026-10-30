package uk.edgeventure.sofa

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.net.wifi.WifiManager
import java.net.DatagramPacket
import java.net.InetAddress
import java.net.MulticastSocket
import java.net.SocketTimeoutException
import java.util.concurrent.ConcurrentHashMap
import kotlin.concurrent.thread

/**
 * Finding Sofa on the home network, two ways at once: Bonjour ("_sofa._tcp", what the Sofa computer
 * announces) and an SSDP search that Sofa answers. Found servers: name -> "http://address:port".
 */
class Discovery(private val context: Context) {
    private val servers = ConcurrentHashMap<String, String>()
    private var nsd: NsdManager? = null
    private var listener: NsdManager.DiscoveryListener? = null
    private var lock: WifiManager.MulticastLock? = null
    private val resolving = java.util.ArrayDeque<NsdServiceInfo>()
    private var busy = false
    @Volatile private var running = false

    fun found(): Map<String, String> = HashMap(servers)

    fun start() {
        if (running) return
        running = true
        val wifi = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
        lock = wifi.createMulticastLock("sofa").apply { setReferenceCounted(false); acquire() }
        startBonjour()
        thread(isDaemon = true) { ssdpLoop() }
    }

    fun stop() {
        if (!running) return
        running = false
        try { listener?.let { nsd?.stopServiceDiscovery(it) } } catch (e: Exception) { }
        listener = null
        try { lock?.release() } catch (e: Exception) { }
    }

    private fun startBonjour() {
        val manager = context.getSystemService(Context.NSD_SERVICE) as NsdManager
        nsd = manager
        val l = object : NsdManager.DiscoveryListener {
            override fun onDiscoveryStarted(serviceType: String) {}
            override fun onDiscoveryStopped(serviceType: String) {}
            override fun onStartDiscoveryFailed(serviceType: String, errorCode: Int) {}
            override fun onStopDiscoveryFailed(serviceType: String, errorCode: Int) {}
            override fun onServiceLost(service: NsdServiceInfo) {}
            override fun onServiceFound(service: NsdServiceInfo) {
                synchronized(resolving) { resolving.add(service) }
                resolveNext()
            }
        }
        listener = l
        try {
            manager.discoverServices("_sofa._tcp", NsdManager.PROTOCOL_DNS_SD, l)
        } catch (e: Exception) {
            listener = null
        }
    }

    /** Older Android resolves one service at a time. */
    private fun resolveNext() {
        val next: NsdServiceInfo
        synchronized(resolving) {
            if (busy || resolving.isEmpty()) return
            busy = true
            next = resolving.poll() ?: return
        }
        @Suppress("DEPRECATION")
        nsd?.resolveService(next, object : NsdManager.ResolveListener {
            override fun onResolveFailed(info: NsdServiceInfo, errorCode: Int) {
                synchronized(resolving) { busy = false }
                resolveNext()
            }

            override fun onServiceResolved(info: NsdServiceInfo) {
                val host = info.host?.hostAddress
                if (host != null && !host.contains(":")) servers[info.serviceName] = "http://$host:${info.port}"
                synchronized(resolving) { busy = false }
                resolveNext()
            }
        })
    }

    private fun ssdpLoop() {
        val search = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\nMX: 2\r\n" +
            "ST: urn:sofa-media:device:Sofa:1\r\n\r\n").toByteArray()
        try {
            MulticastSocket().use { socket ->
                socket.soTimeout = 1500
                val group = InetAddress.getByName("239.255.255.250")
                while (running) {
                    socket.send(DatagramPacket(search, search.size, group, 1900))
                    val buf = ByteArray(2048)
                    val until = System.currentTimeMillis() + 3000
                    while (running && System.currentTimeMillis() < until) {
                        try {
                            val packet = DatagramPacket(buf, buf.size)
                            socket.receive(packet)
                            val text = String(packet.data, 0, packet.length)
                            val location = Regex("(?im)^LOCATION:\\s*(\\S+)").find(text)?.groupValues?.get(1) ?: continue
                            val base = Regex("^(https?://[^/]+)").find(location)?.groupValues?.get(1) ?: continue
                            if (servers.values.none { it == base }) {
                                thread(isDaemon = true) { Api.info(base)?.let { servers[it.optString("name", "Sofa")] = base } }
                            }
                        } catch (e: SocketTimeoutException) {
                            break
                        }
                    }
                    Thread.sleep(4000)
                }
            }
        } catch (e: Exception) {
        }
    }
}

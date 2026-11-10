#!/bin/sh
# Runs inside a test copy of the Sofa box VM image (tools/boot-sofa-box-vm.sh puts it there as a service): the checks,
# each printed as one "SOFA-BOX-PROOF <what>: ok|fail <detail>" line on the console, then "SOFA-BOX-PROOF done" and
# the VM switches itself off. Never on a real box: only the boot test installs it.
AGENT=http://127.0.0.1:8091
SOFA=http://127.0.0.1:8095
say() { echo "SOFA-BOX-PROOF $*"; }
wait_for() {                 # wait_for NAME SECONDS COMMAND…: the command succeeds within the time, or not
  secs="$2"; shift 2                                 # ($1 names the check, for the reader)
  end=$(( $(date +%s) + secs ))
  while :; do
    if "$@" >/dev/null 2>&1; then return 0; fi
    [ "$(date +%s)" -lt "$end" ] || return 1
    sleep 2
  done
}
say "start: $(. /etc/os-release; echo "$PRETTY_NAME"), kernel $(uname -r), $(awk '/MemTotal/ {printf "%d MB", $2/1024}' /proc/meminfo), virtualised: $(systemd-detect-virt 2>/dev/null || echo ?)"

# 1. the box's helper (the home screen, apps, player, settings) on its port
if wait_for agent 240 curl -fs -m 3 "$AGENT/box/state"; then
  say "agent: ok $AGENT/box/state answers"
  INFO="$(curl -fs -m 40 "$AGENT/box/api/info" 2>/dev/null)"   # (box_info asks bluetoothctl and iwgetid, up to 5 s each)
  if echo "$INFO" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["version"]; print(d["version"], d.get("model"), d.get("os"), d["board"]["gen"])' >"/tmp/info" 2>/dev/null; then
    say "home api: ok /box/api/info: Sofa Box OS $(cat /tmp/info)"
  else
    say "home api: fail /box/api/info: $(echo "$INFO" | head -c 200)"
  fi
  HOME_PAGE="$(curl -fs -m 5 -o /dev/null -w '%{http_code}' "$AGENT/box/home")"
  [ "$HOME_PAGE" = 200 ] && say "home page: ok /box/home is $HOME_PAGE" || say "home page: fail /box/home is $HOME_PAGE"
else
  say "agent: fail nothing on $AGENT after 4 minutes ($(systemctl is-active sofa-box-agent); $(journalctl -u sofa-box-agent -n 5 --no-pager -o cat | tr '\n' ' ' | head -c 300))"
fi

# 2. Sofa on the box ("This box"): started by the helper the first time it's asked for, through the helper's own door
curl -fs -m 20 -o /dev/null -H 'Host: box.localhost' "$AGENT/api/info" 2>/dev/null || true
if wait_for sofa 120 curl -fs -m 3 "$SOFA/api/info"; then
  SI="$(curl -fs -m 5 "$SOFA/api/info")"
  if echo "$SI" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("sofa"); print(d.get("version") or d.get("sofa"))' > /tmp/sofa 2>/dev/null; then
    say "sofa: ok $SOFA/api/info: Sofa $(cat /tmp/sofa)"
  else
    say "sofa: fail $SOFA/api/info isn't Sofa: $(echo "$SI" | head -c 200)"
  fi
  TB="$(curl -fs -m 5 -o /dev/null -w '%{http_code}' -H 'Host: box.localhost' "$AGENT/api/info")"
  [ "$TB" = 200 ] && say "sofa through the home screen: ok box.localhost:8091/api/info is $TB" || say "sofa through the home screen: fail $TB"
else
  say "sofa: fail nothing on $SOFA after 2 minutes ($(tail -n 3 /home/sofabox/.local/share/sofa-box/sofa/sofa.log 2>/dev/null | tr '\n' ' ' | head -c 300))"
fi

# 3. the TV's screen: cage with Chromium, which answers the helper on its DevTools port
if wait_for screen 180 sh -c 'systemctl is-active --quiet sofa-box.service && pgrep -x cage >/dev/null && curl -fs -m 3 http://127.0.0.1:9222/json/version >/dev/null'; then
  say "screen: ok sofa-box.service active, cage running, Chromium's DevTools port answers ($(curl -fs -m 3 http://127.0.0.1:9222/json/version | python3 -c 'import json,sys; print(json.load(sys.stdin).get("Browser"))' 2>/dev/null))"
else
  say "screen: fail sofa-box.service $(systemctl is-active sofa-box.service), cage $(pgrep -x cage >/dev/null && echo running || echo not running), devtools $(curl -fs -m 3 -o /dev/null -w '%{http_code}' http://127.0.0.1:9222/json/version); $(journalctl -u sofa-box -n 8 --no-pager -o cat | tr '\n' ' ' | head -c 400)"
fi

# What the TV's screen said, line by line (SOFA-BOX-LOG lines never count as failed checks)
journalctl -u sofa-box -b --no-pager -o cat 2>/dev/null | grep -v '^$' | tail -n 60 | cut -c1-300 | sed 's/^/SOFA-BOX-LOG sofa-box: /'
echo "SOFA-BOX-LOG processes: $(pgrep -a -f 'cage|chromium' | cut -c1-160 | tr '\n' ';' | head -c 900)"
echo "SOFA-BOX-LOG run/user: $(ls /run/user 2>/dev/null | tr '\n' ' '); display file: $(cat /run/user/*/sofa-box-display 2>/dev/null | tr '\n' ' ')"
echo "SOFA-BOX-LOG chromium flags: $(sh -c '. /etc/chromium.d/sofa-box 2>/dev/null; echo $CHROMIUM_FLAGS')"

# 4. the rest of the box, for the record
for s in sofa-box-agent sofa-box sofa-box-input sofa-box-tune NetworkManager; do
  say "service $s: $(systemctl is-active "$s")"
done
say "cec: $(systemctl is-active sofa-box-cec) (a VM has no HDMI-CEC: the service waits for a /dev/cec; condition: $(systemctl show -p ConditionResult --value sofa-box-cec))"
say "phone remote: $(curl -fs -m 3 -o /dev/null -w '%{http_code}' http://127.0.0.1:8092/) on 8092"
say "disk: $(df -h / | awk 'NR==2 {print $2" root, "$4" free"}'), partition grown: $(systemctl is-active systemd-repart 2>/dev/null || echo ?)"
say "decoder: $(ls /dev/dri 2>/dev/null | tr '\n' ' '); vainfo: $(vainfo --display drm 2>&1 | grep -c VAProfile) profiles (a VM has no VA-API decoder: expected 0)"
say "doctor: $(/usr/local/lib/sofa-box/sofa-box doctor 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -E '✓|✗' | tr '\n' ';' | head -c 900)"
say "done"
sleep 2
systemctl poweroff

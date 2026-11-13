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
# how it was started: UEFI or BIOS, and with Secure Boot on or not (the firmware's own SecureBoot variable: its last byte)
if [ -d /sys/firmware/efi ]; then
  SB="$(od -An -t u1 /sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c 2>/dev/null | awk '{print $NF}')"
  say "firmware: UEFI, Secure Boot $([ "$SB" = 1 ] && echo on || echo off)"
  if [ -f /etc/sofa-box-vm-secure-boot ]; then
    [ "$SB" = 1 ] && say "secure boot: ok started by shim, GRUB and the kernel, each checked by the firmware" \
      || say "secure boot: fail the firmware says Secure Boot is off"
  fi
else
  say "firmware: BIOS"
fi

# 0. Install on this computer (boot-sofa-box-vm.sh --install-onto): this start is from the USB stick, with a blank drive
#    beside it. The agent is asked for its drives and the install started the way Settings does it on the TV (the two
#    yeses are the TV's part), followed to the end; then off, and the host starts the PC from the drive alone.
if [ -f /etc/sofa-box-vm-install-to ]; then
  TO="$(cat /etc/sofa-box-vm-install-to)"
  rm -f /etc/sofa-box-vm-install-to                  # (not copied with the rest: the drive starts as a box, not a test)
  say "install: from $(findmnt -no SOURCE /) ($(lsblk -dno TRAN "/dev/$(lsblk -no PKNAME "$(findmnt -no SOURCE /)" | head -n 1)" 2>/dev/null)) onto $TO"
  if wait_for agent 240 curl -fs -m 3 "$AGENT/box/state"; then
    curl -fs -m 30 "$AGENT/box/api/install" > /tmp/drives 2>/dev/null
    if python3 - "$TO" > /tmp/pick 2>/tmp/why <<'EOF'
import json, sys
d = json.load(open("/tmp/drives"))
assert d["from_stick"], "the agent doesn't see a PC running from a stick: %r" % {k: d.get(k) for k in ("pc", "from_stick")}
x = [v for v in d["drives"] if v["disk"] == sys.argv[1]]
assert x, "%s isn't in the list: %r" % (sys.argv[1], d["drives"])
assert not x[0]["why_not"], x[0]["why_not"]
print(json.dumps({"disk": x[0]["disk"], "serial": x[0]["serial"], "size": x[0]["size"]}))
EOF
    then
      say "install list: ok runs from the stick; offered: $(python3 -c 'import json; print("; ".join("%s %s %d GB %s" % (v["disk"], v["model"], v["size"] // 10**9, v["why_not"] or "ok") for v in json.load(open("/tmp/drives"))["drives"]))')"
      R="$(curl -fs -m 30 -X POST -H 'X-Sofa-Box: 1' -H 'Content-Type: application/json' -d "$(cat /tmp/pick)" "$AGENT/box/api/install")"
      echo "SOFA-BOX-LOG install asked: $R"
      END=$(( $(date +%s) + 1500 )) STATE="" LAST=""
      while [ "$(date +%s)" -lt "$END" ]; do
        STATE="$(python3 -c 'import json; print(json.load(open("/run/sofa-box-install.json"))["state"])' 2>/dev/null)"
        NOW="$(python3 -c 'import json; d=json.load(open("/run/sofa-box-install.json")); print(d["step"], d["percent"], d["message"])' 2>/dev/null)"
        [ "$NOW" != "$LAST" ] && [ -n "$NOW" ] && case "$NOW" in copy*) ;; *) echo "SOFA-BOX-LOG install: $NOW" ;; esac
        LAST="$NOW"
        [ "$STATE" = done ] || [ "$STATE" = failed ] && break
        sleep 5
      done
      MSG="$(python3 -c 'import json; print(json.load(open("/run/sofa-box-install.json"))["message"])' 2>/dev/null)"
      journalctl -b -u sofa-box-install-to-disk --no-pager -o cat 2>/dev/null | grep -v '^$' | grep -v ': Copying: ' | tail -n 40 | cut -c1-300 \
        | sed 's/^/SOFA-BOX-LOG installer: /'
      if [ "$STATE" = done ]; then
        say "install: ok $MSG"
        AFTER="$(curl -fs -m 30 "$AGENT/box/api/install" | python3 -c 'import json,sys; d=json.load(sys.stdin); print([v["disk"] for v in d["drives"] if v["installed"]])' 2>/dev/null)"
        echo "$AFTER" | grep -q "$TO" && say "install remembered: ok the stick knows it's on $TO now" \
          || say "install remembered: fail the agent's list after: $AFTER"
      else
        say "install: fail ${STATE:-never started}: $MSG"
      fi
    else
      say "install list: fail $(head -c 600 /tmp/why | tr '\n' ' ')"
    fi
  else
    say "agent: fail nothing on $AGENT after 4 minutes ($(systemctl is-active sofa-box-agent))"
  fi
  say "done"
  sleep 2
  systemctl poweroff
  exit 0
fi
# A start from the drive it was installed on (boot-sofa-box-vm.sh, after the install): the root is that drive's
if [ -f /etc/sofa-box-vm-installed ]; then
  WANT="$(cat /etc/sofa-box-vm-installed)" HAVE="/dev/$(lsblk -no PKNAME "$(findmnt -no SOURCE /)" | head -n 1)"
  if [ "$HAVE" = "$WANT" ] && [ -s /etc/sofa-box-installed ]; then
    say "installed: ok the root is on $HAVE: $(cat /etc/sofa-box-installed)"
  else
    say "installed: fail the root is on $HAVE (not $WANT), /etc/sofa-box-installed: $(cat /etc/sofa-box-installed 2>/dev/null || echo missing)"
  fi
  say "start list: $(efibootmgr 2>/dev/null | grep -E '^Boot(Current|Order)|sofabox' | tr '\n' ';' || echo "no UEFI start list (BIOS)")"
fi

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

# 3. the TV's screen: cage with Chromium, which answers the helper on its DevTools port, with Home open
for c in /sys/class/drm/card*-*; do [ -e "$c/status" ] && say "display $(basename "$c"): $(cat "$c/status"), $(head -n 1 "$c/modes" 2>/dev/null || echo "no modes")"; done
if wait_for screen 240 sh -c 'systemctl is-active --quiet sofa-box.service && pgrep -x cage >/dev/null && curl -fs -m 3 http://127.0.0.1:9222/json/version >/dev/null'; then
  sleep 20                                            # (Home's first draw)
  say "screen: ok sofa-box.service active, cage running, Chromium's DevTools port answers ($(curl -fs -m 3 http://127.0.0.1:9222/json/version | python3 -c 'import json,sys; print(json.load(sys.stdin).get("Browser"))' 2>/dev/null)); pages: $(curl -fs -m 5 http://127.0.0.1:9222/json | python3 -c 'import json,sys; print("; ".join("%s <%s>" % (p.get("title"), p.get("url")) for p in json.load(sys.stdin)))' 2>/dev/null | head -c 300)"
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
# written to a bigger stick than the image (boot-sofa-box-vm.sh --disk): the root has the whole of it, less the boot parts
if [ -f /etc/sofa-box-vm-disk-bytes ]; then
  WANT="$(cat /etc/sofa-box-vm-disk-bytes)"
  HAVE="$(df -B1 --output=size / | tail -n 1 | tr -d ' ')"
  if [ "$HAVE" -ge $(( WANT - 700 * 1024 * 1024 )) ]; then
    say "grown: ok the root is $((HAVE / 1048576)) MB of a $((WANT / 1048576)) MB disk"
  else
    say "grown: fail the root is $((HAVE / 1048576)) MB of a $((WANT / 1048576)) MB disk ($(journalctl -b -u systemd-repart -u systemd-growfs-root -n 6 --no-pager -o cat | tr '\n' ' ' | head -c 300))"
  fi
fi
say "decoder: $(ls /dev/dri 2>/dev/null | tr '\n' ' '); vainfo: $(vainfo --display drm 2>&1 | grep -c VAProfile) profiles (a VM has no VA-API decoder: expected 0)"
say "doctor: $(/usr/local/lib/sofa-box/sofa-box doctor 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -E '✓|✗' | tr '\n' ';' | head -c 900)"
say "done"
sleep 2
systemctl poweroff

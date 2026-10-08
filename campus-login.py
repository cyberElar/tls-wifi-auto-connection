#!/usr/bin/python3
"""Log an interface in to the campus Sangfor AC portal (4.3.2.1) from the
command line -- the same request the login page's "Login" button sends.
Runs on Windows 11, macOS, and Linux (Fedora).

  campus-login.py -u USER -p PASS            log the interface in
  campus-login.py -u USER -p PASS --save     ...and keep the credentials in the
                                             --cred file with private permissions
  campus-login.py --save-only               prompt and save without using the network
  campus-login.py                            use the saved credentials
  campus-login.py --status                   only report whether it is logged in

The page RC4-encrypts the password with the current time in milliseconds as
the key and sends that time along as auth_tag (logic_new.js, onPwdLogin and
do_encrypt_rc4); rc4_hex reproduces it byte for byte.

Every request is bound to the interface's own address and ignores the proxy
environment. On Fedora that is what keeps it out of FlClash: the TUN's policy
rules only claim local sockets with an unbound source (`from 0.0.0.0 iif lo`),
and the shell exports http_proxy pointing at FlClash's 7890. The status probe
is a bare IP for the same reason -- a name would be answered from fake-ip.
On Windows, IP_UNICAST_IF also selects the outgoing Wi-Fi interface. This
does not change system routes or disable the VPN.
"""
import argparse
import ast
import getpass
import http.client
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
import urllib.parse

if platform.system() == "Windows":
    import campus_login_windows as windows

PORTAL = "http://4.3.2.1/ac_portal/login.php"
# AliDNS answers plain HTTP on its anycast address with a 404 when the network
# is open; behind the portal the same request is 302'd to 4.3.2.1/ac_portal.
PROBE = "http://223.5.5.5/"
DEFAULT_IFACE = {"Darwin": "en1", "Windows": None}.get(platform.system(), "wlp0s20f3")


def rc4_hex(src, key):
    src, key = src.strip(), str(key)
    sbox = list(range(256))
    j = 0
    for i in range(256):
        j = (j + sbox[i] + ord(key[i % len(key)])) % 256
        sbox[i], sbox[j] = sbox[j], sbox[i]
    a = b = 0
    out = []
    for ch in src:
        a = (a + 1) % 256
        b = (b + sbox[a]) % 256
        sbox[a], sbox[b] = sbox[b], sbox[a]
        out.append("%02x" % (ord(ch) ^ sbox[(sbox[a] + sbox[b]) % 256]))
    return "".join(out)


def source_address(iface):
    if platform.system() == "Windows":
        return windows.select_adapter(iface).address
    if platform.system() == "Darwin":
        cmd = ["ipconfig", "getifaddr", iface]
        return subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
    out = subprocess.run(["ip", "-4", "-o", "addr", "show", "dev", iface],
                         capture_output=True, text=True).stdout.split()
    return out[out.index("inet") + 1].split("/")[0] if "inet" in out else ""


def curl(src, *args):
    return subprocess.run(["curl", "-s", "--noproxy", "*", "--interface", src] + list(args),
                          capture_output=True, text=True).stdout


def state(src, iface=None):
    """online, portal, or unknown (no answer at all -- not yet associated)."""
    if platform.system() == "Windows":
        try:
            _, redirect, _ = windows.request(src, PROBE, 5, iface=iface, read_body=False)
        except (OSError, ValueError, http.client.HTTPException):
            return "unknown"
        return "portal" if "ac_portal" in redirect else "online"
    out = curl(src, "--max-time", "5", "-o", os.devnull,
               "-w", "%{http_code} %{redirect_url}", PROBE).split()
    if not out or out[0] == "000":
        return "unknown"
    return "portal" if len(out) > 1 and "ac_portal" in out[1] else "online"


class PortalLiterals(ast.NodeTransformer):
    """Allow JSON literals in the portal's single-quoted object notation."""
    def visit_Name(self, node):
        values = {"true": True, "false": False, "null": None}
        if node.id not in values:
            raise ValueError("unexpected name in portal response")
        return ast.Constant(value=values[node.id])


def login(src, user, pwd, iface=None):
    tag = str(int(time.time() * 1000))
    body = urllib.parse.urlencode({"opr": "pwdLogin", "userName": user,
                                   "pwd": rc4_hex(pwd, tag), "auth_tag": tag,
                                   "rememberPwd": "1"})
    if platform.system() == "Windows":
        try:
            _, _, out = windows.request(
                src, PORTAL, 10, body=body.encode("ascii"), iface=iface,
                headers={"X-Requested-With": "XMLHttpRequest",
                         "Content-Type": "application/x-www-form-urlencoded"},
            )
        except (OSError, ValueError, http.client.HTTPException) as error:
            return {"success": False, "msg": "request failed: %s" % error}
    else:
        out = curl(src, "--max-time", "10", "-H", "X-Requested-With: XMLHttpRequest",
                   "--data", body, PORTAL)
    try:
        reply = json.loads(out)
    except ValueError:
        # Preserve apostrophes in valid JSON; never execute a portal response.
        try:
            reply = ast.literal_eval(PortalLiterals().visit(ast.parse(out, mode="eval")))
        except (ValueError, SyntaxError):
            reply = None
    if not isinstance(reply, dict):
        return {"success": False, "msg": "unparseable reply: %r" % out[:200]}
    return reply


def current_network(iface):
    """Connection profile and SSID active on this interface."""
    if platform.system() == "Windows":
        return windows.current_network(windows.select_adapter(iface))
    out = subprocess.run(["nmcli", "-t", "-f", "GENERAL.CONNECTION", "device", "show", iface],
                         capture_output=True, text=True).stdout.strip()
    name = out.split(":", 1)[1] if ":" in out else ""
    ssid = ""
    for line in subprocess.run(["nmcli", "-t", "-f", "ACTIVE,SSID", "device", "wifi", "list",
                                "ifname", iface, "--rescan", "no"],
                               capture_output=True, text=True).stdout.splitlines():
        if line.startswith("yes:"):
            ssid = line[4:]
    return name, ssid


def load_cred(path):
    with open(path, encoding="utf-8-sig") as stream:
        saved = json.load(stream)
    if not isinstance(saved, dict) or any(not isinstance(saved.get(field), str) or
                                         not saved[field].strip() for field in ("user", "password")):
        raise ValueError("expected non-empty user and password strings")
    return saved["user"], saved["password"]


def save_cred(path, user, password):
    path = os.path.abspath(path)
    fd, temporary = tempfile.mkstemp(prefix=".campus-login-", dir=os.path.dirname(path))
    os.close(fd)
    try:
        if platform.system() == "Windows":
            windows.protect_credential(temporary)
        with open(temporary, "w", encoding="utf-8") as stream:
            json.dump({"user": user, "password": password}, stream)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def watch(args):
    # Two speeds: a quick look every few seconds right after joining, because
    # that is when the portal stands between the user and everything; then a
    # slow check once logged in, which only exists to catch a session that the
    # portal expires underneath us. Off campus it does nothing but ask
    # NetworkManager which network this is.
    last_net, failures, last_error = None, 0, None
    while True:
        try:
            name, ssid = current_network(args.iface)
            src = source_address(args.iface) if args.watch in (name, ssid) else ""
            last_error = None
        except (OSError, subprocess.TimeoutExpired) as error:
            message = str(error)
            if message != last_error:
                print("%s: network check failed: %s" % (args.iface, message), flush=True)
            last_error = message
            time.sleep(15)
            continue
        on_campus = args.watch in (name, ssid)
        if on_campus != (last_net == args.watch):
            failures = 0
        last_net = args.watch if on_campus else name
        if not on_campus:
            time.sleep(15)
            continue
        now = state(src, args.iface) if src else "unknown"
        if now == "online":
            failures = 0
            time.sleep(60)
            continue
        if now == "unknown":
            time.sleep(5)
            continue
        try:
            user, pwd = load_cred(args.cred)
        except Exception as e:
            print("no usable credentials in %s: %s" % (args.cred, e), flush=True)
            time.sleep(300)
            continue
        reply = login(src, user, pwd, args.iface)
        time.sleep(2)
        if state(src, args.iface) == "online":
            print("%s: logged in to %s" % (args.iface, args.watch), flush=True)
            failures = 0
            continue
        failures += 1
        print("%s: login failed (%s)" % (args.iface, reply.get("msg") or "no message"), flush=True)
        # A wrong password retried every few seconds can lock the account;
        # back off to at most once every 10 minutes.
        time.sleep(min(600, 10 * 2 ** min(failures, 6)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-u", "--user")
    ap.add_argument("-p", "--password")
    ap.add_argument("-i", "--iface", default=DEFAULT_IFACE)
    ap.add_argument("--cred", default=os.path.expanduser("~/.campus-login"))
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--save-only", action="store_true", help="prompt and save credentials without contacting the network")
    ap.add_argument("--list-interfaces", action="store_true", help="list Windows adapters and exit")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--wait", type=int, default=0,
                    help="seconds to keep retrying while the network is not "
                         "answering yet (right after association)")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--watch", metavar="NETWORK",
                    help="stay running (the background service): whenever the "
                         "interface is on this connection name or SSID and the "
                         "portal is in the way, log in. Logs only logins.")
    args = ap.parse_args()

    if args.list_interfaces:
        if platform.system() != "Windows":
            ap.error("--list-interfaces is only available on Windows")
        for adapter in windows.adapters():
            print("%s: %s%s" % (adapter.name, adapter.address or "no IPv4 address",
                                " (Wi-Fi)" if adapter.kind == 71 else ""))
        return

    # Saved before anything else, so --save works even when already online.
    if args.save or args.save_only:
        args.user = args.user or input("Campus username: ").strip()
        args.password = args.password or getpass.getpass("Campus password: ")
        if not args.user.strip() or not args.password.strip():
            sys.exit("user and password must not be empty")
        save_cred(args.cred, args.user, args.password)
        if args.save_only:
            print("Credentials saved to %s" % args.cred)
            return

    if platform.system() == "Windows" and not args.iface and not args.watch:
        args.iface = windows.select_adapter().name

    if args.watch:
        watch(args)
        return

    deadline = time.time() + args.wait
    while True:
        src = source_address(args.iface)
        now = state(src, args.iface) if src else "unknown"
        if now != "unknown" or time.time() >= deadline:
            break
        time.sleep(3)

    if args.status:
        print("%s: %s" % (args.iface, now))
        sys.exit(0 if now == "online" else 1)
    if now == "online":
        args.quiet or print("%s: already online" % args.iface)
        return
    if now == "unknown":
        sys.exit("%s: no answer from the network (address %r)" % (args.iface, src))

    user, pwd = args.user, args.password
    if not (user and pwd):
        try:
            saved_user, saved_password = load_cred(args.cred)
            user, pwd = user or saved_user, pwd or saved_password
        except Exception:
            sys.exit("no credentials: pass -u/-p (add --save to keep them)")

    reply = login(src, user, pwd, args.iface)
    time.sleep(2)
    ok = state(src, args.iface) == "online"
    msg = reply.get("msg") or ""
    print("%s: %s%s" % (args.iface, "logged in" if ok else "login failed",
                        (" (%s)" % msg) if msg and not ok else ""))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    try:
        main()
    except (OSError, subprocess.TimeoutExpired) as error:
        sys.exit(str(error))
    except KeyboardInterrupt:
        sys.exit(130)

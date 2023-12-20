#!/usr/bin/python3

# This file is part of INSECA.
#
#    Copyright (C) 2020-2023 INSECA authors
#
#    INSECA is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    INSECA is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with INSECA.  If not, see <https://www.gnu.org/licenses/>

#
# If the /opt/share/proxy-pac-url file exists, then:
#  - if the URL specified in that file exists (and returns a WPAD file), then a
#    web server listening on port 8088 is started using that WPAD file.
#  - if the URL can't be reached, then no web server is started (it is stopped it it was)
#    running
#
# Else, a web server listening on port 8088 is started:
#   If the /opt/share/proxy.pac file exists, then it is used by the Web server, otherwise a
#   dummy WPAD which always return a DIRECT "route" is used
# 
#
# When started, the Web server answers the following:
# - GET /current-proxy/<destination>: the web proxy to use to reach <destination> (if specified), like for example:
#    - "DIRECT" => don't use a proxy (make a direct connection to the target server)
#    - "PROXY proxy.example:3200" => use http://proxy.example:3200
#    - "PROXY proxy1.example:3200; PROXY proxy2.example:8080" => use either http://proxy.example:3200 or http://proxy2.example:8080
# - GET /* => the WPAD data otherwise
#
# See also: https://developer.mozilla.org/en-US/docs/Web/HTTP/Proxy_servers_and_tunneling/Proxy_Auto-Configuration_PAC_file
#

import sys
import os
import json
import time
import errno
import requests
import http.server
import urllib.parse
import socket
import socketserver
import threading
import syslog
import signal
import subprocess

port=8088
prefix="/opt/share"

def get_ip():
    s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("1.1.1.1", 53)) # we don't care if not reacheable
        #print("IP: %s"%s.getsockname()[0])
        return s.getsockname()[0]
    except:
        return "127.0.0.1"
    finally:
        s.close()

# determine URL of the remote proxy PAC server to use
remote_url=None
userdata_file=f"{prefix}/proxy-pac-url"
if os.path.exists(userdata_file):
    try:
        userdata=json.load(open(userdata_file, "r"))
        remote_url=userdata["pac-url"].strip()
        if remote_url=="":
            remote_url=None
        syslog.syslog(syslog.LOG_INFO, f"proxy WPAD will be fetched using '{remote_url}'")
    except Exception as e:
        syslog.syslog(syslog.LOG_ERR, "Error loading USERDATA file '%s': %s"%(userdata_file, str(e)))
        remote_url=None

def _fetch_remote():
    """Download the data from the remote proxy PAC server"""
    if not remote_url:
        return None
    counter=0
    while counter<3:
        try:
            r=requests.get(remote_url, timeout=5)
            if r.ok:
                return r.content
        except Exception:
            pass
        counter+=1
        time.sleep(1)
    return None


# https://stackoverflow.com/questions/21631799/how-can-i-pass-parameters-to-a-requesthandler/52046062
def HandlerClassFactory(data):
    class HttpRequestHandler(http.server.SimpleHTTPRequestHandler):
        """PAC server request handler"""
        def __init__(self, *args, **kwargs):
            self._pac_data=data
            if not self._pac_data:
                path=f"{prefix}/proxy.pac"
                if os.path.exists(path):
                    self._pac_data=open(path, "r").read()
                if self._pac_data:
                    syslog.syslog(syslog.LOG_INFO, f"proxy WPAD is from the '{path}' file")
                else:
                    syslog.syslog(syslog.LOG_INFO, f"proxy WPAD is the dummy DIRECT one")
                    self._pac_data="""function FindProxyForURL(url, host) {return "DIRECT";}"""
            if isinstance(self._pac_data, bytes):
                self._pac_data=self._pac_data.decode()
            super(HttpRequestHandler, self).__init__(*args, **kwargs)

        def do_GET(self):
            # send back response
            if self.path.startswith("/current-proxy"):
                import pacparser
                pacparser.init()
                pacparser.parse_pac_string(self._pac_data)
                pacparser.setmyip(get_ip())
                where=self.path[14:]
                if where in ("", "/"):
                    where="www.microsoft.com"
                else:
                    parts=urllib.parse.urlparse(f"http://{where[1:]}")
                    where=parts.netloc
                proxy=pacparser.find_proxy(f"http://{where}")
                self.send_response(200)
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                self.wfile.write(bytes(proxy, "utf8"))
            else:
                self.send_response(200)
                self.send_header("Content-type", "application/x-ns-proxy-autoconfig")
                self.end_headers()
                self.wfile.write(bytes(self._pac_data, "utf8"))
    return HttpRequestHandler

class PacServer(threading.Thread):
    """Thread in which the PAC server is executed"""
    def __init__(self, data):
        threading.Thread.__init__(self)
        self._server=None
        self._data=data

    def run(self):
        syslog.syslog(syslog.LOG_INFO, "starting PAC server...")
        handler_class=HandlerClassFactory(self._data)
        counter=0
        while True:
            try:
                self._server=socketserver.TCPServer(("127.0.0.1", port), handler_class)
                self._server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self._server.serve_forever(poll_interval=1)
                return
            except OSError as e:
                if e.errno==errno.EADDRINUSE:
                    counter+=1
                    if counter>60:
                        syslog.syslog(syslog.LOG_ERR, "Could not start PAC server: %s"%str(e))
                        raise e
                    time.sleep(2)
                else:
                    syslog.syslog(syslog.LOG_ERR, "Could not start PAC server: %s"%str(e))
                    raise e

    def stop(self):
        syslog.syslog(syslog.LOG_INFO, "stopping PAC server...")
        self._server.shutdown()


if remote_url:
    # use NetworkManager's monitor program
    # handling of network events
    server=None
    def update_server_state():
        global server
        data=_fetch_remote()
        if data:
            # remote proxy WPAD data fetched
            syslog.syslog(syslog.LOG_INFO, "fetched remote proxy WPAD data")
            if not server:
                syslog.syslog(syslog.LOG_INFO, "creating new PacServer")
                server=PacServer(data)
                server.start()
        else:
            # no fetched proxy WPAD data
            syslog.syslog(syslog.LOG_INFO, "could not fetch remote proxy WPAD data (no local server will run)")
            if server:
                syslog.syslog(syslog.LOG_INFO, "requesting PAC server stop")
                server.stop()
                server.join()
                syslog.syslog(syslog.LOG_INFO, "PAC server is now stopped")
                server=None

    def handler(signum, frame):
        update_server_state()
    signal.signal(signal.SIGALRM, handler)

    update_server_state()
    p=subprocess.Popen(["ip", "monitor", "route"], stdout=subprocess.PIPE, bufsize=1, text=True)
    while True:
        out=p.stdout.read(1)
        if out=="" and p.poll() is not None:
            break
        if out!="":
            signal.alarm(3)
    p.stdout.close()
    p.wait()

else:
    syslog.syslog(syslog.LOG_INFO, "Starting very simple Proxy PAC server")
    handler_class=HandlerClassFactory(None)
    server=socketserver.TCPServer(("127.0.0.1", port), handler_class)
    server.serve_forever(poll_interval=3600)

sys.exit(0)

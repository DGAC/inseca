#!/usr/bin/python3

# This file is part of INSECA.
#
#    Copyright (C) 2020-2022 INSECA authors
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
# This script always return the proxy.pac file
#

import sys
import os
import json
import time
import errno
import socket
import requests
import http.server
import socketserver
import threading
import syslog


# determine URL of the remote proxy PAC server to use
try:
    userdata_file="/opt/share/proxy-pac-url"
    userdata=json.load(open(userdata_file, "r"))
    remote_url=userdata["pac-url"].strip()
    if remote_url=="":
        remote_url=None
except Exception as e:
    syslog.syslog(syslog.LOG_ERR, "Error loading USERDATA file '%s': %s"%(userdata_file, str(e)))
    remote_url=None
syslog.syslog(syslog.LOG_INFO, "Proxy.pac remote_url: %s"%remote_url)

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
                path="/opt/share/proxy.pac"
                if os.path.exists(path):
                    self._pac_data=open(path, "r").read()
                if not self._pac_data:
                    self._pac_data="""function FindProxyForURL(url, host) {return "DIRECT";}"""
            if isinstance(self._pac_data, bytes):
                self._pac_data=self._pac_data.decode()
            super(HttpRequestHandler, self).__init__(*args, **kwargs)

        def do_GET(self):
            # send back response
            time.sleep(3) # wait for the server to have time to stop in case the network config. has changed
                          # and for example a web browser wants to know the new proxy settings. Otherwise
                          # we might still give the previous (now invalid) proxy settings
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
                self._server=socketserver.TCPServer(("127.0.0.1", 8088), handler_class)
                #self._server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
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
    # monitor NetworkManager through its DBus interfaces
    from gi.repository import GLib
    import dbus
    import dbus.mainloop.glib

    NM_DBUS_NAME = "org.freedesktop.NetworkManager"
    NM_DBUS_PATH = "/org/freedesktop/NetworkManager"
    NM_DBUS_INTERFACE = "org.freedesktop.NetworkManager"

    # handling of network events
    server=None
    def update_server_state():
        global server
        print("Timed out")
        data=_fetch_remote()
        if data:
            # remote proxy.pac data fetched
            syslog.syslog(syslog.LOG_INFO, "fetched remote proxy.pac data")
            if not server:
                syslog.syslog(syslog.LOG_INFO, "creating new PacServer")
                server=PacServer(data)
                server.start()
        else:
            # no fetched proxy.pac data
            syslog.syslog(syslog.LOG_INFO, "could not fetch remote proxy.pac data")
            if server:
                syslog.syslog(syslog.LOG_INFO, "requesting PAC server stop")
                server.stop()
                server.join()
                syslog.syslog(syslog.LOG_INFO, "PAC server is now stopped")
                server=None

        net_state_changed_cb.tid=None
        return False # don't keep the timer

    def net_state_changed_cb(dummy):
        """Function called when the NM's properties change, it can be called several times in a short amount of
        time => use a timer to run the update_server_state() function"""
        if net_state_changed_cb.tid is None:
            print("Properties Changed, running timer")
            net_state_changed_cb.tid=GLib.timeout_add(500, update_server_state) # "aggregate" several property notifications in
                                                                                # one call to update_server_state()
    net_state_changed_cb.tid=None

    # set up NetworkManager monitoring
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    sessionBus = dbus.SystemBus()
    nm_proxy=sessionBus.get_object(NM_DBUS_NAME, NM_DBUS_PATH)
    nm_proxy.connect_to_signal("PropertiesChanged", net_state_changed_cb, dbus_interface=NM_DBUS_INTERFACE)

    loop=GLib.MainLoop()
    net_state_changed_cb(None)
    loop.run()
else:
    syslog.syslog(syslog.LOG_INFO, "Starting very simple Proxy PAC server")
    handler_class=HandlerClassFactory(None)
    server=socketserver.TCPServer(("127.0.0.1", 8088), handler_class)
    server.serve_forever(poll_interval=3600)

sys.exit(0)

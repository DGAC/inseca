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

# cf. https://web.mit.edu/source/debathena/config/gdm-config/debian/debathena-nologin-monitor

import syslog
import os
import tarfile
import signal
import time
import Live
import Utils as util

from gi.repository import GLib
import dbus
import dbus.mainloop.glib

SM_DBUS_NAME = "org.gnome.SessionManager"
SM_DBUS_PATH = "/org/gnome/SessionManager"
SM_DBUS_INTERFACE = "org.gnome.SessionManager"
SM_CLIENT_DBUS_INTERFACE = "org.gnome.SessionManager.ClientPrivate"
APP_ID = "inseca-config-backup"

#
# Session end actions
#
class Backup:
    def __init__(self):
        self._live_env=Live.Environ()
        self._live_env.define_UI_environment()
        self._logs_dir="/internal/logs"
        self._logs_max_size=100*1024*1024 # 100Mib

    @property
    def uid(self):
        return self._live_env.uid

    def shutdown(self):
        # components
        try:
            syslog.syslog(syslog.LOG_INFO, "Shutdown components")
            self._shutdown_components()
        except Exception as e:
            syslog.syslog(syslog.LOG_ERR, "Shutdown components failed: %s"%str(e))

    def backup(self):
        # user 'preferences'
        try:
            syslog.syslog(syslog.LOG_INFO, "Backup user config")
            self._live_env.user_config_backup()
        except Exception as e:
            syslog.syslog(syslog.LOG_ERR, "Backup user config failed: %s"%str(e))

        # logs
        try:
            self._purge_old_logs()
        except Exception as e:
            syslog.syslog(syslog.LOG_ERR, "Failed to purge old logs: %s"%str(e))

        try:
            syslog.syslog(syslog.LOG_INFO, "Backup logs")
            self._backup_logs()
        except:
            pass
        try:
            self._purge_old_logs()
        except:
            pass

    def _purge_old_logs(self):
        """Remove old logs"""
        if not os.path.exists(self._logs_dir):
            return

        # make a list of files, ordered by creation date (earliest last)
        files={}
        for logfile in os.listdir(self._logs_dir):
            fname="%s/%s"%(self._logs_dir, logfile)
            stat=os.stat(fname)
            files[stat.st_mtime]=fname

        # remove files to ensure the cumulated logs' size remains below the maximum
        timestamps=list(files.keys())
        timestamps.sort(reverse=True)
        cumul=0
        for ts in timestamps:
            fname=files[ts]
            if cumul<=self._logs_max_size:
                stat=os.stat(fname)
                cumul+=stat.st_size
            if cumul>self._logs_max_size:
                os.remove(fname)

    def _backup_logs(self):
        os.makedirs(self._logs_dir, exist_ok=True)
        os.chmod(self._logs_dir, 0o700)
        logfile="%s/logs-%s.txz"%(self._logs_dir, util.get_timestamp())
        tarobj=tarfile.open(logfile, mode='w:xz')
        tarobj.add("/var/log", arcname=".", recursive=True)
        tarobj.close()

    def _shutdown_components(self):
        # shudown all the components if there is a shutdown script
        exec_env=os.environ.copy()
        exec_env["PYTHONPATH"]=os.path.dirname(__file__)
        comp_live_config_dir=self._live_env.components_live_config_dir
        components=os.listdir(comp_live_config_dir)
        for component in components:
            script="%s/%s/shutdown.py"%(comp_live_config_dir, component)
            if os.path.exists(script):
                exec_env["USERDATA_DIR"]="/internal/components/%s"%component
                (status, out, err)=util.exec_sync([script], exec_env=exec_env)
                if status==0:
                    syslog.syslog(syslog.LOG_INFO, "Executed the shutdown script for componeent '%s'"%component)
                else:
                    syslog.syslog(syslog.LOG_ERR, "Error executing the shutdown script for componeent '%s': %s"%(component, err))

def QueryEndSession_cb(flags):
    #print("QueryEndSession received")
    syslog.syslog(syslog.LOG_INFO, "Possible end of session, starting backup")
    backup.backup()
    client_proxy.EndSessionResponse(True, "", dbus_interface=SM_CLIENT_DBUS_INTERFACE)

def EndSession_cb(flags):
    #print("EndSession received")
    client_proxy.EndSessionResponse(True, "", dbus_interface=SM_CLIENT_DBUS_INTERFACE)

def CancelEndSession_cb():
    #print("CancelEndSession received")
    pass

def Stop_cb():
    #print("Stop received")
    backup.shutdown()
    loop.quit()

def term_handler(sig, frame):
    backup.shutdown()
    loop.quit()

signal.signal(signal.SIGTERM, term_handler)

# DBUS stuff

dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

while True:
    try:
        backup=Backup()
        os.seteuid(backup.uid) # switch to connected user, required to connect to the session bus
        sessionBus = dbus.SessionBus()
        mngr_proxy=sessionBus.get_object(SM_DBUS_NAME, SM_DBUS_PATH)
        smClientId=mngr_proxy.RegisterClient(APP_ID, "", dbus_interface=SM_DBUS_INTERFACE)

        client_proxy=sessionBus.get_object(SM_DBUS_NAME, smClientId)
        client_proxy.connect_to_signal("QueryEndSession", QueryEndSession_cb, dbus_interface=SM_CLIENT_DBUS_INTERFACE)
        client_proxy.connect_to_signal("EndSession", EndSession_cb, dbus_interface=SM_CLIENT_DBUS_INTERFACE)
        client_proxy.connect_to_signal("CancelEndSession", CancelEndSession_cb, dbus_interface=SM_CLIENT_DBUS_INTERFACE)
        client_proxy.connect_to_signal("Stop", Stop_cb, dbus_interface=SM_CLIENT_DBUS_INTERFACE)
        break
    except Exception as e:
        syslog.syslog(syslog.LOG_WARNING, "Can't connect to the session manager (so we wait a bit): %s"%str(e))
        time.sleep(1)

os.seteuid(0) # back to root

loop=GLib.MainLoop()
syslog.syslog(syslog.LOG_INFO, "Starting main loop...")
loop.run()

exit(0)

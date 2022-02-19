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

import sys
import signal
import syslog
import Utils as util

#
# Killer
#
def start_killer_counter(seconds=15):
    def handler(signum, frame):
        syslog.syslog(syslog.LOG_INFO, "Powering OFF now")
        util.exec_sync(["/sbin/poweroff"])
        sys.exit(0)

    # Set the signal handler and a X second alarm
    signal.signal(signal.SIGALRM, handler)
    signal.alarm(seconds)
    syslog.syslog(syslog.LOG_INFO, "Started killer (%s seconds)"%seconds)

def stop_killer_counter():
    signal.alarm(0)
    syslog.syslog(syslog.LOG_INFO, "Stopped killer")

#
# High level networking
#
def enable_networking():
    (status, out, err)=util.exec_sync(["nmcli", "networking", "on"])

def disable_networking():
    (status, out, err)=util.exec_sync(["nmcli", "networking", "off"])

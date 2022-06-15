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

import syslog
import Live
import Utils as util

# force the usage of the local proxy.pac server
try:
    env=Live.Environ()
    env.define_UI_environment()
    env.user_setting_set("org.gnome.system.proxy", "autoconfig-url", "http://127.0.0.1:8088/proxy.pac")
    env.user_setting_set("org.gnome.system.proxy", "mode", "auto")
    syslog.syslog(syslog.LOG_INFO, "Proxy setting has been forced")
except Exception as e:
    syslog.syslog(syslog.LOG_ERR, "Could not set the user's proxy: %s"%str(e))

# start the proxy-pac service (in the .1 stage to let the proxy-pac-url component copy its USERDATA)
(status, out, err)=util.exec_sync(["systemctl", "start", "inseca-proxy-pac"])
if status!=0:
    syslog.syslog(syslog.LOG_ERR, "Could not start the inseca-proxy-pac service: %s"%err)
else:
    syslog.syslog(syslog.LOG_INFO, "Started the inseca-proxy-pac service")
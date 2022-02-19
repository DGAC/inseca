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

import os
import syslog
import json
import shutil
import Utils as util

# load OpenVPN config file if any
resfile="%s/userdata.json"%os.environ["USERDATA_DIR"]
user_friendly_ovpn_file="%s/VPN.ovpn"%os.environ["USERDATA_DIR"]

if os.path.exists(resfile):
    component_conf=json.load(open(resfile, "r"))
    path=component_conf["ovpn-file"]
    if path is not None:
        ovpn_file="%s/%s"%(os.environ["USERDATA_DIR"], path)
        syslog.syslog(syslog.LOG_INFO, "OVPN file to load: %s"%ovpn_file)
        shutil.copyfile(ovpn_file, user_friendly_ovpn_file)
        args=["nmcli", "connection", "import", "type", "openvpn", "file", user_friendly_ovpn_file]
        (status, out, err)=util.exec_sync(args)
        if status!=0:
            syslog.syslog(syslog.LOG_ERR, "Could not import OVPN config file '%s': %s"%(user_friendly_ovpn_file, err))
        else:
            syslog.syslog(syslog.LOG_INFO, "OVPN config file '%s' imported"%user_friendly_ovpn_file)

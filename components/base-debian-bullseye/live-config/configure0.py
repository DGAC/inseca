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
import os
import Live
import Utils as util

# load pre-defined UI settings from any dconf.xxx files (in the alphabetical order)
live_env=Live.Environ()
live_env.define_UI_environment()

optfiles=os.listdir("/opt")
optfiles.sort()
for fname in optfiles:
    if fname.startswith("dconf."):
        dconf_file="/opt/%s"%fname
        if os.path.exists(dconf_file):
            data=util.load_file_contents(dconf_file)
            os.seteuid(live_env.uid) # switch to user
            (status, out, err)=util.exec_sync(["dconf", "load", "/"], stdin_data=data)
            if status!=0:
                syslog.syslog(syslog.LOG_ERR, "Could not load DConf settings file '%s': %s"%(dconf_file, err))
            else:
                syslog.syslog(syslog.LOG_INFO, "Loaded DConf settings from '%s'"%dconf_file)
            os.seteuid(0) # back to root

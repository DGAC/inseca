#!/usr/bin/python3

import os
import syslog
import Utils as util

# force stopping of any runnig VM
syslog.syslog(syslog.LOG_INFO, "Discarding all guest-os VMs") 
prog="/usr/share/fairshell/virt-system/vm-tool.py"
if os.path.exists(prog):
    util.exec_sync([prog, "discard-all"])

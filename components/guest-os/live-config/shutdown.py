#!/usr/bin/python3

import os
import Utils as util

# force stopping of any runnig VM
prog="/usr/share/fairshell/virt-system/vm-tool.py"
if os.path.exists(prog):
    util.exec_sync([prog, "discard-all"])

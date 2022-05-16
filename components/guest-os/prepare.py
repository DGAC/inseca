#!/usr/bin/python3

# This file is part of INSECA.
#
#    Copyright (C) 2022 INSECA authors
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
import json
import shutil

# check all expected parameters are present
conf=json.load(open(os.environ["CONF_DATA_FILE"], "r"))
for key in ["config"]:
    if key not in conf:
        raise Exception("No '%s' attribute in the build configuration"%key)

# copy the config file
destdir="%s/etc"%os.environ["PRIVDATA_DIR"]
os.makedirs(destdir, exist_ok=True)
shutil.copyfile("%s/%s"%(os.environ["CONF_DIR"], conf["config"]), "%s/fairshell-virt-system.json"%destdir)

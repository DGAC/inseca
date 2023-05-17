#!/usr/bin/python3

# This file is part of INSECA.
#
#    Copyright (C) 2023 INSECA authors
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
import Utils as util

conf=json.load(open(os.environ["CONF_DATA_FILE"], "r"))
for key in ["packages"]:
    if key not in conf:
        raise Exception("No '%s' attribute in the build configuration"%key)

packages=conf["packages"]

if packages:
    live_dir=os.environ["LIVE_DIR"]
    data=[]
    for pack in packages.split(","):
        data+=[pack.strip()]
    util.write_data_to_file("\n".join(data)+"\n", "%s/etc/inseca-flatpak-packages"%live_dir)

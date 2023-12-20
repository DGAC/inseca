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
import shutil

# create the /opt/share/proxy-pac-url file
conf=json.load(open(os.environ["CONF_DATA_FILE"], "r"))
destdir=f"{os.environ['PRIVDATA_DIR']}/opt/share"
os.makedirs(destdir, exist_ok=True)

pacurl=conf["pac-url"]
with open(f"{destdir}/proxy-pac-url", "w") as fd:
    data={
        "pac-url": pacurl
    }
    fd.write(json.dumps(data))


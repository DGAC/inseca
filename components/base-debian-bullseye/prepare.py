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
import Utils as util

# create the /etc/docker/daemon.json file in PRIVDATA_DIR
conf=json.load(open(os.environ["CONF_DATA_FILE"], "r"))
key="docker-bip"
if key in conf:
    data={
        "bip": conf[key]
    }
    destdir="%s/etc/docker"%os.environ["PRIVDATA_DIR"]
    os.makedirs(destdir, exist_ok=True)
    util.write_data_to_file(json.dumps(data), "%s/daemon.json"%destdir, perms=0o600)

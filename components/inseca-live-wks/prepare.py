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
import json
import shutil
import Utils as util

conf=json.load(open(os.environ["CONF_DATA_FILE"], "r"))
for key in ["userdata-skey-pub-file"]:
    if key not in conf:
        raise Exception("No '%s' attribute in the build configuration"%key)

destdir="%s/opt/share"%os.environ["PRIVDATA_DIR"]
os.makedirs(destdir, exist_ok=True)

# userdata-skey-pub-file
file="%s/%s"%(os.environ["CONF_DIR"], conf["userdata-skey-pub-file"])
shutil.copyfile(file, "%s/userdata-skey.pub"%destdir)
pubkey=util.load_file_contents(file)
util.write_data_to_file("USERDATA signing public key: %s"%pubkey, os.environ["BUILD_DATA_FILE"], append=True)

# data/ mapping configuration
map_data={
    "": "/home/insecauser/Documents"
}
util.write_data_to_file(json.dumps(map_data), "%s/inseca-data-map.json"%destdir)

# other config. elements
protected_conf={
    "allowed-virtualized": conf.get("allowed-virtualized", ""),
    "disable-inseca-services": conf.get("disable-inseca-services", ""),
    "allow-network-connections": conf.get("allow-network-connections", True)
}
util.write_data_to_file(json.dumps(protected_conf), "%s/etc/inseca-live.json"%os.environ["LIVE_DIR"])
util.write_data_to_file("Allowed virtual environments: %s\n"%protected_conf["allowed-virtualized"], os.environ["BUILD_DATA_FILE"], append=True)
util.write_data_to_file("Disabled net services: %s\n"%protected_conf["disable-inseca-services"], os.environ["BUILD_DATA_FILE"], append=True)
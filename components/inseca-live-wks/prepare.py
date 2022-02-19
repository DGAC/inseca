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
for key in ["userdata-skey-pub-file", "network-connections-allowed"]:
    if key not in conf:
        raise Exception("No '%s' attribute in the build configuration"%key)

destdir="%s/opt/share"%os.environ["PRIVDATA_DIR"]
os.makedirs(destdir, exist_ok=True)

file="%s/%s"%(os.environ["CONF_DIR"], conf["userdata-skey-pub-file"])
shutil.copyfile(file, "%s/userdata-skey.pub"%destdir)
pubkey=util.load_file_contents(file)
util.write_data_to_file("USERDATA signing public key: %s"%pubkey, os.environ["BUILD_DATA_FILE"], append=True)

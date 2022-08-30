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
map_conf=conf.get("data-mapping", None)
map_data={}
if map_conf:
    entries=map_conf.split(",")
    for entry in entries:
        parts=entry.split(":")
        if len(parts)!=2:
            raise Exception("Invalid directory mapping '%s'"%entry)
        (src, dest)=parts
        if src=="" or len(dest)<2:
            raise Exception("Invalid directory mapping '%s'"%entry)
        if src[0]=="/" or dest[0]!="/":
            raise Exception("Invalid directory mapping '%s'"%entry)
        map_data[src]=dest
util.write_data_to_file(json.dumps(map_data), "%s/inseca-data-map.json"%destdir)

# post unlock script
file=conf.get("post-unlock-script", None)
if file:
    file="%s/%s"%(os.environ["CONF_DIR"], file)
    post_script_file="%s/post-unlock-script"%destdir
    shutil.copyfile(file, post_script_file)
    os.chmod(post_script_file, 0o700)

# other config. elements
protected_conf={
    "allowed-virtualized": conf.get("allowed-virtualized", ""),
    "disabled-net-services": conf.get("disabled-net-services", "")
}
util.write_data_to_file(json.dumps(protected_conf), "%s/etc/inseca-live.json"%os.environ["LIVE_DIR"])
util.write_data_to_file("Allowed virtual environments: %s\n"%protected_conf["allowed-virtualized"], os.environ["BUILD_DATA_FILE"], append=True)
util.write_data_to_file("Disabled net services: %s\n"%protected_conf["disabled-net-services"], os.environ["BUILD_DATA_FILE"], append=True)
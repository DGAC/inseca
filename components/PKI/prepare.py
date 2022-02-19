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

# check all expected parameters are present
conf=json.load(open(os.environ["CONF_DATA_FILE"], "r"))
for key in ["ca-certs-dir"]:
    if key not in conf:
        raise Exception("No '%s' attribute in the build configuration"%key)

# copy all specified certificates
destdir="%s/usr/local/share/ca-certificates"%os.environ["PRIVDATA_DIR"]
os.makedirs(destdir, exist_ok=True)

certsdir="%s/%s"%(os.environ["CONF_DIR"], conf["ca-certs-dir"])

for certfile in os.listdir(certsdir):
    shutil.copyfile("%s/%s"%(certsdir, certfile), "%s/%s"%(destdir, certfile))

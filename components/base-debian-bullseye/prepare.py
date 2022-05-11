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
import Utils as util

conf=json.load(open(os.environ["CONF_DATA_FILE"], "r"))
if conf:
    # Display type
    dtype="wayland"
    if "display-type" in conf:
        dtype=conf["display-type"]

    if dtype not in ("wayland", "x11"):
        raise Exception("Invalid '%s' attribute in the build configuration"%"display-type")

    util.write_data_to_file(dtype, "%s/etc/inseca-display-type"%os.environ["LIVE_DIR"])
    util.write_data_to_file("Display type: %s\n"%dtype, os.environ["BUILD_DATA_FILE"], append=True)

    # DConf spec.
    if "dconf-file" in conf:
        destdir="%s/opt"%os.environ["PRIVDATA_DIR"]
        os.makedirs(destdir, exist_ok=True)

        dconf_file=conf["dconf-file"]
        file="%s/%s"%(os.environ["CONF_DIR"], dconf_file)
        shutil.copyfile(file, "%s/dconf.txt"%destdir)

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

# copy the PRIVDATA private key in /credentials/privdata-ekey.priv (yes, no security!)

conf=json.load(open("%s/build-configuration.json"%os.environ["CONF_DIR"], "r"))
for key in ["privdata-ekey-priv-file"]:
    if key not in conf:
        raise Exception("No '%s' attribute in the build configuration"%key)

privkey_file=conf["privdata-ekey-priv-file"]
if privkey_file:
    destdir="%s/credentials"%os.environ["LIVE_DIR"]
    os.makedirs(destdir, exist_ok=True)

    file="%s/%s"%(os.environ["CONF_DIR"], privkey_file)
    shutil.copyfile(file, "%s/privdata-ekey.priv"%destdir)
    os.chmod("%s/privdata-ekey.priv"%destdir, 0o600)

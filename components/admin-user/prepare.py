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
import string
import secrets
import crypt
import Utils as util

conf=json.load(open(os.environ["CONF_DATA_FILE"], "r"))
for key in ["username", "password"]:
    if key not in conf:
        raise Exception("No '%s' attribute in the build configuration"%key)

username=conf["username"]

# prepare password's hash
password=conf["password"]
if password is None:
    # determine random password
    alphabet=string.ascii_letters+string.punctuation+string.digits
    password=''.join(secrets.choice(alphabet) for i in range(14))
hash=crypt.crypt(password)

# prepare user creation in the Live image
destdir="%s/lib/live/config"%os.environ["LIVE_DIR"]
os.makedirs(destdir, exist_ok=True)
data="""#!/bin/sh
passwd_hash='%s'
/sbin/useradd -r -m -s /bin/bash -p "$passwd_hash" "%s"
"""%(hash, username)
util.write_data_to_file(data, "%s/9995-admin-user-decl"%destdir, perms=0o755)

# keep track of the password
util.write_data_to_file("Admin username: %s\nAdmin password: %s\n"%(username, password), os.environ["BUILD_DATA_FILE"], append=True)

# copy the SSH public key to the "resources" directory
if "ssh-public-key" in conf:
    destdir="%s/opt/share"%os.environ["PRIVDATA_DIR"]
    os.makedirs(destdir, exist_ok=True)

    pubkey=conf["ssh-public-key"]
    util.write_data_to_file(pubkey, "%s/ssh-secpc-admin.pub"%destdir)
    util.write_data_to_file("Admin SSH pubkey: %s\n"%pubkey, os.environ["BUILD_DATA_FILE"], append=True)

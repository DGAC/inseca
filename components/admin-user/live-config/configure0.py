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
import shutil

res_dir=os.environ["PRIVDATA_DIR"]

# add SSH public key, if any. FIXME: this needs to be migrated to the "admin-user" component
os.makedirs("/home/admin/.ssh", mode=0o700, exist_ok=True)
shutil.copyfile("%s/opt/share/ssh-secpc-admin.pub"%res_dir, "/home/admin/.ssh/authorized_keys")
shutil.chown("/home/admin/.ssh", "admin", "admin")
shutil.chown("/home/admin/.ssh/authorized_keys", "admin", "admin")

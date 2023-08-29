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
import syslog
import Utils as util

# restart the Docker daemon if it is installed as its configuration may have been
# modified by some PRIVDATA build parameters
docker_path=shutil.which("docker")
if docker_path:
    syslog.syslog(syslog.LOG_INFO, "(re)Starting Docker")
    (status, out, err)=util.exec_sync(["systemctl", "daemon-reload"])
    if status!=0:
        syslog.syslog(syslog.LOG_ERR, "Failed to reload systemd's configuration: %s"%err)
        raise Exception("Failed to reload systemd's configuration")

    (status, out, err)=util.exec_sync(["systemctl", "restart", "docker"])
    if status!=0:
        syslog.syslog(syslog.LOG_ERR, "(re)Starting Docker failed: %s"%err)
        raise Exception("Failed to start the Docker daemon")

# dump PCR registers from TPM2 if any
ts=util.get_timestamp(as_str=True)
os.makedirs("/internal/tpm-tests", exist_ok=True)
(status, out, err)=util.exec_sync(["tpm2_pcrread"])
if status==0:
    util.write_data_to_file(out, "/internal/tpm-tests/TPM2-%s-PCRs"%ts)
else:
    util.write_data_to_file(err, "/internal/tpm-tests/PCR2-%s-ERR"%ts)


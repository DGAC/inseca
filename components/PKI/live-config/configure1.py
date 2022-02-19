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
import syslog
import tarfile
import Utils as util

# extract the empty NSSDB in the user's directory, used by Chromium
tarobj=tarfile.open("/opt/init_pki_nssdb.tar", "r")
tarobj.extractall("/home/insecauser")

# import the certificate in firefox's DB
def handle_dir(dir, certs_dir):
    for fname in os.listdir(dir):
        path="%s/%s"%(dir, fname)
        if os.path.isdir(path):
            handle_dir(path, certs_dir)
        elif fname.startswith("cert") and fname.endswith(".db"):
            # add OpenSC's PKCS#11 library to the browsers
            (status, out, err)=util.exec_sync(["modutil", "-force", "-dbdir", "sql:"+dir, "-add", "Smartcard token", "-libfile", "/usr/lib/x86_64-linux-gnu/pkcs11/opensc-pkcs11.so"])
            if status!=0:
                syslog.syslog(syslog.LOG_ERR, "Could not import OpenSC's PKCS#11 driver in DB '%s': %s"%(dir, err))
            else:
                syslog.syslog(syslog.LOG_INFO, "Imported OpenSC's PKCS#11 driver in DB '%s'"%dir)

            # import certificates in the DB in $dir
            index=0
            for certfile in os.listdir(certs_dir):
                certpath="%s/%s"%(certs_dir, certfile)
                (status, out, err)=util.exec_sync(["certutil", "-A", "-t", "C,,", "-i", certpath, "-n", "PKI%s"%index, "-d", "sql:"+dir])
                if status!=0:
                    syslog.syslog(syslog.LOG_ERR, "Could not import CA certificate '%s' in DB '%s': %s"%(certfile, dir, err))
                else:
                    syslog.syslog(syslog.LOG_INFO, "Imported CA certificate '%s' in DB '%s'"%(certfile, dir))
                index+=1

            # change ownership, in case new files were created (e.g. pkcs11.txt)
            (status, out, err)=util.exec_sync(["chown", "-R", "insecauser.insecauser", dir])
            if status!=0:
                syslog.syslog(syslog.LOG_ERR, "Could not change ownership of '%s' file to insecauser"%(dir, err))

handle_dir("/home", "/usr/local/share/ca-certificates")

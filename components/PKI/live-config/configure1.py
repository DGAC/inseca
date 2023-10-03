#!/usr/bin/python3

# This file is part of INSECA.
#
#    Copyright (C) 2020-2023 INSECA authors
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
import json
import Utils as util

# extract the empty NSSDB in the user's directory, used by Chromium
tarobj=tarfile.open("/opt/init_pki_nssdb.tar", "r")
tarobj.extractall("/home/insecauser")

def configure_db_in_dir(dir, certs_dir):
    """Import the certificate in (firefox's) DB wherever it finds it under @dir"""
    for fname in os.listdir(dir):
        path="%s/%s"%(dir, fname)
        if os.path.isdir(path):
            configure_db_in_dir(path, certs_dir)
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

def add_certs_to_firefox_policies(certs_dir):
    """Modify or create the Firefox policies file to import the certificates present in @certs_dir"""
    # cf. https://mozilla.github.io/policy-templates/
    policies_file="lib/firefox-esr/distribution/policies.json"
    if os.path.exists(policies_file):
        policies=json.load(open(policies_file, "r"))
    else:
        policies={
            "policies": {}
        }
    if "Certificates" not in policies["policies"]:
        policies["policies"]["Certificates"]={}
    if "Install" not in policies["policies"]["Certificates"]:
        policies["policies"]["Certificates"]["Install"]=[]

    for certfile in os.listdir(certs_dir):
        certpath="%s/%s"%(certs_dir, certfile)
        policies["policies"]["Certificates"]["Install"].append(certpath)

    with open(policies_file, "w") as fd:
        json.dump(policies, fd)

def update_system_certs():
    (status, out, err)=util.exec_sync(["/usr/sbin/update-ca-certificates"])
    if status!=0:
        syslog.syslog(syslog.LOG_ERR, f"Could not update system's trusted certificates: {err}")

extra_certs_dir="/usr/local/share/ca-certificates"
update_system_certs()
configure_db_in_dir("/home", extra_certs_dir)
add_certs_to_firefox_policies(extra_certs_dir)

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
import sys
import datetime
import json
import Utils as util

# display the end of validity of the certificate contained in the OpenVPN config file
resfile="%s/userdata.json"%os.environ["USERDATA_DIR"]
print("VPN") # component 'id' to display to the user

def load_certificates_from_ovpn_file(ovpn_file):
    (status, out, err)=util.exec_sync(["openssl", "storeutl", "-certs", ovpn_file])
    # ignore OpenSSL's return code
    certs=[]
    cert=None
    incert=False
    for line in out.splitlines():
        if line=="-----BEGIN CERTIFICATE-----":
            cert=[line]
            incert=True
        elif line=="-----END CERTIFICATE-----":
            cert+=[line]
            certs+=["\n".join(cert)]
            cert=None
            incert=False
        elif incert:
            cert+=[line]
    return certs

def cert_is_ca(pem):
    (status, out, err)=util.exec_sync(["openssl", "x509", "-text", "-noout"], stdin_data=pem)
    if status==0:
        for line in out.splitlines():
            if "CA:TRUE" in line:
                return True
            elif "CA:FALSE" in line:
                return False
    else:
        raise Exception("Could not interpret PEM data: %s"%err)
    return False

if os.path.exists(resfile):
    component_conf=json.load(open(resfile, "r"))
    path=component_conf["ovpn-file"]
    try:
        if path is not None:
            ovpn_file="%s/%s"%(os.environ["USERDATA_DIR"], path)
            certs=load_certificates_from_ovpn_file(ovpn_file)
            for cert in certs:
                if not cert_is_ca(cert):
                    (status, out, err)=util.exec_sync(["openssl", "x509", "-enddate", "-noout"], stdin_data=cert)
                    if status==0:
                        (dummy, eov)=out.split("=")
                        dt=datetime.datetime.strptime(eov, "%b %d %H:%M:%S %Y %Z")
                        print("End of validity: %s UTC"%dt.strftime("%d/%m/%Y @ %H:%M:%S"))
                        sys.exit(0)
                    else:
                        raise Exception(err)
            raise Exception("Invalid OpenVPN config file")
    except Exception as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
else:
    sys.exit(255)

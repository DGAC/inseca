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

import os
import hmac
import hashlib
import Utils as util
import CryptoGen as crypto

# Gettext stuff
import gettext
lib_dir=os.path.dirname(__file__)
gettext.bindtextdomain("inseca-lib", lib_dir+"/locales")
gettext.textdomain("inseca-lib")
_ = gettext.gettext

def generate_salt():
    return crypto.generate_password(30)

def harden_password_for_blob0(password, salt):
    """Instead of using a password directly, we use some resources intensive computation to
    make brute force cracking of the blob0 more difficule"""
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 5000000).hex()

def compute_hmac(data, key, digest="sha256"):
    """Computes a HMAC of some data (string, bytes or a data structure which can be "JSONized").
    Returns a HEX string
    """
    rkey=key
    if isinstance (rkey, str):
        rkey=rkey.encode()
    rdata=data
    if isinstance (rdata, str):
        rdata=rdata.encode()
    elif not isinstance (rdata, bytes):
        import json
        rdata=json.dumps(rdata, sort_keys=True, indent=None).encode()

    f=hmac.new(rkey, rdata, digest)
    #print("HMAC GEN with code %s on: %s"%(key, rdata))
    #print("  --> HMAC: %s"%f.hexdigest())
    return f.hexdigest()

class CryptoPassword(crypto.Crypto):
    def __init__(self, password, ignore_password_strength=False):
        crypto.Crypto.__init__(self)
        if not isinstance(password, str):
            raise Exception(_("Invalid password: expected a string"))
        if not ignore_password_strength and len(password)<10:
            raise Exception(_("Invalid password: not strong enough"))
        self._password=password

    def encrypt(self, data, return_tmpobj=False):
        if not isinstance(data, str) and not isinstance(data, bytes):
            import json
            data=json.dumps(data, sort_keys=True)
        tmp_data=util.Temp(data)
        data_fname=tmp_data.name

        # encrypt clear text data with symetric key
        args=["openssl", "enc", "-a", "-A", "-aes-256-cbc", "-pbkdf2", "-md", self._digest, "-in", data_fname, "-pass", "stdin"]
        (status, out, err)=util.exec_sync(args, self._password)
        if status!=0:
            raise Exception (_("Could not encrypt data with password: %s")%err)
        enc_data=crypto.data_encode_to_ascii(out)

        retval="%s:%s"%(self._digest, enc_data)

        if return_tmpobj:
            return util.Temp(retval)
        else:
            return retval

    def decrypt(self, data, return_tmpobj=False):
        # retreive the different parts
        (digest, enc_data)=data.split(":")
        if digest=="" or enc_data=="":
            raise Exception (_("Invalid format for data to decrypt '%s'")%data)
        enc_data=crypto.data_decode_from_ascii(enc_data)

        # decrypt the actual data
        itmp=util.Temp(enc_data)
        args=["openssl", "enc", "-d", "-a", "-A", "-aes-256-cbc", "-pbkdf2", "-md", self._digest, "-in", itmp.name, "-pass", "stdin"]
        (status, out, err)=util.exec_sync(args, self._password, as_bytes=True)
        if status!=0:
            raise Exception (_("Could not decrypt data using password: %s")%err)

        if out==crypto.none_value:
            out=None
        if return_tmpobj:
            return util.Temp(out)
        else:
            return out

    def sign(self, data, return_tmpobj=False):
        if not isinstance(data, str) and not isinstance(data, bytes):
            import json
            data=json.dumps(data, sort_keys=True)

        # use HMAC
        hashdata=compute_hmac(data, self._password, digest=self._digest)

        if return_tmpobj:
            return util.Temp(hashdata)
        else:
            return hashdata

    def verify(self, data, signature):
        if not isinstance(data, str) and not isinstance(data, bytes):
            import json
            data=json.dumps(data, sort_keys=True)

        hashdata=compute_hmac(data, self._password, digest=self._digest)
        if hashdata==signature:
            return
        else:
            raise Exception(_("Could not verify the signature"))

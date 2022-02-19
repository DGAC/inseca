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
import logging
import Utils as util
import CryptoGen as crypto

# Gettext stuff
import gettext
lib_dir=os.path.dirname(__file__)
gettext.bindtextdomain("inseca-lib", lib_dir+"/locales")
gettext.textdomain("inseca-lib")
_ = gettext.gettext

def gen_rsa_key_pair():
    """Generate a key pair
    returns: (Temp object for the private key, Temp object for the public key)
    """
    tmp_priv=util.Temp()
    tmp_pub=util.Temp()
    (status, out, err)=util.exec_sync(["/usr/bin/openssl", "genrsa", "-out", tmp_priv.name, "2048"])
    if status!=0:
        raise Exception(_("Could not generate a new private RSA key: %s")%err)

    (status, out, err)=util.exec_sync(["/usr/bin/openssl", "rsa", "-in", tmp_priv.name, "-out", tmp_pub.name, "-pubout", "-outform", "PEM"])
    if status!=0:
        raise Exception(_("Could not generate a new public RSA key: %s")%err)
    return (tmp_priv, tmp_pub)

def get_pubkey_from_cert(cert_data):
    # get public key
    args=["/usr/bin/openssl", "x509", "-pubkey", "-noout"]
    (status, pubkey, err)=util.exec_sync(args, stdin_data=cert_data)
    if status!=0:
        raise Exception (_("Could not extract public key from certificate: %s")%err)

    # make sure algo is RSA
    (status, out, err)=util.exec_sync(["/usr/bin/openssl", "rsa", "-pubin", "-text", "-noout"], pubkey)
    if status!=0:
        raise Exception (_("Could not determine public key type of certificate"))
    return pubkey

def raw_compute_file_signature(data_file, privkey_file, privkey_password, out_signature_file):
    """Create a quick signature of a file"""
    # TODO: modify the crypto.Crypto API to be able to sign/verify using filenames and not data (for huge files)
    if privkey_password:
        args=["/usr/bin/openssl", "dgst", "-sha256", "-passin", "stdin", "-sign", privkey_file, "-out", out_signature_file, data_file]
        (status, out, err)=util.exec_sync(args, stdin_data=privkey_password)
    else:
        args=["/usr/bin/openssl", "dgst", "-sha256", "-sign", privkey_file, "-out", out_signature_file, data_file]
        (status, out, err)=util.exec_sync(args)
    if status!=0:
        raise Exception(_(f"Could not sign file '{data_file}': {err}"))

def raw_verify_file_signature(data_file, signature_file, publickey_file):
    """Verify a file's signature, raise an exception on failure"""
    # TODO: modify the crypto.Crypto API to be able to sign/verify using filenames and not data (for huge files)

    #pubkey=util.load_file_contents(publickey_file, binary=True)
    #obj=CryptoKey(privkey_data=None, pubkey_data=pubkey)
    #obj.verify()
    args=["/usr/bin/openssl", "dgst", "-sha256", "-verify", publickey_file, "-signature", signature_file, data_file]
    (status, out, err)=util.exec_sync(args)
    if status!=0:
        msg=_(f"Signature verification failed for file '{data_file}': {err}")
        logging.error(msg)
        raise Exception(msg)

class CryptoKey(crypto.Crypto):
    """Based on private/public key, no certificate"""
    def __init__(self, privkey_data, pubkey_data):
        crypto.Crypto.__init__(self)
        self._privkey=privkey_data
        self._pubkey=pubkey_data

    def encrypt(self, data, return_tmpobj=False):
        if not self._pubkey:
            raise Exception(_("No public key provided, can't encrypt"))
        if not isinstance(data, str) and not isinstance(data, bytes):
            import json
            data=json.dumps(data, sort_keys=True)
        tmp_data=util.Temp(data)
        data_fname=tmp_data.name

        # generate random symetric key
        symkey=util.gen_random_bytes(32)

        # encrypt symetric key with certificate's public key
        pubtmp=util.Temp(self._pubkey)
        args=["/usr/bin/openssl", "rsautl", "-encrypt", "-inkey", pubtmp.name, "-pubin"]
        (status, out, err)=util.exec_sync(args, stdin_data=symkey, as_bytes=True)
        if status!=0:
            raise Exception (_("Could not encrypt symetric key with certificate's public key: %s")%err)
        enc_key=crypto.data_encode_to_ascii(out)

        # encrypt clear text data with symetric key
        args=["/usr/bin/openssl", "enc", "-a", "-A", "-aes-256-cbc", "-md", self._digest, "-in", data_fname, "-pass", "stdin"]
        (status, out, err)=util.exec_sync(args, symkey)
        if status!=0:
            raise Exception (_("Could not encrypt data with symetric key: %s")%err)
        enc_data=crypto.data_encode_to_ascii(out)

        retval="%s:%s:%s:%s"%(self._digest, enc_key, "rsa", enc_data)

        if return_tmpobj:
            return util.Temp(retval)
        else:
            return retval

    def decrypt(self, data, return_tmpobj=False):
        # retreive the different parts
        if not self._privkey:
            raise Exception("No private key provided, can't decrypt")

        (digest, enc_key, algo, enc_data)=data.split(":")
        if enc_key=="" or enc_data=="":
            raise Exception(_("Invalid format for data to decrypt '%s'")%data)
        enc_key=crypto.data_decode_from_ascii(enc_key)
        enc_data=crypto.data_decode_from_ascii(enc_data)

        # decrypt symetric key (using the RSA algo)
        itmp=util.Temp(enc_key)
        privkey_tmp=util.Temp(self._privkey)
        args=["/usr/bin/openssl", "rsautl", "-decrypt", "-inkey", privkey_tmp.name, "-passin", "fd:0", "-in", itmp.name]
        (status, symkey, err)=util.exec_sync(args, "\n")
        itmp=None
        privkey_tmp=None
        if status!=0:
            raise Exception (_("Could not decrypt intermediate symetric key: %s")%err)

        # decrypt the actual data using the symetric key
        itmp=util.Temp(enc_data)
        args=["/usr/bin/openssl", "enc", "-d", "-a", "-A", "-aes-256-cbc", "-md", digest, "-in", itmp.name, "-pass", "stdin"]
        (status, out, err)=util.exec_sync(args, symkey, as_bytes=True)
        otmp=None
        if status!=0:
            raise Exception (_("Could not decrypt data using symetric key: %s")%err)

        if out==crypto.none_value:
            out=None
        if return_tmpobj:
            return util.Temp(out)
        else:
            return out

    def sign(self, data, return_tmpobj=False):
        if not self._privkey:
            raise Exception(_("No private key provided, can't sign"))
        if not isinstance(data, str) and not isinstance(data, bytes):
            import json
            data=json.dumps(data, sort_keys=True)

        hashdata=crypto.compute_hash(data, self._digest)

        # actual signature
        privkey_tmp=util.Temp(self._privkey)
        args=["/usr/bin/openssl", "pkeyutl", "-sign", "-inkey", privkey_tmp.name]
        (status, out, err) = util.exec_sync(args, stdin_data=hashdata, as_bytes=True)
        if status != 0:
            raise Exception(_("Could not create signature: %s"), err)
        out=self._digest+"|"+crypto.data_encode_to_ascii(out)
        privkey_tmp=None

        if return_tmpobj:
            return util.Temp(out)
        else:
            return out

    def verify(self, data, signature):
        """NB:
        - @data or @data_file must be defined (only 1 can be defined)
        - @signature or @signature_file must be defined (only 1 can be defined)
        """
        if not self._pubkey:
            raise Exception(_("No public key provided, can't verify signature"))
        if not isinstance(data, str) and not isinstance(data, bytes):
            import json
            data=json.dumps(data, sort_keys=True)

        hashdata=crypto.compute_hash(data, self._digest)
        sparts=signature.split("|", 2)

        if len(sparts)!=2:
            raise Exception(_("Invalid signature format"))

        # extract signature as binary
        tmp_sig=util.Temp(crypto.data_decode_from_ascii(sparts[1]))

        # verify signature
        tmp_pubkey=util.Temp(self._pubkey)
        args=["/usr/bin/openssl", "pkeyutl", "-verify", "-pubin", "-inkey", tmp_pubkey.name, "-sigfile", tmp_sig.name]
        (status, out, err)=util.exec_sync(args, stdin_data=hashdata)
        if status == 0:
            return
        if "Signature Verification Failure" in out:
            raise Exception("Signature is wrong")

        raise Exception(_("Unable to verify signature: %s")%out)

class CryptoX509(CryptoKey):
    """Based on a private key and the associated X509 certificate"""
    def __init__(self, privkey_data, cert_data):
        CryptoKey.__init__(self, privkey_data, get_pubkey_from_cert(cert_data))

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
import lzma
import base64
import hashlib
import secrets
import string

import Utils as util

# Gettext stuff
import gettext
lib_dir=os.path.dirname(__file__)
gettext.bindtextdomain("inseca-lib", lib_dir+"/locales")
gettext.textdomain("inseca-lib")
_ = gettext.gettext

def generate_password(length=25, alphabet=None):
    """Generate a random password containing letters and numbers, of the specified length (which can't be less than 12 characters)."""
    # https://www.pleacher.com/mp/mlessons/algebra/entropy.html
    if length<12:
        raise Exception(_("Password is too short (%d characters)")%length)
    if not alphabet:
        alphabet = string.ascii_letters + string.digits + string.punctuation
    return ''.join(secrets.choice(alphabet) for i in range(length))

def validate_password(password, min_entropy=75):
    """Don't allow characters not allowed by VeraCrypt, and check minimum entropy"""
    if not isinstance(password, str):
        raise Exception("CODEBUG, expecting str got %s"%type(password))
    for c in password:
        if c not in "!\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~":
            raise Exception(_("Invalid character '%s'")%c)
    entropy=get_password_strength(password)
    if entropy<min_entropy:
        raise Exception(_("Invalid password: not strong enough"))

def get_password_strength(password):
    if not isinstance(password, str):
        raise Exception("CODEBUG")
    if password=="":
        return 0

    # analyse password
    has_lower=False
    has_upper=False
    has_digit=False
    has_special=False
    for c in password:
        if c in "0123456789":
            has_digit=True
        elif c in "abcdefghijklmnopqrstuvwxyz":
            has_lower=True
        elif c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            has_upper=True
        elif c.isprintable():
            has_special=True

    # compute size of input space
    size=0
    if has_lower:
        size+=26
    if has_upper:
        size+=26
    if has_digit:
        size+=10
    if has_special:
        size+=20

    # compute entropy
    import math
    return math.log(size, 2)*len(password)

none_value="NONE-VALUE-7664b695-a047-4f6a-8e7e-3133ca2f01cb-NONE-VALUE"
def compute_hash(data, digest="sha256"):
    """Compute a HASH.
    Returns: a HEX string
    """
    h=hashlib.new(digest)
    rdata=data
    if isinstance (rdata, str):
        rdata=rdata.encode()
    h.update(rdata)
    return h.hexdigest()

def compute_hash_file(filename, digest="sha256"):
    """Compute a HASH of a file.
    Returns: a HEX string
    """
    BUF_SIZE = 65536  # lets read stuff in 64kb chunks!
    h = hashlib.new(digest)
    with open(filename, 'rb') as f:
        while True:
            data = f.read(BUF_SIZE)
            if not data:
                break
            h.update(data)
    return h.hexdigest()

def data_encode_to_ascii(data):
    """'Encodes' some bytes to make it a single ASCII line, suitable
    to be stored simply in the database, or transmitted as text.
    The data may be compressed if it is more efficient
    The 1st character of the returned string is:
    - 'b' for a non compressed binary data
    - 'B' for a compressed binary data
    - 's' for a non compressed string
    - 'S' for a compressed string
    """
    # if data is short, then we don't compress.
    if isinstance(data, bytes) or isinstance(data, bytearray):
        enc=lzma.compress(data, lzma.FORMAT_XZ)
    elif isinstance(data, str):
        enc=lzma.compress(data.encode(), lzma.FORMAT_XZ)
    else:
        raise TypeError("CODEBUG: argument is not str nor bytes")

    if len(data) > len(enc):
        if isinstance(data, bytes):
            return "B" + base64.b64encode(enc).decode()
        else:
            return "S" + base64.b64encode(enc).decode()
    else:
        if isinstance(data, bytes):
            return "b" + base64.b64encode(data).decode()
        else:
            return "s" + base64.b64encode(data.encode()).decode()

def data_decode_from_ascii(data):
    """Performs the opposite transformation of data_encode_to_ascii()
    Returns: a string or a bytearray
    """
    if not isinstance(data, str):
        raise TypeError("CODEBUG: Argument is not str")

    asciidata=data[1:]
    type=data[0:1]
    if type == 'S':
        return lzma.decompress(base64.b64decode(asciidata)).decode()
    elif type == 's':
        return base64.b64decode(asciidata).decode()
    elif type == 'B':
        return lzma.decompress(base64.b64decode(asciidata))
    elif type == 'b':
        return base64.b64decode(asciidata)
    else:
        raise Exception(_("Invalid data: can't convert from ascii"))

class Crypto():
    """Interface to perform encryption and/or integrity operations"""
    def __init__(self):
        self._digest="sha256"

    def encrypt(self, data, return_tmpobj=False):
        raise Exception("CODEBUG: the encrypt() operation is not supported")

    def decrypt(self, data, return_tmpobj=False):
        raise Exception("CODEBUG: the decrypt() operation is not supported")

    def sign(self, data, return_tmpobj=False):
        raise Exception("CODEBUG: the sign() operation is not supported")

    def verify(self, data, signature):
        raise Exception("CODEBUG: the verify() operation is not supported")

def create_crypto_object(spec):
    if spec["type"]=="password":
        import CryptoPass
        return CryptoPass.CryptoPassword(spec["password"])
    elif spec["type"]=="key":
        import CryptoX509
        privkey=None
        if "private-key-file" in spec:
            privkey=util.load_file_contents(spec["private-key-file"])
        pubkey=None
        if "public-key-file" in spec:
            pubkey=util.load_file_contents(spec["public-key-file"])
        return CryptoX509.CryptoKey(privkey, pubkey)
    elif spec["type"]=="certificate":
        import CryptoX509
        privkey=None
        if "private-key-file" in spec:
            privkey=util.load_file_contents(spec["private-key-file"])
        cert=None
        if "cert-file" in spec:
            cert=util.load_file_contents(spec["cert-file"])
        return CryptoX509.CryptoX509(privkey, cert)
    else:
        raise Exception("CODEBUG: unknown ACL object type '%s'"%spec["type"])

def create_crypto_objects_list(spec):
    objects={}
    for name in spec:
        obj=create_crypto_object(spec[name])
        objects[name]=obj
    return objects

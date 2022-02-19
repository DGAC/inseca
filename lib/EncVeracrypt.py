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
import Utils as util

class Encrypted():
    # NB: password can be passed via stdin using the --stdin argument. This seems undocumented, see:
    #     https://github.com/veracrypt/VeraCrypt/pull/18/commits/9582d8fbcb57c0297aad3d4a05eac53f1c125cd3
    def __init__(self, part_name, password=None):
        if not os.path.exists(part_name):
            raise Exception("Partition '%s' does not exist"%part_name)
        self._part_name=part_name
        self._password=password
        (status, out, err)=util.exec_sync(["/usr/bin/which", "veracrypt"])
        if status!=0:
            raise Exception("Veracrypt not found")
        self._binary_args=["veracrypt", "-t", "--non-interactive"]
        self.binary_string="veracrypt"

    def _slot_from_mapped_name(self, map_name):
        parts=map_name.split("/")
        part=parts[-1]
        if part.startswith(self.binary_string):
            slot=part[9:]
            try:
                return int(slot)
            except:
                raise Exception("Invalid map name '%s' for Veracrypt"%map_name)
        else:
            raise Exception("Invalid map name '%s' for Veracrypt"%map_name)

    def _find_free_slot(self):
        index=1
        while True:
            filename="/dev/mapper/%s%d"%(self.binary_string, index)
            if not os.path.exists(filename):
                break
            index+=1
            if index>64:
                raise Exception("Unable to find free slot")
        return index

    def open(self):
        """Open a Veracrypt "container" and returns the mapper device to use to mount or format"""
        slot=self._find_free_slot()
        if not self._password:
            raise Exception("No password provided")
        args=self._binary_args+["--stdin", "--protect-hidden=no", "-k", "", "--filesystem=none", "--slot=%d"%slot, self._part_name]
        (status, out, err)=util.exec_sync(args, stdin_data=self._password) # no newline!
        if status != 0:
            raise Exception("Unable to open Veracrypt volume '%s': %s" % (self._part_name, err))
        (mapped, mp)=util.get_encrypted_partition_mapped_elements(self._part_name)
        return mapped

    def close(self):
        # Close "container"
        (mapped, mp)=util.get_encrypted_partition_mapped_elements(self._part_name)
        slot=self._slot_from_mapped_name(mapped)
        args=self._binary_args+["-d", "--slot=%d"%slot]
        (status, out, err)=util.exec_sync(args)
        if status != 0:
            raise Exception("Unable to close Veracrypt volume '%s': %s" % (self._part_name, err))

    def create(self):
        # Veracrypt format
        if not self._password:
            raise Exception("No password specified")
        args=self._binary_args+["-c", "--quick", "--stdin", "--volume-type=normal", "--encryption=AES", "--hash=RIPEMD-160", "--filesystem=none", "-k", "", "--random-source=/dev/urandom", self._part_name]
        (status, out, err)=util.exec_sync(args, stdin_data=self._password)
        if status != 0:
            raise Exception("Unable to format '%s' as Veracrypt: %s" % (self._part_name, err))

    def read_header(self):
        """Extract Veracrypt header to a temporary file."""
        if not self._password:
            raise Exception("No password provided")
        hfile=util.Temp()
        args=self._binary_args+["--backup-headers", self._part_name]
        stdin_data="""%s


n
y
%s
"""%(self._password, hfile.name)
        (status, out, err)=util.exec_sync(args, stdin_data)
        if status != 0:
            raise Exception ("Unable to extract VeraCrypt header for '%s': %s" % (self._part_name, err))
        return hfile

    def write_header(self, backup_file):
        """Restore a backup header (to restore the known  password)."""
        if not os.path.isfile(backup_file):
            raise Exception("Missing header file '%s'"%backup_file)

        randdata=util.gen_random_bytes(350) # TODO: check if necessary with Veracrypt
        args=self._binary_args+["--restore-headers", self._part_name]
        stdin_data="""2
Yes
%s
%s

%s
"""%(backup_file, self._password, randdata)
        (status, out, err)=util.exec_sync(args, stdin_data)
        if status != 0:
            raise Exception ("Can't restore Veracrypt header of '%s': %s" % (self._part_name, err))

    def erase(self):
        # https://www.wilderssecurity.com/threads/truecrypt-location-of-encryption-key.274443/
        # https://www.truecrypt71a.com/documentation/technical-details/truecrypt-volume-format-specification/
        try:
            fd=open(self._part_name, "rb+")
            # header
            fd.seek(0)
            fd.write(b'\0'*131072)

            # backup header
            fd.seek(-131072, 2)
            fd.write(b'\0'*131072)

            os.sync()
        except Exception as e:
            raise Exception ("Could not finish erasing Veracrypt headers of '%s': %s" % (self._part_name, str(e)))

    def change_password(self, new_password): # NEEDS TO BE TESTED
        if not self._password:
            raise Exception("No password provided")

        args=self._binary_args+["-C", "-p", self._password, "--new-password=%s"%new_password, self._part_name]
        (status, out, err)=util.exec_sync(args)
        if status != 0:
            raise Exception("Unable to change Veracrypt password of '%s': %s" % (self._part_name, err))

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
import tempfile
import Utils as util

class Encrypted():
    def __init__(self, part_name, password=None):
        if not os.path.exists(part_name):
            raise Exception("Partition '%s' does not exist"%part_name)
        self._part_name=part_name
        self._password=password

    def open(self):
        """Open a LUKS "container" and returns the mapper device to use to mount or format"""
        if not self._password:
            raise Exception("No password provided")
        map_name="secluks-%s"%self._part_name.replace("/", "")
        args=["/sbin/cryptsetup", "open", self._part_name, map_name, "-d", "-"]
        (status, out, err)=util.exec_sync(args, stdin_data=self._password) # no newline!
        if status!=0:
            msgs={
                1: "wrong parameters (code bug)",
                2: "invalid password",
                3: "out of memory",
                4: "wrong device",
                5: "device already exists or is busy",
                -9: "Not enough memory" # OOM killer did its job
            }
            if status in msgs:
                raise Exception("Unable to open LUKS volume '%s': %s"%(self._part_name, msgs[status]))
            raise Exception("Unable to open LUKS volume '%s': %s(%s)"%(self._part_name, status))

        (mapped, mp)=util.get_encrypted_partition_mapped_elements(self._part_name)
        return mapped

    def close(self):
        # Close "container"
        (mapped, mp)=util.get_encrypted_partition_mapped_elements(self._part_name)
        args=["/sbin/cryptsetup", "close", mapped]
        (status, out, err)=util.exec_sync(args) # no newline!
        if status != 0:
            raise Exception("Unable to close LUKS volume '%s': %s" % (self._part_name, err))

    def create(self):
        # LUKS format
        if not self._password:
            raise Exception("No password specified")
        args=["/sbin/cryptsetup", "luksFormat", self._part_name, "--type", "luks2", "--pbkdf-memory", "524288", "-d", "-"] # limit mem consumption to 512 Mio
        (status, out, err)=util.exec_sync(args, stdin_data=self._password) # no newline!
        if status != 0:
            # from the man page: Error codes are: 1 wrong parameters, 2 no permission (bad passphrase),
            #                    3 out of memory, 4 wrong device specified, 5 device already exists or device is busy.
            if status==3:
                err="Out of memory"
            raise Exception("Unable to format '%s' as LUKS: %s" % (self._part_name, err))

    def read_header(self):
        """Extract LUKS header to a temporary file."""
        # https://www.lisenet.com/2013/luks-add-keys-backup-and-restore-volume-header/
        fname="/tmp/%s"%next(tempfile._get_candidate_names())
        args=["/sbin/cryptsetup", "luksHeaderBackup", self._part_name, "--header-backup-file", fname]
        (status, out, err)=util.exec_sync(args)
        if status != 0:
            raise Exception ("Unable to extract LUKS header for '%s': %s" % (self._part_name, err))

        h=util.load_file_contents(fname, binary=True)
        os.unlink(fname)
        hfile=util.Temp(data=h)
        return hfile

    def write_header(self, backup_file):
        """Restore a backup header (to restore the known  password)."""
        if not os.path.isfile(backup_file):
            raise Exception("Missing header file '%s'"%backup_file)
        args=["/sbin/cryptsetup", "luksHeaderRestore", self._part_name, "--header-backup-file", backup_file]
        (status, out, err)=util.exec_sync(args)
        if status != 0:
            raise Exception ("Can't restore LUKS header of '%s': %s" % (self._part_name, err))

    def erase(self):
        # see https://wiki.archlinux.org/index.php/Dm-crypt/Drive_preparation#Wipe_LUKS_header
        try:
            # erase keys, which is fast
            args=["/sbin/cryptsetup", "-q", "luksErase", self._part_name]
            (status, out, err)=util.exec_sync(args)

            # erase header
            fd=open(self._part_name, "rb+")
            fd.seek(0)
            fd.write(b'\0'*16*1024*1024)

            os.sync()
        except Exception as e:
            raise Exception ("Could not finish erasing LUKS headers of '%s': %s" % (self._part_name, str(e)))

    def add_password(self, new_password):
        if not self._password:
            raise Exception("No password provided")

        current_pass_tmp=util.Temp(data=self._password)
        args=["/sbin/cryptsetup", "luksAddKey", self._part_name, "--key-file=%s"%current_pass_tmp.name]
        (status, out, err)=util.exec_sync(args, stdin_data=new_password)
        current_pass_tmp=None
        if status != 0:
            raise Exception ("Can't add LUKS password of '%s': %s" % (self._part_name, err))

    def del_password(self, password):
        args=["/sbin/cryptsetup", "luksRemoveKey", self._part_name]
        (status, out, err)=util.exec_sync(args, stdin_data=password)
        if status != 0:
            raise Exception ("Can't remove LUKS password of '%s': %s" % (self._part_name, err))

    def change_password(self, new_password):
        if not self._password:
            raise Exception("No password provided")

        current_pass_tmp=util.Temp(data=self._password)
        args=["/sbin/cryptsetup", "luksChangeKey", self._part_name, "--key-file=%s"%current_pass_tmp.name]
        (status, out, err)=util.exec_sync(args, stdin_data=new_password)
        current_pass_tmp=None
        if status != 0:
            raise Exception ("Can't change LUKS password of '%s': %s" % (self._part_name, err))

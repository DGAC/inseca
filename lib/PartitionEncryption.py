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
import time
import Utils as util

class Enc():
    def __init__(self, enctype, part_name, password=None):
        """Create an object used to manage the encryption layer of a partition:
        - @part_name needs to be a valid partition name like "/dev/sdb1".
        - @enctype is "veracrypt" or "luks"
        - if @password is not specified, a random password may be generated

        NB: this object will create the appropriate LUKS or VeraCrypt encryption objects in self._obj
        """
        count=0
        while(count<20):
            if os.path.exists(part_name):
                break
            else:
                #print("WAIT for %s"%part_name)
                count+=1
                time.sleep(0.5)
        if not os.path.exists(part_name):
            raise Exception("Partition '%s' does not exist"%part_name)
        self._part_name=part_name

        if enctype=="veracrypt":
            import EncVeracrypt as encvera
            self._obj=encvera.Encrypted(part_name, password=password)
        elif enctype=="luks":
            import EncLUKS as encluks
            self._obj=encluks.Encrypted(part_name, password=password)
        else:
            raise Exception("Unknown encryption type '%s'"%enctype)

    def create(self):
        """Actually create the encryption layer"""
        self._obj.create()

    def open(self):
        """Open the encryption layer and returns the mapper device to use to mount or format"""
        if self.is_opened()==False:
            return self._obj.open()
        else:
            raise Exception("Encryption layer already opened")

    def is_opened(self):
        """Check if the encryption layer is set up"""
        (mapped, mp)=util.get_encrypted_partition_mapped_elements(self._part_name)
        return True if mapped else False

    def mount(self, mountpoint, options=None):
        """Mount the filesystem at @mountpoint"""
        (mapped, mountedpoint)=util.get_encrypted_partition_mapped_elements(self._part_name)
        if not mapped:
            self.open()
            (mapped, mountedpoint)=util.get_encrypted_partition_mapped_elements(self._part_name)
        if mountedpoint:
            if mountedpoint!=mountpoint:
                raise Exception("Filesystem already mounted on '%s'"%mountedpoint)
            return # already mounted where we need

        if options:
            (status, out, err)=util.exec_sync(["/bin/mount","-o", options, mapped, mountpoint])
        else:
            (status, out, err)=util.exec_sync(["/bin/mount", mapped, mountpoint])
        if status!=0:
            raise Exception("Could not mount partition '%s' to mountpoint '%s': %s"%(self._part_name, mountpoint, err))

    def umount(self):
        """Unmount the filesystem. Does nothing if filesystem is not already mounted"""
        (mapped, mountedpoint)=util.get_encrypted_partition_mapped_elements(self._part_name)
        if mountedpoint:
            (status, out, err)=util.exec_sync(["/bin/umount", mapped])
            if status!=0:
                raise Exception("Could not unmount partition '%s': %s"%(self._part_name, err))
            self.close()

    def close(self):
        """Close the encryption layer"""
        if self.is_opened()!=False:
            return self._obj.close()

    def read_header(self):
        """Extract the headers to be backed up to a temporary file,
        and return the TMP file object"""
        return self._obj.read_header()

    def write_header(self, header_file_name):
        """Restore the headers from a backed up"""
        return self._obj.write_header(header_file_name)

    def erase(self):
        """Ensure the data can't ever be retreived"""
        self._obj.erase()

    def add_password(self, new_password):
        #if hasattr(self._obj, "add_password") and callable(self._obj.add_password):
        self._obj.add_password(new_password)

    def del_password(self, password):
        self._obj.del_password(password)

    def change_password(self, new_password):
        self._obj.change_password(new_password)

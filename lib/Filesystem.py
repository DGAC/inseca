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
import enum
import syslog
import Utils as util

class FSType(str, enum.Enum):
    """Supported filesystems types"""
    fat = "FAT"
    ntfs = "NTFS"
    ext4 = "EXT4"
    exfat = "EXFAT"
    btrfs = "BTRFS"

def fstype_to_description(fstype):
    descr={
        FSType.fat: "FAT: Windows, MacOSX et Linux (limite fichiers 4Go)",
        FSType.ntfs: "NTFS: Windows et Linux",
        FSType.ext4: "Ext4: Linux",
        FSType.exfat: "EXFat: Windows et Linux(-) (MacOSX?)",
        FSType.btrfs: "BTRFS: Linux"
    }
    if fstype in descr:
        return descr[fstype]
    else:
        return descr[fstype_from_string(fstype)]

def fstype_from_string(string):
    try:
        return FSType(string.upper())
    except:
        if not string:
            return None
        if "\n" in string:
            raise Exception("Invalid filesystem type '%s'"%string)
        string=string.lower()
        if string.startswith("fat") or string.startswith("vfat"):
            return FSType.fat
        elif string.startswith("ntfs"):
            return FSType.ntfs
        elif string.startswith("ext"):
            return FSType.ext4
        elif string.startswith("exfat"):
            return FSType.exfat
        elif string.startswith("btrfs"):
            return FSType.btrfs
        else:
            raise Exception("Invalid filesystem type '%s'"%string)

def create_filesystem(partname, fstype, label, fsvol=None):
    if not isinstance(fstype, FSType):
        raise Exception("Invalid filesystem argument, expected FSType, got %s"%type(fstype))
    util.wait_for_partition(partname)
    fstype_str=fstype.name
    if fstype==FSType.fat:
        args=["/sbin/mkfs.vfat", "-n", label]
        if fsvol:
            args+=["-i", fsvol]
    elif fstype==FSType.exfat:
        args=["/sbin/mkfs.exfat", "-n", label]
        if fsvol:
            args+=["-i", fsvol]
    elif fstype==FSType.ntfs:
        args=["/sbin/mkfs.ntfs", "-f", "-L", label]
        if fsvol:
            raise Exception("NTFS does not support using a volume ID")
    elif fstype==FSType.ext4:
        args=["/sbin/mkfs.ext4", "-F", "-L", label]
        if fsvol:
            args+=["-U", fsvol]
    elif fstype==FSType.btrfs:
        if os.path.exists("/sbin/mkfs.btrfs"):
            # Debian 11
            args=["/sbin/mkfs.btrfs", "-f", "-L", label]
        else:
            # Debian 10
            args=["/bin/mkfs.btrfs", "-f", "-L", label]
        if fsvol:
            args+=["-U", fsvol]
    else:
        raise Exception("Unhandled FS type '%s'"%fstype_str)

    args+=[partname]
    (status, out, err)=util.exec_sync(args, stdin_data="y\n") # in case mkfs asks for confirmation
    if status!=0:
        if "does not exist" in err: # sometimes, on slow devices, it seems udev is slow to create the device files, or some other weird behaviour
            syslog.syslog(syslog.LOG_INFO, "Device file '%s' was present and has disappeared, waiting till it's present again"%partname)
            util.wait_for_partition(partname)
            create_filesystem(partname, fstype, label, fsvol)
            return
        raise Exception("Impossible de formater '%s' en %s: %s" % (partname, fstype_str, err))

def probe(part_path):
    """Try to identify the filesystem type @part_path, which may
    be a partition path like "/dev/sdb1" or a device mapper path like
    "/dev/mapper/luks-ae49ab77-8791-4569-adb9-c8f34568edb3"
    """
    (status, out, err)=util.exec_sync(["/bin/lsblk", "-n", "-l", "-o", "FSTYPE", part_path])
    if status!=0:
        raise Exception("Could not get filesystem information of '%s': %s"%(part_path, err))
    else:
        return fstype_from_string(out)

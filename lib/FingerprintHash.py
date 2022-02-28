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
#

import os
import tempfile
import time
import hashlib
import Utils as util

def compute_file_hash(filename, start_byte=0, end_byte=None, hash_algo="sha256"):
    """Computes the hash of the file, from @start_byte to @end_byte included (or the total size if left to None)
    """
    if not isinstance(start_byte, int):
        raise Exception("Invalid @start_byte argument '%s'"%start_byte)
    if end_byte is not None:
        if not isinstance(start_byte, int):
            raise Exception("Invalid @end_byte argument '%s'"%start_byte)
        if end_byte<start_byte:
            raise Exception("@end_byte is lower than @start_byte")

    BUF_SIZE = 524288 # 512kb chunks
    time.sleep(0.1) # we may have "permission denied" otherwise!!!

    if end_byte is None:
        try:
            end_byte=os.path.getsize(filename)
        except Exception:
            pass

    if hash_algo=="sha256":
        sha256=hashlib.sha256()
    else:
        raise Exception("Unhandled hash algorithm '%s'"%hash_algo)
    bytesread=0
    with open(filename, 'rb') as f:
        if start_byte>0:
            data=f.seek(start_byte)
        while True:
            to_read=BUF_SIZE
            if end_byte is not None and bytesread+BUF_SIZE>=(end_byte-start_byte):
                to_read=end_byte-start_byte-bytesread

            data=f.read(to_read)
            if data:
                sha256.update(data)
                bytesread+=len(data)
            else:
                break
    return sha256.hexdigest()

def chain_integity_hash(hash0, hash1):
    """Chains 2 hashes to produce a new hash"""
    sha256=hashlib.sha256()
    sha256.update(("%s/%s"%(hash0, hash1)).encode())
    return sha256.hexdigest()

def compute_partitions_table_hash(devfile, disktype):
    """Compute the hash of the partitions table"""
    #print("@Computing partitions table hash")
    sha256=hashlib.sha256()
    with open(devfile, 'rb') as f: # we need to ignore the MBR signature from bytes 0x1b8 to 0x1bb included (4 bytes) because of Windows crap
        data=f.read(440)
        sha256.update(data)
        f.seek(444)
        data=f.read(512-444)
        sha256.update(data)
        if disktype==util.LabelType.DOS:
            h=sha256.hexdigest()
        elif disktype in (util.LabelType.GPT, util.LabelType.HYBRID):
            data=f.read(33*512)
            sha256.update(data)
            h=sha256.hexdigest()
        else:
            raise Exception("Unknown partitioning type '%s'"%disktype)

    return "%s|%s"%("sha256", h)

def compute_partition_hash(partfile):
    """Compute the hash of a (supposedly immutable) partition"""
    #print("@Computing partition hash of '%s', size: %d"%(partfile, size))
    h=compute_file_hash(partfile)
    return "%s|%s"%("sha256", h)

windows_crap_directories=["$RECYCLE.BIN", "System Volume Information", "ClientRecoveryPasswordRotation", "AadRecoveryPasswordDelete"]
def _update_windows_crap_directories_hash(filename, hash_obj):
    """
    This function gets called when @filename is a specific Windows crappy directory,
    it will basically make some checks and either ignore the whole directory (as if it did not
    exist), or, if the checks fail, will update @hash_obj in a way which will make the whole verification
    fail.
    """
    base=os.path.basename(filename)
    if base not in windows_crap_directories:
        print("** Windows CRAP again: unexpected file or directory '%s'"%filename)
        hash_obj.update(b'FAILED')
        return

    try:
        for subfile in os.listdir(filename):
            if subfile in windows_crap_directories:
                _update_windows_crap_directories_hash("%s/%s"%(filename, subfile), hash_obj)
            else:
                if subfile not in ["IndexerVolumeGuid", "WPSettings.dat", "desktop.ini"]:
                    print("** Windows CRAP again in '%s': unexpected file '%s'"%(filename, subfile))
                    hash_obj.update(b'FAILED')
                    continue

                csubfile="%s/%s"%(filename, subfile)
                if not os.path.isfile(csubfile) or os.path.getsize(csubfile)>150: # file size limit from experience
                    print("** Windows CRAP again in '%s': file '%s' too big or wrong type"%(filename, subfile))
                    hash_obj.update(b'FAILED')
    except OSError as e:
        if not "Input/output error" in str(e):
            raise

def _compute_efi_image_hash(filename, hash_obj):
    """Mount an EFI image to compute its hash as Windows likes to modify those files"""
    mp=tempfile.mkdtemp()
    (status, out, err)=util.exec_sync(["/bin/mount", "-o", "loop,ro", filename, mp])
    if status!=0:
        raise Exception("Could not mount EFI image '%s' to '%s': %s"%(filename, mp, err))
    try:
        return _update_directory_hash(mp, hash_obj, "")
    finally:
        (status, out, err)=util.exec_sync(["/bin/umount", mp])
        if status!=0:
            raise Exception("Could not unmount '%s': %s"%(filename, err))

def _update_directory_hash(root, hash_obj, subfile, ignore_func=None):
    """Internal function which 'updates' @hash_obj"""
    if subfile and subfile[0]=="/":
        subfile=subfile[1:]
    filename="%s/%s"%(root, subfile)
    basename=os.path.basename(subfile)

    if basename in windows_crap_directories:
        # specific handling
        #print("CRAP [%s]"%subfile)
        _update_windows_crap_directories_hash(filename, hash_obj)
    elif ignore_func is None or not ignore_func(root, subfile):
        if os.path.isdir(filename):
            #print("Directory [%s]"%subfile)
            hash_obj.update(("D"+subfile).encode())
            flist=os.listdir(filename)
            if flist:
                flist.sort()
                for sub in flist:
                    _update_directory_hash(root, hash_obj, "%s/%s"%(subfile, sub), ignore_func)
        elif os.path.islink(filename):
            #print("Link [%s]"%subfile)
            hash_obj.update(("L"+subfile).encode())
            hash_obj.update(os.readlink(filename).encode())
        else:
            #print("File [%s]"%subfile)
            hash_obj.update(("F"+subfile).encode())
            if basename.lower()=="efi.img":
                _compute_efi_image_hash(filename, hash_obj)
            else:
                BUF_SIZE=2**16
                with open(filename, 'rb') as f:
                    while True:
                        data=f.read(BUF_SIZE)
                        if data:
                            hash_obj.update(data)
                        else:
                            break

def compute_directory_hash(filename, ignore_func=None):
    """Compute a "kind of" hash of all the files and directories recursively,
    with the aim of being able to compare contents or partitions (thanks to Windows
    which sometimes modifies efi.img files when it mounts a partition...)
    by specifying an optional @ignore_func function which:
    - is called for every file analysed
    - with the following arguments:
      - the @filename argument
      - the path relative to @filename of the current file
      - returns True if the file has to be ignored, and False if the file's contents has to be taken into account
    """
    hobj=hashlib.sha256()
    _update_directory_hash(filename, hobj, "", ignore_func)
    return hobj.hexdigest()

def compute_files_hash(partfile):
    """Mount the partition and computes the hash of all the files in the partition.
    Also create a dictionary of files which that Windows fuck decides to modify to add its onw crap,
    indexed by file name and for which the value is the file hash
    """
    (mapname, mountpoint)=get_encrypted_partition_mapped_elements(partfile)
    mp=mountpoint
    if not mountpoint:
        # mount partition
        mp=tempfile.mkdtemp()
        (status, out, err)=util.exec_sync(["/bin/mount", "-o", "ro", partfile, mp])
        if status!=0:
            raise Exception("Could not mount '%s' to '%s': %s"%(partfile, mp, err))

    # actual hash computation
    fp=compute_directory_hash(mp)

    # cleanups
    if not mountpoint:
        # unmount partition
        (status, out, err)=util.exec_sync(["/bin/umount", partfile])
        if status!=0:
            os.rmdir(mp)
            raise Exception("Could not unmount '%s': %s"%(partfile, err))
        os.rmdir(mp)
    return "%s|%s"%("sha256", fp)

def get_encrypted_partition_mapped_elements(part_name):
    """Get the current map name for the partition (for ex. like "/dev/mapper/luks-82993631-f0c9-4fd6-b97e-53d2f12f714e")
    and the mount point, or (None, None) if not opened"""
    counter=0
    while counter<5:
        (status, out, err)=util.exec_sync(["/bin/lsblk", "-n", "-l", "-p", "-o", "NAME,MOUNTPOINT", part_name])
        if status!=0:
            if "not a block device" in err:
                # kernel might not yet be ready
                counter+=1
                time.sleep(1)
            else:
                raise Exception("Could not get mount status of '%s': %s"%(part_name, err))
        else:
            break
    if status!=0:
        raise Exception("Could not get mount status of '%s': %s"%(part_name, err))
    if out!="":
        for line in out.splitlines():
            if line!="":
                parts=line.split(maxsplit=1)
                if parts[0]==part_name:
                    if len(parts)==2:
                        return (parts[0], parts[1])
                    else:
                        return (parts[0], None)
    return (None, None)

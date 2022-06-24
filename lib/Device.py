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

import time
import os
import tempfile
import shutil
import tarfile
import syslog
import json
import enum

import Utils as util
import Filesystem as filesystem
import PartitionEncryption as enc
import CryptoGen as crypto
import AppendedData as append
import FingerprintHash as fphash

# https://papy-tux.legtux.org/doc1064/index.php

end_reserved_space=5 # MB

#
# Device "formatting" functions according to specifications:
# - define partitions and/or write ISO to device
# - format partitions
# - initialize partition's contents
# - create "signature" data

class Mode(str, enum.Enum):
    """Types de device."""
    DIRECT = "direct"
    LOOP = "loop" # raw images, not yet implemented
    NBD = "nbd"

def _find_nbd_free_dev():
    index=0
    while index<8:
        path="/sys/class/block/nbd%s/size"%index
        if os.path.exists(path):
            size=open(path, "r").read()
            if int(size)==0:
                return "/dev/nbd%s"%index
        index+=1
    raise Exception("No NBD device available (tried %s)"%index)

def _nbd_setup(filename):
    # check /sys/class/block/nbd<X>/size
    # cat /sys/class/block/nbd*/size
    (status, out, err)=util.exec_sync(["modprobe", "-av", "nbd"])
    if status!=0:
        raise Exception("Can't load nbd kernel driver: %s"%err)
    devfile=_find_nbd_free_dev()
    (status, out, err)=util.exec_sync(["qemu-nbd", "-c", devfile, filename])
    if status!=0:
        raise Exception("Can't access to '%s' using the nbd driver: %s"%(filename, err))
    return devfile

def _nbd_cleanup(devfile):
    ensure_kernel_sync(devfile)
    (status, out, err)=util.exec_sync(["qemu-nbd", "-d", devfile])
    if status!=0:
        raise Exception("Can't disconnect the nbd device '%s': %s"%(devfile, err))

def _loop_setup(filename):
    (status, out, err)=util.exec_sync(["losetup", "--show", "-f", filename])
    if status!=0:
        raise Exception("Can't set up file '%s' using a loop device: %s"%(filename, err))
    return out

def _loop_cleanup(devfile):
    ensure_kernel_sync(devfile)
    (status, out, err)=util.exec_sync(["losetup", "-d", devfile])
    if status!=0:
        raise Exception("Can't disconnect from the nbd device '%s': %s"%(devfile, err))

class Device:
    def __init__(self, devfile):
        self._mountpoints={} # key = partition ID, value=TMP directory string where partition is mounted
        self._auto_umount=[] # list mountpoints which are automatically unmounted when object is destroyed
        self._mode=Mode.DIRECT
        self._devfile=None
        self._cached_layout=None

        valid=False
        devfile=os.path.realpath(devfile)
        if not devfile.startswith("/dev/"):
            util.print_event("Setting up loop device")
            devfile=_nbd_setup(devfile)
            self._mode=Mode.NBD
            valid=True
        else:
            if (devfile.startswith("/dev/sd") or devfile.startswith("/dev/vd")) and devfile[-1] not in "0123456789":
                valid=True
            elif devfile.startswith("/dev/nbd") or devfile.startswith("/dev/nvme"):
                valid=True
            elif devfile.startswith("/dev/loop"):
                valid=True
        if not valid:
            raise Exception("Invalid device '%s'"%devfile)
            
        if not os.path.exists(devfile):
            raise Exception("Device or VM image file '%s' does not exist "%devfile)
        self._devfile=devfile

        self._meta=None # meta data read from the device
        self._decryptors=None
        self._part_secrets={}

    def __del__(self):
        # TODO:
        # - only unmount partitions which we have mounted
        # - only "clean" NBD connections (same for losetup in the future) if there is partition still mounted
        #   => means modify _nbd_setup() to use an already existing NBD device if the file is already "mapped"
        #      using an NBD connection. As of Buster, qemu-nbd has no --list option
        for part_id in self._auto_umount.copy():
            tmpdir=self._mountpoints[part_id]
            if tmpdir:
                self.umount(part_id)

        if self._mode==Mode.NBD:
            util.print_event("Cleaning up loop device")
            try:
                _nbd_cleanup(self._devfile)
            except Exception:
                pass

    @property
    def devfile(self):
        """Get the device file, like '/dev/sdb'"""
        return self._devfile

    def format(self, specs):
        """Apply the specifications (any data will be lost), including:
        - formatting the device
        - creating partitions

        This function _assumes_ the provided specifications are correct (i.e. have been generated by a Builder object).
        """
        self._meta=None
        self._cached_layout=None # invalidate any cached layout

        if self._mode==Mode.DIRECT and specs["device"]!=self._devfile:
            raise Exception("Specified device does not match actual device to use")

        # disable cache for that disk
        if self._mode==Mode.DIRECT:
            (status, out, err)=util.exec_sync(["/sbin/hdparm", "-W", "0", self._devfile])
            if status!=0:
                # some devices don't support write-caching feature
                if "Inappropriate ioctl for device" not in err:
                    print("Could not disable disk caching for '%s': %s"%(self._devfile, err))

        # preparation work
        # the @offset variable will contain the number of partitions which were created
        # while writing the ISO file
        leave_existing=False
        offset=0
        firstpart=specs["partitions"][0]
        if "leave-existing" in firstpart:
            layout=analyse_layout(self._devfile)
            offset=len(layout["partitions"]) # number of partitions already existing
            leave_existing=True
        if offset>0:
            disktype=util.LabelType(layout["device"]["type"])
            if disktype!=util.LabelType(specs["type"]):
                print("** 'leave-existing' has been specified but the existing type of disk is not the one in the specifications")
            is_first=False
            min_start_sector=0
            for partdata in layout["partitions"]:
                min_start_sector=max(min_start_sector, partdata["sector-end"])
            min_start_sector+=1
        else:
            util.print_event("Unmounting all partitions")
            self.umount_all()
            util.print_event("Wiping MBR/GPT")
            _wipe_mbr_gpt(self._devfile)
            disktype=util.LabelType(specs["type"])
            is_first=True
            min_start_sector=1

        # create partitions
        for pspec in specs["partitions"]:
            (nb, min_start_sector)=_create_partition(self._devfile, disktype, is_first, pspec, min_start_sector)
            if nb!=None:
                offset=nb
            is_first=False
            ensure_kernel_sync(self._devfile)

        # format partitions
        mapping={} # key=partition number, value=part spec
                   # key=partition ID, value=partition number
                   # mapping ex: {
                   #  "1": {
                   #     "label": "Hehe",
                   #     "filesystem": "exfat",
                   #     "id": "data-partition",
                   #     "encryption": null,
                   #     "password": null,
                   #     "size-mb": 100,
                   #     "immutable": true
                   #  },
                   #  "data-partition": 1
                   # }
        counter=1
        for pspec in specs["partitions"]:
            if "leave-existing" in pspec or "iso-file" in pspec:
                continue
            partnum=counter+offset
            if disktype==util.LabelType.DOS and partnum>4:
                raise Exception("Can't create more than 4 partitions (primary) on msdos devices")
            elif (disktype==util.LabelType.GPT or disktype==util.LabelType.HYBRID) and partnum>128:
                raise Exception("Can't create more than 128 partitions on GPT devices")
            util.wait_for_partition(_partition_name_from_number(self._devfile, counter+offset))
            password=_format_partition(self._devfile, pspec, counter+offset)
            counter+=1

            mapping[partnum]=pspec
            mapping[pspec["id"]]=partnum

        # convert to hybrid if necessary
        if leave_existing==False and disktype==util.LabelType.HYBRID:
            # https://www.rodsbooks.com/gdisk/hybrid.html
            # NB: in presence of hybrid partitions, Windows will only see the partitions listed in the hybrid MBR

            # compute partitions to include in the hybrid MBR
            h_partitions=[]
            for part_id in specs["hybrid-partitions"]:
                h_partitions+=[mapping[part_id]]

            args=["r", "h"] # recovery or transformation mode & make hybrid
            args+=[' '.join(str(i) for i in h_partitions)] # selection of partitions to include
            args+=["N"] # don't place EFI in MBR

            first=True
            for part_num in h_partitions:
                if first:
                    first=False
                    args+=["EF", "Y"] # EF type & mark as bootable
                else:
                    args+=["83", "N"]
            if len(h_partitions)<3:
                args+=["N"] # don't protect more partitions
            args+=["x", "h"] # extra functionality & recompute CHS values
            args+=["w", "Y", ""] # write modifications and exit
            (status, out, err)=util.exec_sync(["/sbin/gdisk", self._devfile], stdin_data="\n".join(args))
            if status!=0:
                raise Exception("Could not create hybrid format: %s"%err)
            ensure_kernel_sync(self._devfile)

    def seal_metadata(self, specs):
        """Generate and write meta data on the device

        This function _assumes_ the provided specifications are correct (i.e. have been generated by a Builder object).
        """
        # generate data used for partitions verifications
        layout=analyse_layout(self._devfile)
        if util.debug:
            print("Sealing Metadata: PSPECS: %s"%json.dumps(specs, indent=4, sort_keys=True))
            print("Sealing Metadata: LAYOUT: %s"%json.dumps(layout, indent=4, sort_keys=True))

        # identify the offset incurred by having an ISO image
        pspec=specs["partitions"][0]
        if "leave-existing" in pspec or "iso-file" in pspec:
            spindex=len(layout["partitions"]) - (len(specs["partitions"]) - 1)
        else:
            spindex=0
        # analyse each partition in the layout
        index=-1
        for part in layout["partitions"]:
            partfile=_partition_name_from_number(self._devfile, part["number"])
            index+=1
            if index>=spindex:
                # this partition has been specified in the specs
                if spindex>0:
                    pspec=specs["partitions"][index-spindex+1]
                else:
                    pspec=specs["partitions"][index]

                part["id"]=pspec["id"]
                enctype=pspec["encryption"]
                imm=pspec["immutable"]
                part["immutable"]=imm
                if imm:
                    self.umount(pspec["id"])
                    if enctype:
                        part["analysed-hash"]=fphash.compute_partition_hash(partfile)
                        syslog.syslog(syslog.LOG_WARNING, "Immutable encrypted data is not yet fully supported, Windows might break things")
                    else:
                        if part["filesystem"] and (filesystem.fstype_from_string(part["filesystem"])==filesystem.FSType.fat or \
                                                    filesystem.fstype_from_string(part["filesystem"])==filesystem.FSType.ntfs):
                            fp=fphash.compute_files_hash(partfile)
                            part["analysed-files-hash"]=fp
                        else:
                            part["analysed-hash"]=fphash.compute_partition_hash(partfile)

                part["encryption"]=enctype
                if enctype:
                    password=pspec["password"]
                    part["password"]=password
                    part["filesystem"]=_probe_encryption(partfile, enctype, password).value
                    part["header"]=_extract_partition_header(partfile, enctype, password)
                    if util.debug:
                        part["header"]=part["header"][1:20]+"...."
            else:
                # this partition has been created by an ISO image or was here before
                part["immutable"]=True
                fstype=None
                if part["filesystem"]:
                    try:
                        fstype=filesystem.fstype_from_string(part["filesystem"])
                    except Exception:
                        pass
                    if part["filesystem"]!="ISO9660":
                        _umount(partfile)
                if fstype in (filesystem.FSType.fat, filesystem.FSType.ntfs):
                    fp=fphash.compute_files_hash(partfile)
                    part["analysed-files-hash"]=fp
                else:
                    part["analysed-hash"]=fphash.compute_partition_hash(partfile)

        # compute partitions table's hash
        fp=fphash.compute_partitions_table_hash(self._devfile, util.LabelType(layout["device"]["type"]))
        layout["device"]["analysed-table-hash"]=fp

        # add meta data and security data
        meta=append.MetaData(self._devfile, specs, layout)
        sec=append.SecurityData(self._devfile, specs, layout)
        meta.write_to_device()
        sec.write_to_device()

    def verify(self, verifiers):
        """Perform device verifications:
        - verify the presence of a DOS or GPT partitioning scheme
        - presence of metadata and security information
        - signature of the metadata
        - device ID's association with metadata
        - verify the partitioning scheme has not been changed
        - validity of table of partition's signature
        - verify that non encrypted filesystems have not changed
        - validity of immutable partition's signatures

        The @verifiers argument is a dictionary of means to verify signatures, where
        keys are verifier "names" (IDs) and values are dictionaries with the following keys:
        - "type": "password" | "key" | "certificate"
        - "password": the password used if type is "password"
        - "public-key-file": the public key to use if type is "key", to perform signature verification
        - "cert-file": the certificate to use if type is "certificate", to perform signature verification
        """
        meta=self._load_meta_data()
        meta.verify(verifiers)
        self._meta=meta
        return meta.get_data()

    def wipe(self):
        """Removes any information from the device"""
        self._meta=None
        self._cached_layout=None # invalidate any cached layout

        # determine device's size
        try:
            specs=analyse_layout(self._devfile)
            #print("SPECS: %s"%json.dumps(specs, indent=4))
            devsize=specs["device"]["hw-id"]["size-bytes"]
        except:
            specs=None
            devsize=None

        # TODO: try to optimize data wiping with encrypted partitions
        if False and specs is not None:
            try:
                for partdata in specs["partitions"]:
                    if partdata["filesystem"]=='ISO9660':
                        pass

                    # TODO: optimise wiping of encrypted partitions
        
                # MBR & GPT structures
                _wipe_mbr_gpt(self._devfile)
                return
            except:
                pass

        # raw wiping
        chunk_size=4*1024*1024 # 4MB at a time
        chunk=b'\0'*chunk_size
        written=0
        with open(self._devfile, "wb", buffering=0) as fd:
            while True:
                if devsize is not None:
                    percent=written*100/devsize
                    util.print_event("%s%% erased"%round(percent, 1))
                try:
                    nb=fd.write(chunk)
                    written+=nb
                except OSError as e:
                    if e.errno==28: # No space left on device
                        break
                    raise e

    def _load_meta_data(self):
        """Loads the meta data, without verifying it"""
        disktype=util.get_device_label_type(self._devfile)
        meta=append.MetaData(self._devfile)
        meta.read_from_device()
        return meta

    def get_unprotected_data(self):
        """Get the unprotected information from the device.
        The "verified" information defines if the device has first been verified or not.
        """
        if self._meta:
            meta=self._meta
        else:
            meta=self._load_meta_data()

        data=meta.get_data()
        res=data["unprotected"].copy()
        res["verified"]=True if meta==self._meta else False
        return res

    def get_protected_data(self, exception_if_no_decryptor=True):
        """Extract information using the decryption secrets provided by calling define_decryptors().
        """
        if self._meta:
            meta=self._meta
        else:
            meta=self._load_meta_data()
        data=meta.get_data()
        prot=data["protected"]

        if not self._decryptors:
            if exception_if_no_decryptor:
                raise Exception("No decryption object defined")
            return prot

        crypto_objects=crypto.create_crypto_objects_list(self._decryptors)
        res={}
        found=False
        for pid in prot:
            if pid in crypto_objects:
                found=True
                cobj=crypto_objects[pid]
                dec=cobj.decrypt(prot[pid])
                dec=dec.decode()
                dec=json.loads(dec)
                res.update(dec)
        if not found:
            raise Exception("No matching decryptor provided")
        return res

    def get_signature_ids(self):
        if self._meta:
            meta=self._meta
        else:
            meta=self._load_meta_data()
        return list(meta.get_signatures().keys())

    def get_decryptor_ids(self):
        """Get the list of decryptor IDs (each ID protects some data using a password or a key)"""
        if self._meta:
            meta=self._meta
        else:
            meta=self._load_meta_data()
        data=meta.get_data()
        return list(data["protected"].keys())

    def get_hardware_id(self):
        """Get the unprotected information from the device"""
        if self._meta:
            meta=self._meta
        else:
            meta=self._load_meta_data()
        data=meta.get_data()
        return data["hw-id"].copy()

    def get_partitions_layout(self):
        """Get the layout of the device's partitions.
        NB: the passwords or other secret to mount encryted partitions will be included the result of this function
            if they have been reviously provided either by:
            - using the set_partition_secret() function
            - using the define_decryptors() function which may (depending on the specifications when the device was created)
              provide the expected secrets
        """
        if self._cached_layout is not None:
            return self._cached_layout
        if self._meta:
            meta=self._meta
        else:
            meta=self._load_meta_data()

        # prepare resulted data
        data=meta.get_data()
        res=data["verif"].copy()
        del res["table-hash"]

        # complement with secrets extracted from the protected data if possible
        if self._decryptors:
            # add decrypted information per partition
            prot=self.get_protected_data()
            # ex. of protected data:
            # {
            #    "@data/password": "MyPassword",
            #    "secret": "This is a secret!"
            # }
            for key in prot:
                if key[0]=="@":
                    parts=key[1:].split("/")
                    if len(parts)!=2:
                        raise Exception("Invalid protected data '%s'"%key)
                    partition_id=parts[0]
                    for partdata in res["partitions"]:
                        if "id" in partdata and partdata["id"]==partition_id:
                            # this may for example translate as: partdata["password"]="MyPassword"
                            partdata[parts[1]]=prot[key]

        # complement with secrets provided by set_partition_secret()
        for partdata in res["partitions"]:
            if "id" in partdata and partdata["id"] in self._part_secrets:
                partition_id=partdata["id"]
                for secret in self._part_secrets[partition_id]:
                    partdata[secret]=self._part_secrets[partition_id][secret]
        self._cached_layout=res
        return res

    def get_partition_info_for_id(self, partition_id):
        """Get a partition's informations"""
        partitions=self.get_partitions_layout()
        for partdata in partitions["partitions"]:
            if "id" in partdata and partdata["id"]==partition_id:
                part_info=partdata.copy()
                partfile=_partition_name_from_number(self._devfile, part_info["number"])
                part_info["part-file"]=partfile
                return part_info
        raise Exception("Could not identify partition with ID '%s'"%partition_id)

    def get_partition_devfile(self, partition_id):
        """Get the device name for the specified partition_id"""
        partitions=self.get_partitions_layout()
        for partdata in partitions["partitions"]:
            if "id" in partdata and partdata["id"]==partition_id:
                return _partition_name_from_number(self._devfile, partdata["number"])
        raise Exception("Could not identify partition with ID '%s'"%partition_id)

    def define_decryptors(self, decryptors):
        """Define decryption secrets to access the protected data, defined as a dictionary
        indexed by decryption object "names" (IDs, as specified in the "decryptors" section of the specifications
        when the device was created), and the values are:
        - "type": "password" | "key" | "certificate"
        - "password": the password used if type is "password"
        - "private-key-file": the private key to use if type is "key" or "certificate"

        If the protected data contains some secrets about encrypted partitions, then they will be extracted
        next time the get_partitions_layout() is called.
        """
        self._decryptors=decryptors

    
    def define_a_decryptor(self, dkey):
        """Try to define a single decryptor object, which can be a file or a password"""
        if os.path.exists(dkey):
            how={"type": "key", "private-key-file": dkey}
        else:
            how={"type": "password", "password": dkey}
        # try to identify a decryptor
        for did in self.get_decryptor_ids():
            decryptor={did: how}
            try:
                self.define_decryptors(decryptor)
                return
            except Exception:
                pass
        raise Exception("Provided private key or password is not a valid decryptor")

    def set_partition_secret(self, partition_id, secret_type, secret_value):
        """Defines a secret to mount a partition.
        Typically @secret_type will be "password", and the associated @secret_value will be the password.
        If @partition_id does not actually exist, then no error or warning is provided.
        """
        if partition_id not in self._part_secrets:
            self._part_secrets[partition_id]={}
        self._part_secrets[partition_id][secret_type]=secret_value
        self._cached_layout=None # invalidate any cached layout

    def get_partition_secret(self, partition_id, secret_type):
        """Retreives a partition secret defined by set_partition_secret()"""
        if partition_id in self._part_secrets and secret_type in self._part_secrets[partition_id]:
            return self._part_secrets[partition_id][secret_type]
        raise Exception("No secret '%s' defined for partition '%s'"%(secret_type, partition_id))

    def _get_partition_enc_object(self, part_info):
        if "encryption" in part_info and part_info["encryption"]:
            partfile=part_info["part-file"]
            if not "password" in part_info:
                raise Exception("No password provided to access partition '%s'"%partfile)
            obj=enc.Enc(part_info["encryption"], partfile, part_info["password"])
            return obj
        return None

    def mount(self, partition_id, mountpoint=None, options=None, auto_umount=True):
        """Mount a partition defined by its ID to the specified mount point or a temporary defined one if not specified.
        If @auto_umount is True, then the partition is unmounted when the @self object is destroyed
        Returns the mounted point.
        """
        if options is not None and not isinstance(options, str):
            raise Exception("Code bug: invalid @options argument")

        # check if partition is already mounted
        mp=self._get_actual_mount_point(partition_id)
        if mp:
            if mountpoint is not None and mountpoint!=mp:
                raise Exception("Partition '%s' is already mounted on '%s'"%(partition_id, mp))
            return mp
        util.print_event("Mounting partition '%s'"%partition_id)

        # identify mount point to use
        if mountpoint:
            realmp=mountpoint
            os.makedirs(realmp, exist_ok=True)
        else:
            realmp=tempfile.mkdtemp()
        self._mountpoints[partition_id]=realmp
        if auto_umount:
            self._auto_umount+=[partition_id]

        # actually mount partition
        part_info=self.get_partition_info_for_id(partition_id)
        encobj=self._get_partition_enc_object(part_info)
        try:
            if encobj:
                encobj.mount(realmp, options)
            else:
                partfile=_partition_name_from_number(self.devfile, part_info["number"])
                time.sleep(1) # make sure the device is here
                if not os.path.exists(partfile):
                    syslog.syslog(syslog.LOG_INFO, "wait a bit")
                    time.sleep(3)

                if options:
                    args=["/bin/mount", "-o", options, partfile, realmp]
                else:
                    args=["/bin/mount", partfile, realmp]
                (status, out, err)=util.exec_sync(args)
                if status!=0:
                    raise Exception("Could not mount partition '%s': %s"%(partfile, err))

                counter=0
                while True:
                    amp=self._get_actual_mount_point(partition_id)
                    if amp is None:
                        counter+=1
                        if counter>=50:
                            raise Exception("Could not mount partition '%s': could not tell if it was correctly mounted!"%partition_id)
                        time.sleep(0.2)
                    elif amp==realmp:
                        break
                    else:
                        raise Exception("Partition '%s' has been mounted on '%s' when asked to be mounted on '%s'"%
                                        (partition_id, amp, realmp))
            return realmp
        except Exception as e:
            if not mountpoint and partition_id in self._mountpoints:
                del self._mountpoints[partition_id]
            if auto_umount:
                self._auto_umount.remove(partition_id)
            raise e

    def umount(self, partition_id):
        """Unmount a mounted partition"""
        if partition_id not in self._mountpoints:
            mp=self._get_actual_mount_point(partition_id)
            if mp:
                (status, out, err)=util.exec_sync(["/bin/umount", mp])
                if status!=0:
                    raise Exception("Could not umount partition '%s': %s"%(partition_id, err))
            return

        mp=self._mountpoints[partition_id]
        util.print_event("Unmounting partition '%s'"%partition_id)

        part_info=self.get_partition_info_for_id(partition_id)
        encobj=self._get_partition_enc_object(part_info)
        if encobj:
            encobj.umount()
        else:
            (status, out, err)=util.exec_sync(["/bin/umount", mp])
            if status!=0:
                partfile=_partition_name_from_number(self.devfile, part_info["number"])
                raise Exception("Could not umount partition '%s': %s"%(partfile, err))
        if mp.startswith("/tmp"):
            os.rmdir(mp)

        if partition_id in self._mountpoints:
            del self._mountpoints[partition_id]
        if partition_id in self._auto_umount:
            self._auto_umount.remove(partition_id)

    def umount_all(self):
        """Unmount all the mounted partitions for the device"""
        mounted=list(self._mountpoints.keys())
        for part_id in mounted:
            tmpdir=self._mountpoints[part_id]
            if tmpdir:
                self.umount(part_id)

        # clean any remaining partitions which may have been mounted by another program
        if self._devfile:
            umount_all_partitions(self._devfile)

    def _get_actual_mount_point(self, partition_id):
        """Get the actual current mount point of the specified partition, return None if not mounted"""
        part_info=self.get_partition_info_for_id(partition_id)
        if part_info["encryption"]:
            (mapped, mountedpoint)=util.get_encrypted_partition_mapped_elements(part_info["part-file"])
            return mountedpoint
        else:
            part_name=part_info["part-file"]
            counter=0
            while counter<20: # wait up to 10'
                (status, out, err)=util.exec_sync(["/bin/lsblk", "-n", "-l", "-p", "-o", "MOUNTPOINT", part_name])
                if status!=0:
                    if "not a block device" in err:
                        # kernel might not yet be ready
                        counter+=1
                        time.sleep(0.5)
                    else:
                        raise Exception("Could not get mount status of '%s': %s"%(part_name, err))
                else:
                    return out if out!="" else None
            raise Exception("Could not get mount status of '%s': %s"%(part_name, err))

    def copy_file(self, partition_id, source_file, destination_file, owner=None, mode=None):
        """Copy a file or a directory (recursively) to the specified partition on the device,
        at the location specified by @destination_directory (from the root of the device's filesystem
        of the partition.

        If @source_file is a directory:
        - if it ends with "/" then the contents of the directory is copied to @destination_file (which should be a directory)
        - otherwise, the directory itself (and its contents) is copied to @destination_file

        @owner can be a unix owner string like "root.root", and @mode a permission like "644"
        """
        # sanity check
        if not os.path.isfile(source_file) and not os.path.isdir(source_file):
            raise Exception("Invalid file to copy '%s'"%source_file)
        if not os.path.isabs(destination_file):
            raise Exception("Destination file must be absolute")

        # mount partition if necessary
        mountpoint=self.mount(partition_id)

        # actual copy
        full_destination_file="%s%s"%(mountpoint, destination_file)
        full_destination_dir=os.path.dirname(full_destination_file)

        # make destination directory
        os.makedirs(full_destination_dir, exist_ok=True)

        # adapt source_file
        slashdir=False
        if os.path.isdir(source_file) and source_file[-1]=="/":
            slashdir=True
        source_file=os.path.realpath(source_file)

        # actual copy
        if slashdir:
            os.makedirs(full_destination_file, exist_ok=True)
            for subfile in os.listdir(source_file):
                self.copy_file(partition_id, "%s/%s"%(source_file, subfile), destination_file, owner, mode)
        else:
            fullpath=os.path.abspath(source_file)
            filepart=os.path.basename(fullpath)
            args=["/bin/cp", "-dR", source_file, full_destination_file]
            (status, out, err)=util.exec_sync(args)
            if status!=0:
                raise Exception("Could not copy '%s' to device: %s"%(source_file, err))

            if owner:
                shutil.chown(full_destination_file, owner)

            if mode:
                os.chmod(full_destination_file, int(mode, 8))

    def compute_inter_partitions_hash(self):
        """For each inter partition (excluding the partitions table), compute the hash of the contents, linked with the
        hash of the previous inter partition space.
        Returns an array of objects in the form {<what inter space>: <cumumated hash>}"""
        log=[]
        hash="Let's not start at zero!"
        layout=self.get_partitions_layout()
        partitions=layout["partitions"]
        ftype=util.LabelType(layout["type"])
        #print("Partitions: %s"%json.dumps(self.get_partitions_layout(), indent=4))

        if ftype==util.LabelType.DOS:
            istart=1
        else:
            istart=34
        sectorsize=None
        for partdata in partitions:
            if sectorsize is None:
                sectorsize=int(partdata["size-bytes"]/(partdata["sector-end"]-partdata["sector-start"]+1))
            
            iend=partdata["sector-start"]-1
            #print("   Inter partition %s - %s... "%(istart, iend), end="", flush=True)
            ihash=fphash.compute_file_hash(self._devfile, istart*sectorsize, iend*sectorsize)
            #print("%s"%hash)
            hash=fphash.chain_integity_hash(hash, ihash)
            log+=[{"<%s"%partdata["id"]: hash[:5]}]

            # next inter partition start position
            istart=partdata["sector-end"]+1
        return (hash, log)

    def _get_efi_partition(self):
        """Identify the EFI partition, which must be of type "EFI".
        Returns the EFI partition's informations"""
        partitions=self.get_partitions_layout()
        for partdata in partitions["partitions"]:
            if partdata["type"]=="EFI":
                part_info=partdata.copy()
                partfile=_partition_name_from_number(self._devfile, part_info["number"])
                part_info["part-file"]=partfile
                return part_info
        raise Exception("Could not identify EFI partition")

    def install_grub_efi(self, boot_binaries_archive):
        """Installs the Grub signed binaries in the EFI partition, along with the shim's secureboot signed binaries"""
        # find the EFI partition
        efipart=self._get_efi_partition()
        efipartid=efipart["id"]

        # copy binaries to EFI partition
        mp=self.mount(efipartid)
        target_dir="%s/EFI/boot"%mp
        os.makedirs(target_dir, exist_ok=True)
        tarobj=tarfile.open(boot_binaries_archive, mode="r|xz")
        tarobj.extractall(target_dir)

    def install_grub_bios(self):
        """Installs the BIOS version of Grub in the hybrid MBR
        NB: - the --force is required to install in the hybrid environment
            - no Grub configuration file is created

        Grub's associated files will be stored on the EFI partition.

        SEE:
          - https://willhaley.com/blog/custom-debian-live-environment/
          - https://wiki.archlinux.fr/GRUB/Trucs_et_Astuces#Installation_sur_clef_USB_externe
        """
        # find the EFI partition
        efipart=self._get_efi_partition()

        # 1st partition must be a "BIOS boot" partition, otherwise Grub seems to hate it
        layout=self.get_partitions_layout()
        part=layout["partitions"][0]
        if part["type"]!="BIOS":
            raise Exception("1st partition must be 'BIOS' in order to install Grub BIOS")

        mp=self.mount(efipart["id"])

        # install Grub BIOS itself, depending if the grub-pc package is installed on the system (which may
        # not be the case on UEFI systems)
        if os.path.exists("/usr/lib/grub/i386-pc"):
            # Grub for BIOS is installed on the system.
            args=["/usr/sbin/grub-install", "--root-directory=%s"%mp, "--force", "--target=i386-pc", self.devfile]
        else:
            # Grub for BIOS is installed on the system: use a 'grub-bios' Docker container
            args=["docker", "run", "--privileged", "--rm", "-v", "%s:/efi"%mp, "grub-bios", "grub-install", "--root-directory=/efi", "--force", "--target=i386-pc", self.devfile]
        syslog.syslog(syslog.LOG_INFO, "GRUB BIOS command: %s"%" ".join(args))
        (status, out, err)=util.exec_sync(args)
        if status!=0:
            raise Exception("Could not install Grub BIOS on device '%s': %s"%(self.devfile, err))

    def install_grub_configuration(self, conf_tar_file, live_partition_id):
        """Install Grub's configuration files in the EFI partition, and
        creates a GRUB configuration.
        Returns the actual directories where GRUB config files are (for both Legacy and UEFI modes)"""
        # find the EFI partition
        efipart=self._get_efi_partition()

        # identify the 1st partition which will contain the Live files
        livepart=self.get_partition_info_for_id(live_partition_id)
        livepartfile=livepart["part-file"]

        # get the FS's UUID
        (status, out, err)=util.exec_sync(["/sbin/blkid", "-s", "UUID", livepartfile])
        if status!=0:
            raise Exception("Could not get UUID of partition '%s': %s"%(livepartfile, err))
        parts=out.split('"')
        livepartuuid=parts[1]

        # copy files to EFI partition
        mp=self.mount(efipart["id"])
        dirs=["%s/EFI/debian"%mp, "%s/boot/grub"%mp]
        for target_dir in dirs:
            os.makedirs(target_dir, exist_ok=True)
            tarobj=tarfile.open(conf_tar_file, mode='r')
            tarobj.extractall(target_dir)

            # create bootparams.cfg files, one for each live Linux partition
            bootparams_file="%s/bootparams.cfg"%target_dir
            util.write_data_to_file("set bootuuid=%s\n"%livepartuuid, bootparams_file)
        return dirs

def analyse_layout(devfile):
    try:
        serial=util.get_device_serial(devfile)
    except Exception:
        serial=""
    model=util.get_device_model(devfile)

    # get size (output is in bytes)
    (disksize, sectorsize)=util.get_disk_sizes(devfile)

    # determine if we have a hybrid partition type using gdisk
    disktype=util.get_device_label_type(devfile)

    # read partitions & general info
    (status, out, err)=util.exec_sync(["/sbin/fdisk", "-l", "--bytes", "-o" , "Device,Start,End,Sectors,Size,Type", devfile], C_locale=True)
    if status!=0:
        raise Exception("Could not get information about device '%s': %s"%(devfile, err))

    for line in out.splitlines():
        if line.startswith("Sector size:"):
            parts=line.split()
            sectorsize=int(parts[3])
            if sectorsize!=int(parts[6]):
                raise Exception("Weird sector size info: %s"%line)

    res={
        "device": {
            "devfile": devfile,
            "hw-id": {
                "model": model,
                "serial": serial,
                "size-bytes": disksize,
            },
            "type": disktype,
            "sector-size": sectorsize
        },
        "partitions": [],
    }

    # partitions
    for line in out.splitlines():
        if line.startswith(devfile):
            parts=line.split(maxsplit=5)
            fsd=util.get_partition_infos(parts[0], enforce_known_filesystem=False)
            parttype=parts[5].lower()
            if parttype.startswith("bios"):
                ptype="BIOS"
            elif parttype.startswith("linux"):
                ptype="LINUX"
            elif parttype.startswith("efi"):
                ptype="EFI"
            else:
                ptype=None

            data={
                "size-mb": bytes_to_mb(int(parts[4])),
                "size-bytes": int(parts[4]),
                "filesystem": fsd[0],
                "label": fsd[1],
                "number": _partition_number_from_name(devfile, parts[0]),
                "sector-start": int(parts[1]),
                "sector-end": int(parts[2]),
                "type": ptype,
                "devfile-ext": parts[0][len(devfile):]
            }
            res["partitions"]+=[data]

    #print("LAYOUT of %s is: %s"%(devfile, json.dumps(res, indent=4)))
    return res

def _partition_number_from_name(devfile, partfile):
    """Extract the partition number from its name and the device file.
    ex: /dev/sda2 => 2
        /dev/nbd0p3 => 3
    """
    pnum=partfile[len(devfile):]
    if pnum[0]=="p":
        pnum=pnum[1:]
    return int(pnum)

def _partition_name_from_number(devfile, partnumber):
    """Does the reverse of _partition_number_from_name()
    """
    if devfile[-1] in "0123456789":
        return "%sp%d"%(devfile, partnumber)
    return "%s%d"%(devfile, partnumber)

#
# Utility functions
#
def ensure_kernel_sync(devfile):
    """Make sure the OS knows about the new partitions"""
    # Also: usr/sbin/blockdev --rereadpt <devfile>

    counter=0
    time.sleep(3)
    while counter<10:
        counter+=1
        (status, out, err)=util.exec_sync(["/sbin/partprobe", devfile], timeout=5)
        if status==250: # timeout
            time.sleep(2)
        elif status!=0:
            if "we have been unable to inform the kernel" in err:
                time.sleep(2)
            elif not "The driver descriptor says the physical block size" in err:
                raise Exception("Could not run partprobe on '%s': %s"%(devfile, err))
            else:
                return
        else:
            return
    raise Exception("Partprobe timed out")

def mb_to_sectors(mb, sect_size):
    return int(mb*1000000/sect_size)

def bytes_to_mb(size):
    return size/1000000

def mb_to_bytes(size):
    return size*1000000

def _write_iso(devfile, iso_file):
    import DDTool as ddt
    obj=ddt.DDTool(devfile, iso_file)
    obj.write()

def _align_boundary(sector):
    # check https://developer.ibm.com/tutorials/l-4kb-sector-disks/
    return (int((sector-1)/2048)+1)*2048 # align to a multiple of 2048

def _create_partition(devfile, disktype, is_first, pspec, min_start_sector):
    """Returns a couple:
    [0] the actual number of partitions created by an ISO, or None if no ISO file was used
    [1] the minimum start sector for the next partition

    @dev_file: is a device file name like '/dev/sdb'
    @disktype: GPT or msdos
    @is_first: indicates if the partition is the first on the device (which means sfdisk will create
               a new partition table)
    @pspec: partition's specifications
    @min_sector: minimum start sector for the partition to create or None
    """
    if "id" in pspec:
        util.print_event("Creating partition '%s'"%pspec["id"])
    else:
        util.print_event("Creating 'start' partition")
    if not isinstance(disktype, util.LabelType):
        raise Exception("Invalid @disktype argument '%s'"%disktype)
    if "leave-existing" in pspec or "iso-file" in pspec:
        layout=analyse_layout(devfile)
        if "iso-file" in pspec:
            if len(layout["partitions"])>0:
                raise Exception("Can't accept ISO file specification if there is already a partition")
            if min_start_sector!=1:
                raise Exception("ISO image is always writen from the 1st sector")
            _write_iso(devfile, pspec["iso-file"])
            layout=analyse_layout(devfile)

        if len(layout["partitions"])==0:
            raise Exception("ISO image did not create any partition")
        if layout["device"]["type"] not in ("dos", "gpt"):
            print("** Detected partitionning after ISO writing is '%s', expect some problems"%layout["device"]["type"])
        #print("ISO created %d partition(s)"%len(layout["partitions"]))

        part=layout["partitions"][len(layout["partitions"])-1]
        analysed_sector_end=part["sector-end"]
        next_min_start_sector=analysed_sector_end+1
        if "size-mb" in pspec:
            size_mb=pspec["size-mb"]
            if size_mb<=0:
                raise Exception("Invalid 'size-mb' specification of %d"%size_mb)
            sectorsize=layout["device"]["sector-size"]
            max_sector_end=mb_to_sectors(size_mb, sectorsize)
            if analysed_sector_end>max_sector_end:
                raise Exception("ISO image is too big for the allowed size of %d Mb"%size_mb)
            next_min_start_sector=max_sector_end
        return (len(layout["partitions"]), next_min_start_sector)

    else:
        # analyse current setup
        layout=analyse_layout(devfile)
        if not is_first:
            disktype=util.LabelType(layout["device"]["type"]) # the actual disk type may be different than the expected one
                                                              # in case we wrote an ISO and were wrong on the disk type it created

        # start sector
        disksize=layout["device"]["hw-id"]["size-bytes"]
        sectorsize=layout["device"]["sector-size"]

        if (disktype==util.LabelType.GPT or disktype==util.LabelType.HYBRID) and min_start_sector<65535:
            min_start_sector=65535
        min_start_sector=_align_boundary(min_start_sector)

        # end sector
        max_end_sector=(disksize-end_reserved_space*1000000)/sectorsize
        size_mb=pspec["size-mb"]
        if size_mb!=None:
            size_mb=int(size_mb)
            if size_mb>0:
                end_sector=min_start_sector+size_mb*1000000/sectorsize
                if end_sector>max_end_sector:
                    end_sector=max_end_sector
            else:
                end_sector=max_end_sector+size_mb*1000000/sectorsize
                if end_sector<min_start_sector:
                    raise Exception("No space left on device to create partition '%s'"%pspec["label"])
        else:
            end_sector=max_end_sector
        end_sector=_align_boundary(end_sector)

        if end_sector-min_start_sector<=0:
            raise Exception("No space left on device to create partition '%s'"%pspec["label"])

        # actual partition creation
        if is_first:
            nb_existing_partitions=0
            # create partitions table
            if disktype==util.LabelType.DOS:
                specs="o\nw\n"
            else:
                specs="g\nw\n"
            try:
                run_fdisk_commands(devfile, specs)
                ensure_kernel_sync(devfile)
            except Exception as e:
                raise Exception("Could not create partition table of type '%s': %s"%(disktype.value, str(e)))
        else:
            nb_existing_partitions=len(layout["partitions"])

        if disktype==util.LabelType.DOS:
            if nb_existing_partitions==3: # partition number 4 is automatically selected
                specs="n\np\n%d\n%d\nw\n"%(min_start_sector, end_sector) # select a primary partition
            else:
                specs="n\np\n\n%d\n%d\nw\n"%(min_start_sector, end_sector) # select a primary partition
        else:
            specs="n\n\n%d\n%d\nw\n"%(min_start_sector, end_sector)
        try:
            run_fdisk_commands(devfile, specs)
            ensure_kernel_sync(devfile)
        except Exception as e:
            raise Exception("Could not add partition: %s"%str(e))

        layout=analyse_layout(devfile)
        part=layout["partitions"][len(layout["partitions"])-1]
        analysed_sector_end=part["sector-end"]
        next_min_start_sector=analysed_sector_end+1

        # if partition type is specified, set it now
        ptype=pspec["type"]
        if ptype:
            if disktype==util.LabelType.GPT or disktype==util.LabelType.HYBRID:
                if ptype=="BIOS":
                    code="4"
                elif ptype=="EFI":
                    code="1"
                elif ptype=="LINUX":
                    code="20"
                else:
                    raise Exception("Unknown partition type '%s'"%ptype)
            else:
                if ptype=="BIOS" or ptype=="EFI":
                    raise Exception("Partition type '%s' not compatible with DOS device"%ptype)
                elif ptype=="LINUX":
                    code="83"
                else:
                    raise Exception("Unknown partition type '%s'"%ptype)
            try:
                if part["number"]==1: # partition number is not asked as there is only one
                    command="t\n%s\nw\n"%code
                else:
                    command="t\n%d\n%s\nw\n"%(part["number"], code)
                run_fdisk_commands(devfile, command)
            except Exception as e:
                raise Exception("Could not define partition '%s' as type '%s': %s"%(pspec["id"], ptype, str(e)))

        return (None, next_min_start_sector)

def run_fdisk_commands(devfile, commands):
    """Internal function to execute an FDISK commands sequence.
    Use with care (fdisk does not behave the same way for GPT and DOS schemes)!"""
    (status, out, err)=util.exec_sync(["/sbin/fdisk", devfile], C_locale=True, stdin_data=commands)
    if status!=0:
        if "reading the partition table failed" in err:
            if devfile.startswith("/dev/loop"):
                return
            # weird error sometimes happening
            counter=0
            while True:
                os.sync()
                time.sleep(1)
                (status, out, err2)=util.exec_sync(["/sbin/fdisk", devfile], stdin_data="w\n")
                if status==0 or (status!=0 and "Permission denied" in err):
                    break
                counter+=1
                if counter>10:
                    raise Exception(err2)
        else:
            raise Exception(err)

def _format_partition(devfile, pspec, part_number):
    """Format a partition according to the specs.
    Returns the actual password if an encryption layer was set up
    """
    if "iso-file" in pspec:
        # nothing to do
        return None
    else:
        util.print_event("Formatting partition '%s'"%pspec["id"])
        # get filesystem to use
        fstype=None
        fslabel=None
        fsvol=None
        if "filesystem" in pspec:
            fstype=filesystem.fstype_from_string(pspec["filesystem"])
            fslabel=pspec["label"]
            fsvol=pspec["volume-id"]

        # partition formatting
        part_name=_partition_name_from_number(devfile, part_number)
        util.wait_for_partition(part_name)
        password=None
        if "encryption" in pspec and pspec["encryption"]:
            enctype=pspec["encryption"]
            if "password" in pspec:
                password=pspec["password"]
            if password==None:
                import string
                password=crypto.generate_password(length=12, alphabet=string.ascii_letters+string.digits)
            obj=enc.Enc(enctype, part_name, password=password)
            obj.create()

            if fstype:
                (status, out, err)=util.exec_sync(["/bin/ls", "/dev/mapper"])
                mapped=obj.open()
                filesystem.create_filesystem(mapped, fstype, fslabel, fsvol)
                obj.close()

            return password

        elif fstype:
            filesystem.create_filesystem(part_name, fstype, fslabel, fsvol)
            return None

def _umount(what):
    """Unmount a single filesystem"""
    (status, out, err)=util.exec_sync(["/bin/umount", what])
    if status!=0:
        if not err.endswith(" not mounted."):
            raise Exception("Could not unmount '%s': %s"%(what, err))
            
def umount_all_partitions(devfile):
    """Unmount all the partitions of the @devfile device, and close any encrypted volume"""
    counter=0
    while counter<util.lsblk_wait_time:
        (status, out, err)=util.exec_sync(["/bin/lsblk", "-n", "-p", "-o", "NAME,MOUNTPOINT", devfile],
                                        C_locale=True)
        if status!=0:
            if "not a block device" in err:
                # kernel might not yet be ready
                counter+=1
                time.sleep(1)
            else:
                raise Exception("Could not get mount status of '%s': %s"%(devfile, err))
        else:
            break

    if out!="":
        last_part_name=None
        for line in out.splitlines():
            if line!="":
                # remove the hierarchical information in the output (we can't use -l because
                # the order is not preserved)
                parts=line.split("/", 1)
                line="/"+parts[1]
                parts=line.split(maxsplit=1)
                if len(parts)==2:
                    _umount(parts[1])
                if parts[0].startswith("/dev/mapper/"):
                    ext=parts[0][12:]
                    if ext.startswith("luks") or ext.startswith("secluks"):
                        obj=enc.Enc("luks", last_part_name)
                        obj.close()
                    elif ext.startswith("veracrypt"):
                        obj=enc.Enc("veracrypt", last_part_name)
                        obj.close()
                else:
                    last_part_name=parts[0]

def _wipe_mbr_gpt(devfile):
    """Remove the MSDOS/GTP partitioning information"""
    # https://fr.wikipedia.org/wiki/GUID_Partition_Table
    disktype=_determine_partition_table_label(devfile)
    umount_all_partitions(devfile)

    if disktype==util.LabelType.DOS:
        fd=open(devfile, "rb+")
        fd.seek(0)
        fd.write(b'\0'*512) # clear MBR
    else:
        fd=open(devfile, "rb+")
        # primary GPT header
        fd.seek(0)
        fd.write(b'\0'*512*34)
        # secondary GPT header
        fd.seek(-512*34, 2)
        fd.write(b'\0'*512*34)

    (status, out, err)=util.exec_sync(["/sbin/wipefs", "-a", devfile])
    ensure_kernel_sync(devfile)
    if status!=0:
        raise Exception("Could not wipe filesystem signatures from '%s': %s"%(devfile, err))

    # remove any remaining metadata
    fd=open(devfile, "rb+")
    to_write=20
    fd.seek(-to_write*1024*1024, 2)
    while to_write>0:
        to_write-=1
        fd.write(b'\0'*1024*1024)
    fd.close()
    
def _determine_partition_table_label(devfile):
    """Determine if partitions table if GPT or MSDOS"""
    (status, out, err)=util.exec_sync(["/sbin/sfdisk", "-l", "--bytes", "-o" , "Device,Start,End,Sectors,Size", devfile], C_locale=True)
    if status!=0:
        raise Exception("Could not get information about device '%s': %s"%(devfile, err))

    for line in out.splitlines():
        if line.startswith("Disklabel type:"):
            parts=line.split()
            return util.LabelType(parts[2])
    return None

def _probe_encryption(partfile, enctype, password):
    """Probe the partition @partfile with encryption type and password,
    returns the filesystem type"""
    try:
        obj=enc.Enc(enctype, partfile, password=password)
        mapfile=obj.is_opened()
        if mapfile==False:
            mapfile=obj.open()
            fstype=filesystem.probe(mapfile)
            obj.close()
        else:
            fstype=filesystem.probe(mapfile)
        return fstype
    except Exception as e:
        raise Exception("Error probing encrypted partition '%s': %s"%(partfile, str(e)))

def _extract_partition_header(partfile, enctype, password):
    """Extract headers of encrypted partitions"""
    obj=enc.Enc(enctype, partfile, password=password)
    tmp=obj.read_header()
    header=tmp.get_contents(binary=True)
    return crypto.data_encode_to_ascii(header)

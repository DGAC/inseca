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
#

# This object initialises an admin environment created from a 

import os
import datetime
import json
import tempfile
import syslog
import Utils as util
import PartitionEncryption as enc
import Device
import CryptoPass as cpass
import SpecBuilder
import Live

class Context:
    def __init__(self):
        # key validity
        self._valid_to=None
        keydata=json.loads(util.load_file_contents("/opt/share/keyinfos.json"))
        if "valid-to" in keydata and keydata["valid-to"]!=None:
            self._valid_to=keydata["valid-to"]

        # UI environment variables
        self._live_env=Live.Environ()

        live_devpart=util.get_root_live_partition()
        self._live_devfile=util.get_device_of_partition(live_devpart)
        self._live_env.define_UI_environment()

        # device status
        self._dummy_partfile=None # dummy partition device file
        self._internal_partfile=None # /internal partition device file
        self._compute_extra_partitions()
        self._embedded_fs_mountpoint_obj=None
        self._dummy_mountpoint_obj=None

        # load the UI settings
        dconf_file="/opt/dconf.txt"
        if os.path.exists(dconf_file):
            data=util.load_file_contents(dconf_file)
            os.seteuid(self._live_env.uid) # switch to user
            (status, out, err)=util.exec_sync(["dconf", "load", "/"], stdin_data=data) # DConf needs to be run as the same user and with the correct env. variables
            if status!=0:
                syslog.syslog(syslog.LOG_ERR, "Could not load DConf settings: %s"%err)
            else:
                syslog.syslog(syslog.LOG_INFO, "Loaded DConf settings")
            os.seteuid(0) # back to root
        else:
            syslog.syslog(syslog.LOG_WARNING, "No DConf settings defined")

    @property
    def is_initialized(self):
        """Tells if the device has already been initialized"""
        return self._internal_partfile is not None

    @property
    def internal_partfile(self):
        return self._internal_partfile

    @property
    def is_valid(self):
        """Tells if the key is still valid (from a calendar point of view)"""
        if self._valid_to:
            now=datetime.datetime.utcnow()
            now=int(now.timestamp())
            if now>self._valid_to:
                return False
        return True

    @property
    def is_unlocked(self):
        """Tells if the device is unlocked"""
        return self._live_env.unlocked

    def _compute_extra_partitions(self):
        """Analyse the device and determine if the "dummy" and "internal" partitions exist.
        If they don't but the appended data has references to the start and end of these partitions
        (which may have been "undeclared"" as the result of someone re-writing the 'ISO' image),
        the partitions are 'redeclared' using that data."""
        dev=Device.Device(self._live_devfile)
        layout=Device.analyse_layout(self._live_devfile)
        try:
            data=dev.get_unprotected_data() # no exception => this device has already been initialized at some point
            nb=len(layout["partitions"])
            if nb==4:
                # we've got all the expected partitions
                lastpart=layout["partitions"][nb-1]
                size=layout["device"]["hw-id"]["size-bytes"]
                sectsize=layout["device"]["sector-size"]
                totalnbsect=size/sectsize
                partsect=lastpart["sector-end"]

                remain_b=(totalnbsect-partsect) *sectsize
                if remain_b <= (Device.end_reserved_space + 1)*1000*1000:
                    if nb<=2:
                        raise Exception("Device was probably created using the wrong tool")
                    else:
                        self._internal_partfile="%s%s"%(self._live_devfile, lastpart["number"])
                        self._dummy_partfile="%s%s"%(self._live_devfile, lastpart["number"]-1)
            elif nb==2:
                # partitions may have been 'undeclared' by an ISO re-write, try to 'redeclare' them
                start_sect=data["dummy-start-sect"]
                end_sect=data["dummy-end-sect"]
                commands="n\n\n\n%d\n%d\nw\n"%(start_sect, end_sect)
                Device.run_fdisk_commands(self._live_devfile, commands)
                Device.ensure_kernel_sync(self._live_devfile)

                start_sect=data["int-start-sect"]
                end_sect=data["int-end-sect"]
                commands="n\np\n%d\n%d\nw\n"%(start_sect, end_sect) # partition 4 is automatically selected here
                Device.run_fdisk_commands(self._live_devfile, commands)
                Device.ensure_kernel_sync(self._live_devfile)
                syslog.syslog(syslog.LOG_INFO, "Partitions recreated!")

                self._compute_extra_partitions()
            else:
                # device was from a previous installation, ignore that
                pass
        except:
            # device has not yet been initialized, only check it looks good, don't do anything else here
            nb=len(layout["partitions"])
            if nb!=2:
                raise Exception("Not an INSECA admin device")

    def _get_embedded_offset(self):
        """Mount the EFI partition and read the contents of the key-offset file"""
        layout=Device.analyse_layout(self._live_devfile)
        mp=None
        for part in layout["partitions"]:
            if part["type"]=="EFI":
                mp=tempfile.TemporaryDirectory()
                (status, out, err)=util.exec_sync(["mount", "-o", "ro",
                                                   "%s%s"%(self._live_devfile, part["devfile-ext"]), mp.name])
                if status!=0:
                    raise Exception("Could not mount EFI partition: %s"%err)
                break
        if mp is None:
            raise Exception("Invalid device: could not find the EFI partition!")
        path="%s/key-offset"%mp.name
        try:
            if not os.path.exists(path):
                raise Exception("Invalid device: missing key-offset file")
            try:
                offset=int(util.load_file_contents(path))
                if offset<0:
                    raise Exception()
                return offset
            except:
                raise Exception("Invalid device: invalid key-offset value")
        finally:
            (status, out, err)=util.exec_sync(["umount", mp.name])

    def _mount_embedded_fs(self):
        """Actually mount the embedded filesystem"""
        if self._embedded_fs_mountpoint_obj is not None:
            return self._embedded_fs_mountpoint_obj.name
        offset=self._get_embedded_offset()
        mp=tempfile.TemporaryDirectory()
        (status, out, err)=util.exec_sync(["mount", "-o", "loop,rw,offset=%d"%offset, self._live_devfile, mp.name])
        if status!=0:
            raise Exception("Could not mount extra data: %s"%err)
        self._embedded_fs_mountpoint_obj=mp
        return mp.name

    def _umount_embedded_fs(self):
        """Unmount the embedded filesystem"""
        if self._embedded_fs_mountpoint_obj is None:
            return
        (status, out, err)=util.exec_sync(["umount", self._embedded_fs_mountpoint_obj.name])
        self._embedded_fs_mountpoint_obj=None


    def _mount_dummy(self):
        """Mount the dummy partition"""
        if self._dummy_partfile is None:
            raise Exception("Device is not yet initialized")
        if self._dummy_mountpoint_obj is not None:
            return self._dummy_mountpoint_obj.name
        mp=tempfile.TemporaryDirectory()
        (status, out, err)=util.exec_sync(["mount", self._dummy_partfile, mp.name])
        if status!=0:
            raise Exception("Could not mount extra data: %s"%err)
        self._dummy_mountpoint_obj=mp
        return mp.name

    def _umount_dummy(self):
        """Unmount the dummy partition"""
        if self._dummy_mountpoint_obj is None:
            return
        (status, out, err)=util.exec_sync(["umount", self._dummy_mountpoint_obj.name])
        self._dummy_mountpoint_obj=None


    def decrypt_config(self, code):
        """Decrypt the config.txz.enc file stored in the embedded filesystem using the
        specified code (password).
        Returns a tmp file object which containes the decrypted data"""
        try:
            # mount the embedded filesystem
            mp=self._mount_embedded_fs()

            # decrypt the config.txz.enc file
            path="%s/config.txz.enc"%mp
            if not os.path.exists(path):
                raise Exception("Invalid device: no config.txz.enc file")
            edata=util.load_file_contents(path)
            eobj=cpass.CryptoPassword(code)
            return eobj.decrypt(edata, return_tmpobj=True)
        except Exception:
            raise Exception("Invalid code")
        finally:
            self._umount_embedded_fs()

    def _get_internal_password(self, user_password):
        """Uses the blob0.json file of the embedded filesystem to decrypt the internal partition's password.
        Returns the (internal password, user CN) tuple for the user for which @user_password is correct"""
        mp=self._mount_dummy()
        try:
            path="%s/resources/blob0.json"%mp
            if not os.path.exists(path):
                raise Exception("Device has not yet been initialized")
            users=json.loads(util.load_file_contents(path))
            for user_uuid in users:
                userdata=users[user_uuid]
                try:
                    if "salt" in userdata:
                        salt=userdata["salt"]
                    else:
                        salt="not really some salt" # for INSECA created before using the password hardening with salt
                    password=cpass.harden_password_for_blob0(user_password, salt)
                    eobj=cpass.CryptoPassword(password)
                    return (eobj.decrypt(userdata["enc-blob"]), userdata["cn"])
                except:
                    pass
            raise Exception("Invalid password")
        finally:
            self._umount_dummy()

    def declare_user(self, name, user_password, internal_password):
        """Declare/modify a user in the blob0.json file (which is created on first call)."""
        mp=self._mount_dummy()
        try:
            Live.declare_user(mp, name, user_password, internal_password)
        finally:
            self._umount_dummy()

    def get_users(self):
        """List all declared users"""
        mp=self._mount_dummy()
        try:
            return Live.get_users(mp)
        finally:
            self._umount_dummy()

    def delete_user(self, name):
        """Delete a user, independently of the authentication method (no error if user did not exist)"""
        name=name.lower()
        mp=self._mount_dummy()
        try:
            Live.delete_user(mp, name, None) # we don't keep user config data in the live admin environment
        finally:
            self._umount_dummy()
            self._umount_internal()

    def init_device(self, password):
        """Creates the "dummy" and "internal" partitions on the device and add the associated meta data
        The @password is the password the internal partition will have"""
        if self.is_initialized:
            raise Exception("Device already initialized")
        if not self.is_valid:
            raise Exception("Device is not valid anymore")

        dev=Device.Device(self._live_devfile)
        scriptdir=os.path.dirname(Device.__file__)
        builder=SpecBuilder.Builder(self._live_devfile, "%s/specs.json"%scriptdir)
        now=datetime.datetime.utcnow()
        builder.set_parameter_value("password-internal", password)
        builder.set_parameter_value("creation-date", now.strftime("%Y-%m-%d %H:%M:%S"))
        builder.set_parameter_value("creation-date-ts", str(int(now.timestamp())))
        builder.set_parameter_value("dummy-start-sect", 0) # not known yet
        builder.set_parameter_value("dummy-end-sect", 0)
        builder.set_parameter_value("int-start-sect", 0)
        builder.set_parameter_value("int-end-sect", 0)

        specs=builder.get_specifications()
        dev.format(specs)

        layout=Device.analyse_layout(self._live_devfile)
        pdata=layout["partitions"][2]
        builder.set_parameter_value("dummy-start-sect", pdata["sector-start"])
        builder.set_parameter_value("dummy-end-sect", pdata["sector-end"])
        pdata=layout["partitions"][3]
        builder.set_parameter_value("int-start-sect", pdata["sector-start"])
        builder.set_parameter_value("int-end-sect", pdata["sector-end"])

        specs=builder.get_specifications()
        dev.seal_metadata(specs)

        # update object's internal state
        self._compute_extra_partitions()

    def login(self, password):
        if not self.is_valid:
            raise Exception("Device is not valid anymore")
        if self._internal_partfile is not None:
            (ipw, cn)=self._get_internal_password(password)
            obj=enc.Enc("luks", self._internal_partfile, ipw)
            os.makedirs("/internal", mode=0o700, exist_ok=True)
            obj.mount("/internal")

            # alter the user's password and display name
            util.change_user_password("insecauser", password)
            util.change_user_comment(self._live_env.logged, cn)

            # deactivate GDM autologin
            Live.deactivate_gdm_autologin()

            # initialize the components
            self._live_env.extract_privdata()
            self._live_env.extract_live_config_scripts()
            self._live_env.configure_components(0)
            self._live_env.configure_components(1)

    def logout(self):
        if self._internal_partfile is not None:
            encobj=enc.Enc("luks", self._internal_partfile)
            encobj.umount()
            util.change_user_password("insecauser", None)

    def password_change(self, name, current_password, new_password):
        if not self.is_valid:
            raise Exception("Device is not valid anymore")
        (ipw, cn)=self._get_internal_password(current_password)
        self.declare_user(name, new_password, ipw)
        util.change_user_password("insecauser", new_password)

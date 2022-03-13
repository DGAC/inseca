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
import time
import json
import shutil
import subprocess
import tempfile
import tarfile
import syslog
import Utils as util
import Job
import PartitionEncryption

class AdminDeviceInitJob(Job.Job):
    """Creates the "dummy" and "internal" partitions on the device and add the associated meta data,
    and extract the initial configuration"""
    def __init__(self, context, internal_password, conf_file, feedback_component):
        Job.Job.__init__(self)
        self._context=context
        self._conf_file=conf_file
        self._password=internal_password
        self._feedback_component=feedback_component

    def run(self):
        try:
            # init device (partitionning)
            self._context.init_device(self._password)

            # mount internal partition
            obj=PartitionEncryption.Enc("luks", self._context.internal_partfile, self._password)

            # extract the embedded configuration in /internal/configurations
            os.makedirs("/internal", mode=0o700, exist_ok=True)
            obj.mount("/internal")
            tarobj=tarfile.open(self._conf_file, mode="r")
            tarobj.extractall("/internal")

            # umount internal partition
            obj.umount()

            self.result=None
        except Exception as e:
            self.exception=e

class AdminDeviceUnlockJob(Job.Job):
    """Open and mount the /internal partition"""
    def __init__(self, context, user_password, feedback_component):
        Job.Job.__init__(self)
        self._context=context
        self._password=user_password
        self._feedback_component=feedback_component

    def run(self):
        try:
            self._context.login(self._password)
            self.result=None
        except Exception as e:
            self.exception=e

class PasswordChangeJob(Job.Job):
    """Open and mount the /internal partition"""
    def __init__(self, context, current_password, new_password, feedback_component):
        Job.Job.__init__(self)
        self._context=context
        self._current_password=current_password
        self._new_password=new_password
        self._feedback_component=feedback_component

    def run(self):
        try:
            self._context.password_change("default", self._current_password, self._new_password)
            self.result=None
        except Exception as e:
            self.exception=e

class GetPluggedDevicesJob(Job.Job):
    """Get the list of plugged devices"""
    def __init__(self, after_event):
        Job.Job.__init__(self)
        self._after_event=after_event

    def run(self):
        try:
            if self._after_event:
                time.sleep(2)
            plugged_disks=util.get_disks()
            disks_data={}

            for devfile in plugged_disks:
                entry=plugged_disks[devfile]
                size_g=entry["size-G"]
                if entry["useable"]==True:
                    if entry["internal-disk"]:
                        name="!!! DISQUE INTERNE DU PC (%s Go) !!!"%size_g
                    else:
                        name="%s (%s Go)"%(entry["model"], size_g)
                    disks_data[name]=entry
                    disks_data[name]["devfile"]=devfile
            self.result=disks_data
        except Exception as e:
            self.exception=e

class GetPluggedDevicesJob2(Job.Job):
    """Get the list of plugged devices"""
    def __init__(self, after_event):
        Job.Job.__init__(self)
        self._after_event=after_event

    def run(self):
        try:
            if self._after_event:
                time.sleep(2)
            plugged_disks=util.get_disks()

            for devfile in plugged_disks:
                entry=plugged_disks[devfile]
                size_g=entry["size-G"]
                if entry["useable"]==True:
                    if entry["internal-disk"]:
                        name="!!! DISQUE INTERNE DU PC (%s Go) !!!"%size_g
                    else:
                        name="%s (%s Go)"%(entry["model"], size_g)
                    entry["descr"]=name
            self.result=plugged_disks
        except Exception as e:
            self.exception=e


class BorgExtractJob(Job.Job):
    def __init__(self, rconf, arname, where):
        Job.Job.__init__(self)
        self._rconf=rconf
        self._arname=arname
        self._where=where

    def run(self):
        try:
            self._rconf.extract_archive(self._arname, self._where)
        except Exception as e:
            self.exception=e

class BorgUpdateConfJob(Job.Job):
    def __init__(self, rconf, arname, where):
        Job.Job.__init__(self)
        self._rconf=rconf

    def run(self):
        try:
            self._rconf.extract_archive(self._arname, self._where)
        except Exception as e:
            self.exception=e

class BorgExtractLastArchiveJob(Job.Job):
    def __init__(self, rconf):
        Job.Job.__init__(self)
        self._rconf=rconf

    def run(self):
        try:
            self._rconf.cache_last_archive()
        except Exception as e:
            self.exception=e

class ComputeInstallElementsJob(Job.Job):
    def __init__(self, gconf, dconf, iconf, feedback_component):
        Job.Job.__init__(self)
        self._gconf=gconf
        self._dconf=dconf
        self._iconf=iconf
        self._feedback_component=feedback_component

    def run(self):
        try:
            import InstallerComponent
            self._feedback_component.add_event("Analysing configuration...")
            (linuximage, linuxuserdata, infos)=self._gconf.get_install_elements(self._iconf)
            params=InstallerComponent.Params(self._gconf, self._dconf, self._iconf, linuxuserdata)
            self._gconf.release_install_elements(self._iconf)
            self.result=params
        except Exception as e:
            self.exception=e

class InsecaRunJob(Job.Job):
    def __init__(self, args, message, out_as_result=False, feedback_component=None):
        Job.Job.__init__(self)
        self._args=args
        self._message=message
        self._add_event_func=None
        self._out_as_result=out_as_result
        if feedback_component:
            self._add_event_func=feedback_component.add_event    

    def run(self):
        try:
            prog_path=shutil.which("inseca")
            if prog_path is None:
                raise Exception("CODEBUG: could not find the 'inseca' program")

            if self._add_event_func:
                self._add_event_func(self._message)

            args=["pkexec", prog_path]
            if "INSECA_ROOT" in os.environ:
                args+=["--root", os.environ["INSECA_ROOT"]]
            if "INSECA_DEFAULT_REPOS_DIR" in os.environ:
                args+=["--repos-dir", os.environ["INSECA_DEFAULT_REPOS_DIR"]]
            if "INSECA_CACHE_DIR" in os.environ:
                args+=["--cache-dir", os.environ["INSECA_CACHE_DIR"]]
            args+=self._args

            syslog.syslog(syslog.LOG_INFO, "InsecaRunJob: %s"%" ".join(args))
            if self._out_as_result:
                (status, out, err)=util.exec_sync(args)
                syslog.syslog(syslog.LOG_INFO, "InsecaRunJob finished, status: %s"%status)
                if status==0:
                    self.result=out
                elif status==126:
                    syslog.syslog(syslog.LOG_INFO, "InsecaRunJob cancelled")
                    self.cancel()
                else:
                    syslog.syslog(syslog.LOG_INFO, "InsecaRunJob failed: %s"%err)
                    raise Exception(err)
            else:
                process=subprocess.Popen(args, bufsize=0, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                from fcntl import fcntl, F_GETFL, F_SETFL
                from os import O_NONBLOCK

                flags=fcntl(process.stdout, F_GETFL) # get current p.stdout flags
                fcntl(process.stdout, F_SETFL, flags | O_NONBLOCK)
                flags=fcntl(process.stderr, F_GETFL) # get current p.stdout flags
                fcntl(process.stderr, F_SETFL, flags | O_NONBLOCK)
                time.sleep(0.3)
                status=None
                killed=False
                while True:
                    status=process.poll()
                    if status!=None:
                        syslog.syslog(syslog.LOG_INFO, "InsecaRunJob finished, status: %s"%status)
                        if status==126:
                            self.cancel()
                            syslog.syslog(syslog.LOG_INFO, "InsecaRunJob cancelled")
                            killed=True
                        break
                    time.sleep(0.3)

                    if self.cancelled:
                        if not killed:
                            # we cant' send the TERM signal using process.terminate() because the pkexec'd process is run by root
                            # and we may not be running as root.
                            args=["pkexec", "kill", "%s"%process.pid]
                            (status, out, err)=util.exec_sync(args)
                            killed=True
                    elif not killed:
                        try:
                            outl=os.read(process.stdout.fileno(), 1024).splitlines()
                            if len(outl)>0:
                                out=outl[-1] # get only the last line
                                try:
                                    (ts, msg)=out.decode().split(maxsplit=1)
                                    if self._add_event_func:
                                        self._add_event_func(msg)
                                except Exception:
                                    pass
                        except OSError as e:
                            # we may get a lot of Resource temporarily unavailable errors
                            if e.errno!=11:
                                syslog.syslog(syslog.LOG_WARNING, "InsecaRunJob OSError: %s"%str(e))
                                util.print_event("OSError: %s"%str(e))
                        except Exception as e:
                            syslog.syslog(syslog.LOG_INFO, "InsecaRunJob failed: %s"%str(e))
                            util.print_event("Error: %s"%str(e))
                            raise e

                if not killed and status!=None and status!=0:
                    if status==126:
                        self.cancel()
                    else:
                        err=""
                        try:
                            err=os.read(process.stderr.fileno(), 1024)
                        except:
                            pass
                        if err:
                            syslog.syslog(syslog.LOG_INFO, err.decode())
                            raise Exception(err.decode())
                        else:
                            syslog.syslog(syslog.LOG_INFO, "Error")
                            raise Exception("Error")
        except Exception as e:
            self.exception=e


class DeviceFormatJob(InsecaRunJob):
    def __init__(self, fconf, params, target, feedback_component):
        params_file=util.Temp(data=json.dumps(params))
        args=["--verbose", "dev-format", fconf.id, params_file.name, target]
        InsecaRunJob.__init__(self, args, "Creating INSECA device", feedback_component=feedback_component)

class DeviceIdentifyJob(InsecaRunJob):
    def __init__(self, target):
        args=["dev-ident", target]
        InsecaRunJob.__init__(self, args, "Identifying device", out_as_result=True)

    def run(self):
        try:
            InsecaRunJob.run(self)
            self.result=json.loads(self.result)
        except Exception as e:
            self.exception=Exception("Unable to identify device or not an INSECA device")

class DeviceMountJob(InsecaRunJob):
    def __init__(self, target, part_id):
        self._mp=tempfile.mkdtemp()
        args=["dev-mount", target, part_id, self._mp]
        InsecaRunJob.__init__(self, args, "Mounting partition")

    def run(self):
        InsecaRunJob.run(self)
        self.result=self._mp
 
class DeviceUmountJob(InsecaRunJob):
    def __init__(self, target, part_id):
        args=["dev-umount", target, part_id]
        InsecaRunJob.__init__(self, args, "Unmounting partition")


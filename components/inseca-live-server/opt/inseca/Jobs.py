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
import syslog
import tarfile
import tempfile
import time
import json
import Utils as util
import Live
import Job
import Sync
import Installer
import Borg

class InsecaUnlockJob(Job.Job):
    """Used the user provided password to perform all the required verifications and mount the encrypted filesystems.
    Returns the (blob0, int_password, data_password) tuple"""
    def __init__(self, live_env, passwd, with_user_config_files=False):
        if not isinstance(live_env, Live.Environ):
            raise Exception("CODEBUG: invalid @live_env argument")
        Job.Job.__init__(self)
        self._live_env=live_env
        self._passwd=passwd
        self._with_user_config_files=with_user_config_files

    def run(self):
        try:
            syslog.syslog(syslog.LOG_INFO, "Device unlock started")
            bp=Live.BootProcessWKS.get_instance(self._live_env)
            res=bp.unlock(self._passwd) # result will be (blob0, int_password, data_password)
            self.result=res
            syslog.syslog(syslog.LOG_INFO, "Device unlock done")
        except Live.InvalidCredentialException as e:
            self.exception=e
            syslog.syslog(syslog.LOG_ERR, "%s", str(e))
            return
        except Live.DeviceIntegrityException as e:
            self.exception=e
            syslog.syslog(syslog.LOG_ERR, "%s", str(e))
            return
        except Exception as e:
            self.exception=Exception("Internal configuration error: %s"%str(e))
            syslog.syslog(syslog.LOG_ERR, "Internal configuration error: %s"%str(e))
            return

        try:
            syslog.syslog(syslog.LOG_INFO, "Components configuration started (stage 0)")
            self._live_env.configure_components(0)
            syslog.syslog(syslog.LOG_INFO, "Components configuration done (stage 0)")

            if self._with_user_config_files:
                syslog.syslog(syslog.LOG_INFO, "User config files extract started")
                # extract TAR archives from the default profile
                self._live_env.define_UI_environment()
                dirname=self._live_env.default_profile_dir
                if dirname:
                    for base in os.listdir(dirname):
                        if base.endswith(".tar"):
                            syslog.syslog(syslog.LOG_INFO, "Extracting profile file '%s'"%base)
                            filename="%s/%s"%(dirname, base)
                            obj=tarfile.open(filename)
                            obj.extractall(self._live_env.home_dir)

                # change the user's wallpaper to mark the end of the boot process
                if os.path.exists("/internal/resources/default-wallpaper"):
                    self._live_env.user_setting_set("org.gnome.desktop.background", "picture-uri",
                                                    "/internal/resources/default-wallpaper")
                    self._live_env.user_setting_set("org.gnome.desktop.background", "picture-options", "stretched")

                # remove any NO-BACKUP mark
                self._live_env.user_config_clean_nobackup()

                # restore backed up config files
                self._live_env.user_config_restore()

                # make sure all the extracted files belong to the user
                (status, out, err)=util.exec_sync(["chown", "-R", "%s.%s"%(self._live_env.uid, self._live_env.gid), self._live_env.home_dir])
                if status!=0:
                    syslog.syslog(syslog.LOG_WARNING, "Could not give ownership of $HOME to logged user: %s"%err)
                syslog.syslog(syslog.LOG_INFO, "User config files extract done")

            syslog.syslog(syslog.LOG_INFO, "Components configuration started (stage 1)")
            self._live_env.configure_components(1)
            syslog.syslog(syslog.LOG_INFO, "Components configuration done (stage 1)")
        except Exception as e:
            self.exception=Exception("Could not configure some component")
            syslog.syslog(syslog.LOG_ERR, "Could not configure some component: %s"%str(e))
            return

        try:
            syslog.syslog(syslog.LOG_INFO, "Declaring device")
            self._live_env.events.declare_device()
            syslog.syslog(syslog.LOG_INFO, "Adding boot infos")
            self._live_env.events.add_booted_event()
        except Exception as e:
            syslog.syslog(syslog.LOG_ERR, "Error logging events: %s"%str(e))

class LiveLinuxUpdatesGetJob(Job.Job):
    """Download and stage live Linux upddates"""
    def __init__(self, config_file, stage_dir):
        Job.Job.__init__(self)
        self._device_config_file=config_file
        self._stage_dir=stage_dir

    def run(self):
        repo_dir="/internal/build-repo"
        staged_archive_file="%s/archive_name"%self._stage_dir
        staged_archive_name=None
        if os.path.exists(staged_archive_file):
            staged_archive_name=util.load_file_contents(staged_archive_file)
        os.makedirs(self._stage_dir, exist_ok=True, mode=0o700)

        # wait for the device to be unlocked
        while True:
            if os.path.exists("/internal/credentials"):
                break
            time.sleep(60) # wait 1m

        try:
            # get the ts of the current kernel
            kernel_ts=int(os.stat("/run/live/medium/live/vmlinuz").st_mtime)

            # looking for updates
            syslog.syslog(syslog.LOG_INFO, "Looking for updates")
            config=json.load(open(self._device_config_file))
            section=config["build-repo-config"]
            repo_id=section["id"]
            repo_password=section["password"]

            section=config["storage-sources"]
            for target in section:
                syslog.syslog(syslog.LOG_INFO, "Trying to update build repository from the '%s' source"%target)
                sync_conf_file="/internal/credentials/storage/%s"%target
                if os.path.exists(sync_conf_file):
                    try:
                        # check for Internet connection 
                        while not Sync.internet_accessible():
                            syslog.syslog(syslog.LOG_INFO, "No Internet access")
                            raise Exception("No Internet access")

                        # update the build repo's data
                        so=Sync.SyncConfig(target, section[target], sync_conf_file)
                        remote=Sync.SyncLocation(repo_id, so)
                        local=Sync.SyncLocation(repo_dir)

                        self.set_progress(Live.UpdatesStatus.DOWNLOAD)
                        rclone=Sync.RcloneSync(remote, local)
                        rclone.sync(add_event_func=self.set_progress)
                        
                        self.set_progress(Live.UpdatesStatus.CHECK)
                        borg_repo=Borg.Repo(repo_dir, repo_password)
                        borg_repo.check() # ensure repo is useable
                        (archive_ts, archive_name)=borg_repo.get_latest_archive()
                        if archive_ts>kernel_ts:
                            # compare with existing staged archive
                            if archive_name!=staged_archive_name:
                                syslog.syslog(syslog.LOG_INFO, "Extracting live Linux for next boot")
                                self.set_progress(Live.UpdatesStatus.STAGE)
                                # clear the staging dir of any previous file
                                for fname in os.listdir(self._stage_dir):
                                    os.remove("%s/%s"%(self._stage_dir, fname))

                                # extract the archive contents
                                borg_repo.extract_archive(archive_name, self._stage_dir)
                                util.write_data_to_file(archive_name, staged_archive_file)
                                self.result=1
                                return
                    except Exception as e:
                        syslog.syslog(syslog.LOG_ERR, "Error analysing fetched data from target '%s': %s"%(target, str(e)))
                        raise e
                else:
                    # FIXME: future evolution to allow update via a USB stick
                    pass

            # no update available
            self.result=0

        except Exception as e:
            syslog.syslog(syslog.LOG_ERR, "ERROR: %s"%str(e))
            self.exception=e

class LiveLinuxUpdateApplyJob(Job.Job):
    """Apply a live linux upddate"""
    def __init__(self, iso_file, blob0, int_password, data_password):
        Job.Job.__init__(self)
        self._iso_file=iso_file
        self._blob0=blob0
        self._int_password=int_password
        self._data_password=data_password

    def run(self):
        # check if there is actually a staged update
        if not os.path.exists(self._iso_file):
            self.result=0
            return # no update staged

        # remount live partition RW
        live_part=util.get_root_live_partition()
        (status, out, err)=util.exec_sync(["mount", "-o", "rw,remount", "/run/live/medium"])
        if status!=0:
            syslog.syslog(syslog.LOG_ERR, "Could not remount '/run/live/medium' in RW mode: %s"%err)
            self.exception=Exception("Could not remount '/run/live/medium' in RW mode: %s"%err)
            return

        dummy_mounted=False
        try:
            # mount the dummy partition
            target=util.get_device_of_partition(live_part)
            tempdir=tempfile.TemporaryDirectory()
            (status, out, err)=util.exec_sync(["mount", util.get_partition_of_device(target, 2), tempdir.name])
            if status!=0:
                syslog.syslog(syslog.LOG_ERR, "Could not mount the dummy partition '%s': %s"%(util.get_partition_of_device(target, 1), err))
                self.exception=Exception("Could not mount the dummy partition '%s': %s"%(util.get_partition_of_device(target, 1), err))
            dummy_mounted=True

            # actual update
            signing_pubkey="/opt/share/build-sign-key.pub"
            updater=Installer.DeviceUpdater(self._blob0, signing_pubkey, tempdir.name, "/run/live/medium", "/internal",
                                            self._int_password, self._data_password, self._iso_file, target)
            updater.update()
            self.result=1
        except Exception as e:
            self.exception=e
            syslog.syslog(syslog.LOG_ERR, "Error: %s"%str(e))
        finally:
            if dummy_mounted:
                (status, out, err)=util.exec_sync(["umount", tempdir.name])
                if status!=0:
                    syslog.syslog(syslog.LOG_ERR, "Could not umount the dummy partition: %s"%err)
            # remount live partition RO
            (status, out, err)=util.exec_sync(["mount", "-o", "ro,remount", "/run/live/medium"])
            if status!=0:
                syslog.syslog(syslog.LOG_ERR, "Could not remount '/run/live/medium' in RO mode: %s"%err)

class PasswordChangeJob(Job.Job):
    """Change the user's password"""
    def __init__(self, env, current_password, new_password):
        Job.Job.__init__(self)
        self._env=env
        self._current_password=current_password
        self._new_password=new_password

    def run(self):
        live_part=util.get_root_live_partition()
        dummy_mounted=False
        try:
            target=util.get_device_of_partition(live_part)
            tempdir=tempfile.TemporaryDirectory()
            (status, out, err)=util.exec_sync(["mount", util.get_partition_of_device(target, 2), tempdir.name]) # FIXME: 2 is dummy partition, use an index by name
            if status!=0:
                syslog.syslog(syslog.LOG_ERR, "Could not mount the dummy partition '%s': %s"%(util.get_partition_of_device(target, 1), err))
                self.exception=Exception("Could not mount the dummy partition '%s': %s"%(util.get_partition_of_device(target, 1), err))
            dummy_mounted=True

            Live.change_user_password(tempdir.name, self._current_password, self._new_password)
            syslog.syslog(syslog.LOG_INFO, "Password changed")
        except Exception as e:
            self.exception=e
            syslog.syslog(syslog.LOG_ERR, "Error: %s"%str(e))
        finally:
            if dummy_mounted:
                (status, out, err)=util.exec_sync(["umount", tempdir.name])
                if status!=0:
                    syslog.syslog(syslog.LOG_ERR, "Could not umount the dummy partition: %s"%err)

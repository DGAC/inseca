# This file is part of INSECA.
#
#    Copyright (C) 2020-2024 INSECA authors
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
import datetime
import time
import shutil
import uuid
import syslog
import Utils as util
import CryptoGen as cgen

# Gettext stuff
import gettext
lib_dir=os.path.dirname(__file__)
gettext.bindtextdomain("inseca-lib", lib_dir+"/locales")
gettext.textdomain("inseca-lib")
_ = gettext.gettext

class BorgRepoIncomplete(Exception):
    pass
class BorgMemoryError(Exception):
    pass
class BorgRepoLocked(Exception):
    pass

class Repo:
    def __init__(self, repo_dir, password, config_dir=None, cache_dir=None):
        self._repo_dir=repo_dir
        self._password=password
        self._config_dir=config_dir
        self._cache_dir=cache_dir
        self._tmp_dir=None
        self._mountpoints={} # key=archive name, value=[tmp directory name (as a string) where it is mounted, Popen object]
        self._borg_prog=shutil.which("borg") # so Python does not have to search the borg exe while shuting down (in the __del__ method)
        if self._borg_prog is None:
            raise Exception("Could not find the 'borg' program, make sure Borg Backup is installed")

        # determine Borg version
        (status, out, err)=util.exec_sync([self._borg_prog, "-V"])
        if status!=0:
            raise Exception(f"Could not determine borg's version: {err}")
        (_, version_s)=out.split()
        (maj, min, *_)=version_s.split(".")
        version=int(maj)*10+int(min)

        # determine available features
        self._has_compact=version>=12

    def __del__(self):
        self.umount_all()

    @property
    def config_dir(self):
        if self._config_dir is None:
            if self._tmp_dir is None:
                self._tmp_dir=tempfile.TemporaryDirectory()
            self._config_dir=self._tmp_dir.name+"/config"
            os.makedirs(self._config_dir)
        return self._config_dir

    @property
    def cache_dir(self):
        if self._cache_dir is None:
            if self._tmp_dir is None:
                self._tmp_dir=tempfile.TemporaryDirectory()
            self._cache_dir=self._tmp_dir.name+"/cache"
            os.makedirs(self._cache_dir)
        return self._cache_dir

    def get_exec_env(self):
        cenv=os.environ.copy()
        cenv["BORG_PASSPHRASE"]=self._password
        cenv["BORG_REPO"]=self._repo_dir
        cenv["BORG_RELOCATED_REPO_ACCESS_IS_OK"]="yes"

        # Borg stores information about all the repositories in the BORG_CONFIG_DIR environment variable
        # built by default as $XDG_CONFIG_HOME/.config.
        # Because we may need to copy repositories on the same system (and the same user account name) while
        # developping, and because it's better to separate INSECA's Borg usage from the non INSECA Borg usage,
        # we ask Borg to keep those files in the $INSECA_ROOT/.borg directory if the configuration is a master one,
        # otherwise we create random directories on the fly for that purpose
        #
        # Cf. https://borgbackup.readthedocs.io/en/stable/usage/general.html#env-vars
        #     https://borgbackup.readthedocs.io/en/stable/internals/data-structures.html

        cenv["BORG_CONFIG_DIR"]=self.config_dir
        cenv["BORG_CACHE_DIR"]=self.cache_dir
        return cenv

    def _borg_err_to_exception(self, context, err):
        if "Data integrity error" in err:
            raise BorgRepoIncomplete("%s: %s"%(context, _("Incomplete synchronisation, retry later")))
        elif "MemoryError" in err:
            raise BorgMemoryError("%s: %s"%(context, _("Not enough memory(?)")))
        elif "Failed to create/acquire the lock" in err:
            raise BorgRepoLocked(f"{context}: {_('Unable to acquire lock on repository, may already be used')}")

        raise Exception("%s: %s"%(context, err))

    def _borg_run(self, args:list[str], context:str, stdin_data:str=None, cwd:str=None, env_variables:dict[str, str]=None):
        """Execute Borg, handle errors and return the execution's output"""
        cenv=self.get_exec_env()
        if env_variables is not None:
            cenv.update(env_variables)
        (status, out, err)=util.exec_sync([self._borg_prog]+args, exec_env=cenv,
                                          stdin_data=stdin_data, cwd=cwd)
        if status!=0:
            self._borg_err_to_exception(context, err)
        return out

    def init(self):
        """Initialize a Borg repository.
        If no password was specified when the object was created, one is randomly generated.
        Returns: the repo.'s password"""
        # create repo
        os.makedirs(self._repo_dir)
        if not self._password:
            self._password=cgen.generate_password()
        self._borg_run(["init", "--encryption=repokey", self._repo_dir],
                       _("Could not initialize repository"))

        # change segment size to 32Mb
        newconf=[]
        cfile="%s/config"%self._repo_dir
        for line in util.load_file_contents(cfile).splitlines():
            if line.startswith("max_segment_size"):
                line="max_segment_size = 33554432"
            newconf+=[line]
        util.write_data_to_file("\n".join(newconf), cfile)

        return self._password

    def change_password(self, new_password:str):
        """Change the password of the repository"""
        util.print_event(_("Changing repository's password"))
        self._borg_run(["key", "change-passphrase"],
                        _("Could not change password"), env_variables={"BORG_NEW_PASSPHRASE": new_password})

    def generate_new_id(self):
        """Generate a new ID and define it as the new ID of the repository"""
        id=cgen.generate_password(64, "abcdef0123456789")
        configfile=f"{self._repo_dir}/config"
        nlines=[]
        with open(configfile, "r") as fd:
            replaced=False
            for line in fd.read().splitlines():
                if line.startswith("id ="):
                    nlines.append(f"id = {id}")
                    replaced=True
                else:
                    nlines.append(line)
            if not replaced:
                raise Exception(f"Could not identify the repository's ID in '{configfile}', Borg's file format changed?")
        util.write_data_to_file("\n".join(nlines), configfile)

    def create_archive(self, datadir, compress=False):
        """Create a new archive containing the data in @datadir.
        Returns: the new archive's name"""
        # create archive
        arname=str(uuid.uuid4())
        util.print_event(_("Creating archive '%s'")%arname)
        self._borg_run(["create", "-C", "lzma,9" if compress else "none", "::%s"%arname, "."],
                        _("Could not create archive"), stdin_data="Y", cwd=datadir)

        # change ownership of the files if program was executed using sudo
        if "SUDO_UID" in os.environ and "SUDO_GID" in os.environ:
            uid=int(os.environ["SUDO_UID"])
            gid=int(os.environ["SUDO_GID"])
            util.chown_r(self._repo_dir, uid, gid)
            util.chown_r(self.config_dir, uid, gid)
            util.chown_r(self.cache_dir, uid, gid)

        return arname

    def get_all_archives(self):
        """Get a list of all the archives as a dictionary indexed by the timestamp the archive was created
        and where values are the associated archives' name"""
        # the "Y" is necessary so that repos. can be relocated
        out=self._borg_run(["list"], _("Failed to get archives list"), stdin_data="Y")
        res={}
        
        for line in out.splitlines():
            # e.g. b7760356-7e2c-11ea-be7b-5703d69f8bcb Tue, 2020-04-14 10:48:34
            parts=line.split()
            if len(parts)<4:
                raise Exception("CODEBUG: could not parse Borg's output line '%s'"%line)
            dt=datetime.datetime.strptime("%s %s"%(parts[2], parts[3]), "%Y-%m-%d %H:%M:%S")
            ts=int(dt.timestamp())
            res[ts]=parts[0]
        return res

    def check(self):
        """Checks if the repository is Ok (using the "borg check" command).
        Returns:
        - None if there is no error
        - a list of file which have problems, and which potentially require a re-sync from the
          source (with rclone, one has to change the date first)
        - an exception if there is an unhandled error
        """
        syslog.syslog(syslog.LOG_INFO, "Checking Borg repository's health")
        (status, out, err)=util.exec_sync([self._borg_prog, "check"], exec_env=self.get_exec_env())
        if status==0:
            if os.path.exists("%s/lock.roster"%self._repo_dir):
                raise Exception("Repository is already being used, try again later")
            return None
        else:
            # identify file which have an integrity problem, err will be like:
            # "Data integrity error: Segment entry checksum mismatch [segment 739, offset 1224]"
            # the file in error will be "739" in this case
            errfiles=[]
            for line in err.splitlines():
                if "[segment " in line:
                    parts=line.split("[segment ")
                    if len(parts)==2:
                        parts=parts[1].split(",")
                        segment=parts[0]
                        for (root, dirs, files) in os.walk("%s/data"%self._repo_dir):
                            if segment in files:
                                errfiles+=["%s/%s"%(root, segment)]
            if len(errfiles)>0:
                syslog.syslog(syslog.LOG_WARNING, "Repository has some file errors: %s"%errfiles)
                return errfiles
            syslog.syslog(syslog.LOG_ERR, "Unhandled repository check error: %s"%err)
            raise Exception("Unhandled repository check error")

    def get_latest_archive(self):
        """Get the most recent archive in the specified repository
        Returns a (ts, archive name) tuple"""
        arlist=self.get_all_archives()
        if len(arlist)>0:
            tslist=list(arlist.keys())
            tslist.sort(reverse=True)
            ts=tslist[0]
            return (ts, arlist[ts])
        else:
            return (0, None)

    def archive_exists(self, archive_name):
        """Tells if a specific archive is in the repository"""
        if archive_name in self._mountpoints:
            return True
        out=self._borg_run(["list"], _("Could not list archives"))
        for line in out.splitlines():
            if line.startswith("%s "%archive_name):
                return True
        return False

    def extract_archive(self, archive_name, destdir, files=None):
        """Extract the whole contents of the specified archive in @destdir (which must already exist)"""
        if not archive_name:
            raise Exception(_("Archive to extract is not specified"))
        if not os.path.exists(destdir):
            raise Exception(_("Destination path '%s' does not exist")%destdir)
        if not os.path.isdir(destdir):
            raise Exception(_("Destination path '%s' is not a directory")%destdir)
        cwd=os.getcwd()
        try:
            os.chdir(destdir)
            #util.print_event("Extracting archive %s in %s"%(archive_name, destdir))
            if files is None:
                self._borg_run(["extract", "--sparse", "::%s"%archive_name], _("Could not extract archive"))
            elif isinstance (files, list):
                self._borg_run(["extract", "--sparse", "::%s"%archive_name]+files, _("Could not extract files %s from archive")%files)
            else:
                raise Exception(f"Invalid @files argument, expected a list, got a {type(files)}")
        finally:
            os.chdir(cwd)

    def list_archive_contents(self, arname):
        """List all the files in the archive
        Returns: the raw textual output"""
        return self._borg_run(["list", "::%s"%arname], _("Could not list files in archive"))

    def delete_archive(self, arname):
        """Delete the specified archive from the reposiroty"""
        self._borg_run(["delete", "::%s"%arname], _("Could not delete archive"), stdin_data="Y")

    def vacuum(self):
        """Remove unused data from the repository"""
        if self._has_compact:
            self._borg_run(["compact"], _("Could not compact archive"))

    def mount(self, archive_name):
        """Mounts the specified archive somewhere and returns the mount point"""
        if not isinstance(archive_name, str):
            raise Exception("CODEBUG: @archive_name is not a string")
        if archive_name in self._mountpoints:
            return self._mountpoints[archive_name][0]
        mp=tempfile.mkdtemp()

        # the -f argument requests that the process don't daemonize itself
        proc=util.exec_async([self._borg_prog, "mount", "-f", "::%s"%archive_name, mp], exec_env=self.get_exec_env())
        time.sleep(0.5)
        ret=proc.poll()
        if ret is not None:
            (out, err)=proc.communicate()
            self._borg_err_to_exception(_("Could not mount archive '%s'"%archive_name), err)

        self._mountpoints[archive_name]=[mp, proc]
        util.print_event(_(f"Mounted archive '{archive_name}' on '{mp}'"))

        # ensure that the archive is actually useable before returning
        counter=0
        while counter<6:
            counter+=1
            if len(os.listdir(mp))>0:
                break
            time.sleep(0.5)
        return mp

    def umount(self, archive_name):
        """Unmounts the specified archive"""
        if archive_name not in self._mountpoints:
            return
        (mp, proc)=self._mountpoints[archive_name]
        # kill the FUSE process
        proc.terminate()
        counter=0
        while True:
            ret=proc.poll()
            if ret is None:
                time.sleep(1)
                counter+=1
                if counter>10:
                    raise Exception(_("Could not umount archive '%s': timed out")%archive_name)
            else:
                break
        # force umount
        self._borg_run(["umount", mp], _("Could not umount archive '%s'"%archive_name))

        del self._mountpoints[archive_name]
        try:
            os.rmdir(mp)
        except Exception:
            pass
        try:
            util.print_event(_(f"Unmounted archive '{archive_name}' (was mounted on '{mp}')")) # may fail if Python is shuting down
        except:
            pass

    def umount_all(self):
        """Unmounts all the mounted archives"""
        for archive_name in list(self._mountpoints.keys()):
            self.umount(archive_name)

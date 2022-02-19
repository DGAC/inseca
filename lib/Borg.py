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
import datetime
import time
import shutil
import uuid
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

class Repo:
    def __init__(self, repo_dir, password, config_dir=None, cache_dir=None):
        self._repo_dir=repo_dir
        self._password=password
        self._config_dir=config_dir
        self._cache_dir=cache_dir
        self._tmp_dir=None
        self._mountpoints={} # key=archive name, value=[tmp directory name (as a string) where it is mounted, Popen object]
        self._borg_prog=shutil.which("borg") # so Python does not have to search the borg exe while shuting down (in the __del__ method)

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

    def init(self):
        """Initialize a Borg repository.
        If no password was specified when the object was created, one is randomly generated.
        Returns: the repo.'s password"""
        # create repo
        os.makedirs(self._repo_dir)
        if not self._password:
            self._password=cgen.generate_password()
        (status, out, err)=util.exec_sync([self._borg_prog, "init", "--encryption=repokey",
                                          self._repo_dir], exec_env=self.get_exec_env())
        if status!=0:
            raise Exception(_("Could not initialize repository: %s")%err)

        # change segment size to 32Mb
        newconf=[]
        cfile="%s/config"%self._repo_dir
        for line in util.load_file_contents(cfile).splitlines():
            if line.startswith("max_segment_size"):
                line="max_segment_size = 33554432"
            newconf+=[line]
        util.write_data_to_file("\n".join(newconf), cfile)

        return self._password

    def create_archive(self, datadir, compress=False):
        """Create a new archive containing the data in @datadir.
        Returns: the new archive's name"""
        # create archive
        arname=str(uuid.uuid4())
        util.print_event(("Creating archive '%s'")%arname)
        (status, out, err)=util.exec_sync([self._borg_prog, "create", "-C", "lzma,9" if compress else "none", "::%s"%arname, "."],
                                        stdin_data="Y", cwd=datadir, exec_env=self.get_exec_env())
        if status!=0:
            raise Exception(_("Could not create archive: %s")%err)

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
        (status, out, err)=util.exec_sync([self._borg_prog, "list"], stdin_data="Y", exec_env=self.get_exec_env())
        if status!=0:
            if "Data integrity error" in err:
                raise BorgRepoIncomplete(_("Incomplete synchronisation, retry later"))
            else:
                raise Exception(_("Failed to get archives list: %s")%err)
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

    def is_locked(self):
        """Tell if the repository is locked by Borg (i.e. another process is using it or there is a stale lock)"""
        if os.path.exists("%s/lock.roster"%self._repo_dir):
            return True
        return False

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
        (status, out, err)=util.exec_sync([self._borg_prog, "list"], exec_env=self.get_exec_env())
        if status!=0:
            if "Data integrity error" in err:
                raise BorgRepoIncomplete(_("Incomplete synchronisation, retry later"))
            else:
                raise Exception(_("Could not list archives: %s")%err)
        for line in out.splitlines():
            if line.startswith("%s "%archive_name):
                return True
        return False

    def extract_archive(self, archive_name, destdir):
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
            (status, out, err)=util.exec_sync([self._borg_prog, "extract", "::%s"%archive_name, "--sparse"],
                                            exec_env=self.get_exec_env())
            if status!=0:
                if "Data integrity error" in err:
                    raise BorgRepoIncomplete(_("Incomplete synchronisation, retry later"))
                else:
                    raise Exception(_("Could not extract archive: %s")%err)
        finally:
            os.chdir(cwd)

    def list_archive_contents(self, arname):
        """List all the files in the archive
        Returns: the raw textual output"""
        (status, out, err)=util.exec_sync([self._borg_prog, "list", "::%s"%arname], exec_env=self.get_exec_env())
        if status!=0:
            if "Data integrity error" in err:
                raise BorgRepoIncomplete("Incomplete synchronisation, retry later")
            else:
                raise Exception("Could not list files in archive: %s"%err)
        return out

    def delete_archive(self, arname):
        """Delete the specified archive from the reposiroty"""
        (status, out, err)=util.exec_sync([self._borg_prog, "delete", "::%s"%arname], stdin_data="Y", exec_env=self.get_exec_env())
        if status!=0:
            if "Data integrity error" in err:
                raise BorgRepoIncomplete("Incomplete synchronisation, retry later")
            else:
                raise Exception("Could not delete archive: %s"%err)

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
            if "Data integrity error" in err:
                raise BorgRepoIncomplete(_("Incomplete synchronisation, retry later"))
            else:
                raise Exception(_(f"Could not mount archive '{archive_name}': {err}"))

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
        (status, out, err)=util.exec_sync([self._borg_prog, "umount", mp]) # no need to define the BORG_* environment variables
        if status!=0:
            if "Data integrity error" in err:
                raise BorgRepoIncomplete(_("Incomplete synchronisation, retry later"))
            else:
                raise Exception(_("Could not umount archive '{archive_name}': {err}"))

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

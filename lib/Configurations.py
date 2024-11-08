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
#    along with INSECA.  If not, see <https://www.gnu.org/licenses/>

from __future__ import annotations
import os
import json
import enum
import datetime
import calendar
import shutil
import sys
import uuid
import tempfile
import tarfile
from dataclasses import dataclass
import CryptoGen as cgen
import CryptoX509 as x509
from abc import ABC, abstractmethod, abstractproperty
import Utils as util
import Filesystem
import Sync
import Borg as borg
import ValueHolder
import LiveBuilder

# Gettext stuff
import gettext
lib_dir=os.path.dirname(__file__)
gettext.bindtextdomain("inseca", lib_dir+"/locales")
gettext.textdomain("inseca")
_ = gettext.gettext

# file names
file_iso="live-linux.iso"
file_userdata="live-linux.userdata-specs"
file_infos="infos.json"

def _validate_attributes(data, specs):
    """Check that @data respects the specifications
    @specs is a list of [attr name, can be None, is required]
    """
    if not isinstance(data, dict):
        raise Exception("CODEBUG: expected a dictionary, got: %s"%data)
    if len(data)>len(specs):
        raise Exception("CODEBUG: extra attributes: spec=%s / data=%s"%(specs, data))
    for attr in specs:
        spec=specs[attr]
        if attr not in data:
            if spec[2]:
                raise Exception(_("Missing attribute '%s'")%attr)
        else:
            value=data[attr]
            if value is None and not spec[1]:
                raise Exception(_("Invalid attribute '%s': should not be null")%attr)
            if value is not None and not isinstance(value, spec[0]):
                raise Exception(_("Invalid attribute '%s': wrong data type")%attr)

def _validate_parameter_definition(data): # FIXME: put someplace where it can also be used by the SpecBuilder
    if not isinstance(data, dict):
        raise Exception(_("Expected a dictionary, got: %s")%data)
    attrs=("descr", "type", "default", "attest")
    for attr in data:
        if attr not in attrs:
            raise Exception(_("Invalid attribute '%s'")%attr)
    for attr in ("descr", "type", "attest"):
        if attr not in data:
            raise Exception(_("Missing attribute '%s'")%attr)

    if not isinstance(data["descr"], str):
        raise Exception(_("Invalid 'descr' attribute: wrong type"))
    if data["type"] not in ("str", "filesystem", "password", "timestamp", "int", "file", "size-mb", "encryptiontype"):
        raise Exception(_("Invalid 'type' attribute '%s'")%data["type"])
    if not isinstance(data["attest"], bool):
        raise Exception(_("Invalid 'attest' attribute: wrong type"))

def validate_parameter_value(spec, value, config_dir):
    rtype=spec["type"]
    if rtype=="str":
        if not isinstance(value, str):
            raise Exception(_("Wrong value '%s' for a string parameter")%value)
    elif rtype=="file":
        path=value
        if path is not None:
            if not os.path.isabs(value):
                path="%s/%s"%(config_dir, value)
            if not os.path.exists(path):
                raise Exception(_("Missing file '%s' identified in parameter")%path)
    elif rtype in ("size-mb", "int"):
        if not isinstance(value, int) or value<0:
            raise Exception(_("Wrong value '%s' for parameter")%value)
    elif rtype=="filesystem":
        try:
            Filesystem.fstype_from_string(value)
        except Exception:
            raise Exception(_("Wrong value '%s' for a filesystem parameter")%value)

def get_last_file_modification_ts(basename, exclude=None):
    rts=int(os.stat(basename).st_mtime)
    if os.path.isdir(basename):
        for fname in os.listdir(basename):
            if fname==".git":
                continue
            path="%s/%s"%(basename, fname)
            if path==exclude:
                continue
            if os.path.isdir(path):
                ts=get_last_file_modification_ts(path)
            else:
                try:
                    ts=int(os.stat(path).st_mtime)
                except Exception:
                    # file can't be read, or a symlink to some unavailable place
                    ts=0
            if rts<ts:
                rts=ts
    return rts

def identify_free_filename(base_dir, prefix, ext=None):
    """Identify a 'free' (inexistant) directory/file name like $base_dir/$prefix.<index>.
    Returns the full path"""
    index=0
    while True:
        path="%s/%s.%s"%(base_dir, prefix, index)
        if ext:
            path=path+ext
        if not os.path.exists(path):
            return path
        index+=1

#
# Build configurations
#
class BuildType(str, enum.Enum):
    """Different types of build configurations"""
    SIMPLE="simple"
    ADMIN="admin"
    WKS="workstation"
    SERVER="server"

class GlobalConfiguration:
    """Represents a global INSECA configuration.
    Creating a new object allows one to take into account an updated configuration"""
    def __init__(self, path=None):
        self._ready=False
        if path is None:
            if not "INSECA_ROOT" in os.environ:
                raise Exception(_("INSECA_ROOT environment variable is not defined"))
            path=os.environ["INSECA_ROOT"]
            if not os.path.isdir(path):
                raise Exception(_("Directory '%s' pointed by INSECA_ROOT environment variable does not exist")%path)
        self._path=os.path.realpath(path)
        self._script_dir=os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

        # Check that the top level directories are present
        for fname in ("install-configurations", "format-configurations", "repo-configurations", "domain-configurations"):
            fpath="%s/%s"%(self._path, fname)
            if not os.path.exists(fpath):
                raise Exception(_(f"Top directory '{fpath}' is missing"))
            if not os.path.isdir(fpath):
                raise Exception(_(f"'{fpath}' should be a directory"))

        self._load_global_settings()
        self._all_conf_ids=[] # to avoid ANY config ID duplicate
        self._load_build_configs()
        self._load_install_configs()
        self._load_format_configs()
        self._load_domain_configs()
        self._load_repo_configs()

        # identify the build ID associated to install configs
        # NB: on admin environments, there is no build config => this step will actually not provide
        #     the build_id
        for iuid in self._install_configs:
            iconf=self._install_configs[iuid]
            for uid in self._build_configs:
                bconf=self._build_configs[uid]
                if bconf.repo_id==iconf._build_repo_id:
                    iconf.build_id=uid
                    break

        self._archives_cache_dir=None # must be defined before use, no default value
        if not self._is_master:
            if "INSECA_CACHE_DIR" in os.environ:
                self.archives_cache_dir=os.environ["INSECA_CACHE_DIR"]

        self._ready=True

    @property
    def ready(self):
        """Tells if the object has finished loading the whole configuration"""
        return self._ready

    @property
    def script_dir(self):
        return self._script_dir

    @property
    def path(self):
        """Points to the path of the global configuration (i.e. $INSECA_ROOT)"""
        return self._path

    def get_relative_path(self, path):
        """Get the part of @path relative to the directory holding the INSECA configuration,
        Returns @path itself if it's not a subdir of that directory
        """
        if path.startswith(self._path):
            return path[len(self._path)+1:]
        return path

    @property
    def archives_cache_dir(self):
        """Get the directory where all the extracted archives are stored.
        The sub directory structure is:
        /<repo id>/<archive id>/...
        and
        /<repo id>/last-archive which is a symlink pointing to the last archive ID directory
        """
        if not self._archives_cache_dir:
            raise Exception(_("The archives_cache_dir property has not yet been defined"))
        return self._archives_cache_dir

    @archives_cache_dir.setter
    def archives_cache_dir(self, archive_dir):
        archive_dir=os.path.realpath(archive_dir)
        os.makedirs(archive_dir, mode=0o700, exist_ok=True)
        if os.stat(archive_dir).st_mode&0o777!=0o700: # ensure the dir's mode is 700
            os.chmod(archive_dir, 0o700)
        self._archives_cache_dir=archive_dir

    @property
    def build_configs(self):
        if not self.ready:
            raise Exception("Configuration has not yet been fully loaded")
        return list(self._build_configs.keys())

    @property
    def install_configs(self):
        if not self.ready:
            raise Exception("Configuration has not yet been fully loaded")
        return list(self._install_configs.keys())

    @property
    def format_configs(self):
        if not self.ready:
            raise Exception("Configuration has not yet been fully loaded")
        return list(self._format_configs.keys())

    @property
    def domain_configs(self):
        if not self.ready:
            raise Exception("Configuration has not yet been fully loaded")
        return list(self._domain_configs.keys())

    @property
    def repo_configs(self):
        if not self.ready:
            raise Exception("Configuration has not yet been fully loaded")
        return list(self._repo_configs.keys())

    @property
    def proxy_pac_file(self):
        if not self.ready:
            raise Exception("Configuration has not yet been fully loaded")
        return self._proxy_pac_file

    @property
    def is_master(self):
        if not self.ready:
            raise Exception("Configuration has not yet been fully loaded")
        return self._is_master

    def _load_global_settings(self):
        fname="%s/inseca.json"%self._path
        if not os.path.isfile(fname):
            raise Exception(_("Global configuration file '%s' is missing")%fname)
        data=json.load(open(fname, "r"))

        # global validation
        specs={
            "deploy": [dict, False, True],
            "is-master": [bool, False, False]
        }
        _validate_attributes(data, specs)
        self._sync_configs={}

        # deploy configuration
        for entry in data["deploy"]:
            sdata=data["deploy"][entry]
            if "reader-conf" in sdata:
                fname=None
                if sdata["reader-conf"] is not None:
                    fname="%s/storage-credentials/%s"%(self._path, sdata["reader-conf"])
                    if not os.path.isfile(fname):
                        raise Exception(_(f"'reader-conf' file '{fname}' not found for entry '{entry}'"))
                self._sync_configs["R"+entry]=Sync.SyncConfig(entry, sdata["root"], fname)
            if "writer-conf" in sdata:
                fname=None
                if sdata["writer-conf"] is not None:
                    fname="%s/storage-credentials/%s"%(self._path, sdata["writer-conf"])
                    if not os.path.isfile(fname):
                        raise Exception(_(f"'writer-conf' file '{fname}' not found for entry '{entry}'"))
                self._sync_configs["W"+entry]=Sync.SyncConfig(entry, sdata["root"], fname)

        # proxy.pac
        self._proxy_pac_file=None
        dpac="%s/proxy.pac"%self._path
        if os.path.exists(dpac):
            self._proxy_pac_file=dpac

        if "INSECA_PROXY_PAC" in os.environ:
            path=os.environ["INSECA_PROXY_PAC"]
            if path:
                if not os.path.isabs(path):
                    path="%s/%s"%(self._path, path)
                self._proxy_pac_file=path

        if self._proxy_pac_file is not None:
            if not os.path.isfile(self._proxy_pac_file):
                #raise Exception("Proxy PAC file '%s' does not exist"%self._proxy_pac_file)
                Sync.proxy_pac_file=None
            else:
                Sync.proxy_pac_file=self._proxy_pac_file

        # master config
        self._is_master=True
        if "is-master" in data:
            self._is_master=data["is-master"]

    def get_target_sync_object(self, target, way_out):
        """Get the specified sync. target (as named in the global inseca.json file)
        @way_out specified the required target type: True to "export" data, and False to "import" it.
        """
        if not self.ready:
            raise Exception("Configuration has not yet been fully loaded")
        if way_out:
            name="W"+target
        else:
            name="R"+target
        if name in self._sync_configs:
            return self._sync_configs[name]
        raise Exception(_("Unknown synchronization target '%s'")%target)

    def get_all_sync_objects(self, way_out):
        """Get all the sync. targets for the specified type (see get_target_sync_object())"""
        if not self.ready:
            raise Exception("Configuration has not yet been fully loaded")
        res=[]
        for key in self._sync_configs:
            if key[0]=="R" and not way_out or key[0]=="W" and way_out:
                res+=[self._sync_configs[key]]
        return res

    def _sort_configs(self, configs):
        data={} # key: description, value=[] of config objects having that description
        for uid in configs:
            conf=configs[uid]
            if conf.descr not in data:
                data[conf.descr]=[]
            data[conf.descr]+=[conf]
        res={}
        keys=list(data.keys())
        keys.sort()
        for descr in keys:
            for conf in data[descr]:
                res[conf.id]=conf
        return res

    def _load_build_configs(self):
        """Load all live configurations as a dict of live Linux configurations indexed by config ID"""
        tpath="%s/build-configurations"%self._path
        if not os.path.exists(tpath):
            # no build configuration, which is normal in the admin environment
            self._build_configs={}
            return

        res={}
        for cdir in os.listdir(tpath):
            cpath="%s/%s"%(tpath, cdir)
            if cdir[0]=="_" or not os.path.isdir(cpath):
                continue # ignore this
            cfile="%s/build-configuration.json"%cpath
            if not os.path.exists(cfile):
                util.print_event("WARNING: missing build configuration file '%s', configuration ignored"%self.get_relative_path(cfile))
            else:
                conf=BuildConfig(self, cfile)
                if conf.id in self._all_conf_ids and conf.config_file!=cfile:
                    raise Exception(_(f"Build configuration '{conf.id}' already exists (in '{conf.config_file}', loaded from '{cfile}')"))
                res[conf.id]=conf
                self._all_conf_ids+=[conf.id]
        self._build_configs=self._sort_configs(res)

    def _load_install_configs(self):
        """Load all install configurations as a dict of the install configurations indexed by config ID"""
        res={}
        tpath="%s/install-configurations"%self._path
        for cdir in os.listdir(tpath):
            cpath="%s/%s"%(tpath, cdir)
            if cdir[0]=="_" or not os.path.isdir(cpath):
                continue # ignore this
            cfile="%s/install-configuration.json"%cpath
            if not os.path.exists(cfile):
                util.print_event("WARNING: missing install configuration file '%s' configuration ignored"%self.get_relative_path(cfile))
            else:
                conf=InstallConfig(self, cfile)
                if conf.id in self._all_conf_ids and conf.config_file!=cfile:
                    raise Exception(_(f"Install configuration '{conf.id}' already exists (in '{conf.config_file}', loaded from '{cfile}')"))
                res[conf.id]=conf
                self._all_conf_ids+=[conf.id]
        self._install_configs=self._sort_configs(res)

    def _load_format_configs(self):
        """Load all format configurations as a dict of the format configurations indexed by config ID"""
        res={}
        tpath="%s/format-configurations"%self._path
        for cdir in os.listdir(tpath):
            cpath="%s/%s"%(tpath, cdir)
            if cdir[0]=="_" or not os.path.isdir(cpath):
                continue # ignore this
            cfile="%s/format-configuration.json"%cpath
            if not os.path.exists(cfile):
                raise Exception(_("Missing format configuration file '%s'")%self.get_relative_path(cfile))
            conf=FormatConfig(self, cfile)
            if conf.id in self._all_conf_ids and conf.config_file!=cfile:
                raise Exception(_(f"Format configuration '{conf.id}' already exists (in '{conf.config_file}', loaded from '{cfile}')"))
            res[conf.id]=conf
            self._all_conf_ids+=[conf.id]
        self._format_configs=self._sort_configs(res)

    def _load_domain_configs(self):
        """Load all domain configurations ad a dict of the install configurations indexed by config ID"""
        res={}
        tpath="%s/domain-configurations"%self._path
        for cfile in os.listdir(tpath):
            cpath="%s/%s"%(tpath, cfile)
            if cfile[0]=="_" or not os.path.isfile(cpath):
                continue # ignore this
            conf=DomainConfig(self, cpath)
            if conf.id in self._all_conf_ids and conf.config_file!=cfile:
                raise Exception(_(f"Domain configuration '{conf.id}' already exists (in '{conf.config_file}', loaded from '{cfile}')"))
            res[conf.id]=conf
            self._all_conf_ids+=[conf.id]
        self._domain_configs=self._sort_configs(res)

    def _load_repo_configs(self, path=None):
        """Load all domain configurations as a dict of the install configurations indexed by config ID"""
        if path is None:
            self._repo_configs={}
            path="%s/repo-configurations"%self._path
            self._load_repo_configs(path)
            self._repo_configs=self._sort_configs(self._repo_configs)
            return

        for cfile in os.listdir(path):
            cpath="%s/%s"%(path, cfile)
            if cfile[0]=="_":
                continue # ignore this
            if os.path.isdir(cpath):
                self._load_repo_configs(cpath)
            else:
                conf=RepoConfig(self, cpath)
                if conf.id in self._all_conf_ids:
                    if conf.config_file!=cpath:
                        raise Exception(_(f"Duplicate repository configuration '{conf.id}' already exists (in '{conf.config_file}', loaded from '{cpath}')"))
                else:
                    if not os.path.isabs(conf.path):
                        if "INSECA_DEFAULT_REPOS_DIR" in os.environ:
                            conf.path="%s/%s"%(os.environ["INSECA_DEFAULT_REPOS_DIR"], conf.path)
                        else:
                            conf.path="%s/repos/%s"%(self.path, conf.path)
                    self._repo_configs[conf.id]=conf
                    self._all_conf_ids+=[conf.id]

    def get_any_conf(self, conf:str, exception_if_not_found=True) -> ConfigInterface:
        """Get a ConfigInterface object from its ID, or actual config file path,
        or its description (or part of it)"""
        if not self.ready:
            raise Exception("Configuration has not yet been fully loaded")
        res=self.get_build_conf(conf, exception_if_not_found=False)
        if res is not None:
            return res
        res=self.get_install_conf(conf, exception_if_not_found=False)
        if res is not None:
            return res
        res=self.get_format_conf(conf, exception_if_not_found=False)
        if res is not None:
            return res
        res=self.get_domain_conf(conf, exception_if_not_found=False)
        if res is not None:
            return res
        res=self.get_repo_conf(conf, exception_if_not_found=False)
        if res is not None:
            return res
        if exception_if_not_found:
            raise Exception(_(f"Unknown configuration '{conf}'"))
        return None

    def get_build_conf(self, build_conf:str, exception_if_not_found=True) -> BuildConfig:
        """Get a build config. object from its ID or actual config file path,
        or its description (or part of it)"""
        if not self.ready:
            raise Exception("Configuration has not yet been fully loaded")
        if build_conf in self._build_configs:
            return self._build_configs[build_conf]
        if exception_if_not_found:
            raise Exception(_("Unknown build configuration '%s'")%build_conf)
        return None

    def get_install_conf(self, install_conf:str, exception_if_not_found=True) -> InstallConfig:
        """Get an install config. object from its ID or actual config file path,
        or its description (or part of it)"""
        if not self.ready:
            raise Exception("Configuration has not yet been fully loaded")
        if install_conf in self._install_configs:
            return self._install_configs[install_conf]
        if exception_if_not_found:
            raise Exception(_("Unknown install configuration '%s'")%install_conf)
        return None

    def get_format_conf(self, format_conf:str, exception_if_not_found=True) -> FormatConfig:
        """Get a format config. object from its ID or actual config file path
        or its description (or part of it)"""
        if not self.ready:
            raise Exception("Configuration has not yet been fully loaded")
        if format_conf in self._format_configs:
            return self._format_configs[format_conf]
        if exception_if_not_found:
            raise Exception(_("Unknown format configuration '%s'")%format_conf)
        return None

    def get_domain_conf(self, domain_conf:str, exception_if_not_found=True) -> DomainConfig:
        """Get an install config. object from its ID or actual config file path
        or its description (or part of it)"""
        if not self.ready:
            raise Exception("Configuration has not yet been fully loaded")
        if domain_conf in self._domain_configs:
            return self._domain_configs[domain_conf]
        if exception_if_not_found:
            raise Exception(_("Unknown domain configuration '%s'")%domain_conf)
        return None

    def get_repo_conf(self, repo_conf:str, exception_if_not_found=True) -> RepoConfig:
        """Get a repo config. object from its ID or actual config file path"""
        if not self.ready:
            raise Exception("Configuration has not yet been fully loaded")
        if not repo_conf:
            if exception_if_not_found:
                raise Exception("CODEBUG: no repository configuration specified")
            return None

        if repo_conf in self._repo_configs:
            return self._repo_configs[repo_conf]
        rpath=os.path.realpath(repo_conf)
        if os.path.exists(rpath):
            for uid in self._repo_configs:
                if self._repo_configs[uid].config_file==rpath:
                    return self._repo_configs[uid]
        if exception_if_not_found:
            raise Exception(_("Unknown repo configuration '%s'")%repo_conf)
        return None

    def get_install_elements(self, install_conf, archive=None):
        """Analyse @install_conf and returns the elements required to manage installations as a tuple:
        - the path to the live Linux ISO file
        - the path to userdata specs file
        - the build infos
        If @archive is specified, it is used instead of the last one available
        NB: call release_install_elements() when the returned resources are not used anymore
        """
        if not self.ready:
            raise Exception("Configuration has not yet been fully loaded")
        if not isinstance(install_conf, InstallConfig):
            raise Exception("CODEBUG: @install_conf is not an InstallConfig object")
        # get the live Linux image and parameters files
        rconf=self.get_repo_conf(install_conf.build_repo_id)
        if archive is None:
            (ts, barname)=rconf.get_latest_archive()
            if barname is None:
                raise Exception(_("No build archive available"))
        else:
            if not rconf.archive_exists(archive):
                raise Exception(_("No archive '%s' in repository"))
            barname=archive

        cdir=rconf.get_archive_dir_from_cache(barname)
        if cdir is None:
            cdir=rconf.mount(barname)
        linuximage="%s/%s"%(cdir, file_iso)
        if not os.path.exists(linuximage):
            raise Exception(_(f"Build repo '{rconf.id}' seems corrupted: missing the '{file_iso}' file in archive '{barname}'"))

        linuxuserdata="%s/%s"%(cdir, file_userdata)
        if not os.path.exists(linuxuserdata):
            raise Exception(_(f"Build repo '{rconf.id}' seems corrupted: missing the '{file_userdata}' file in archive '{barname}'"))

        infosfile="%s/%s"%(cdir, file_infos)
        if not os.path.exists(infosfile):
            raise Exception(_(f"Build repo '{rconf.id}' seems corrupted: missing the '{file_infos}' file in archive '{barname}'"))
        infos=json.load(open(infosfile, "r"))

        return (linuximage, linuxuserdata, infos)

    def release_install_elements(self, install_conf, archive=None):
        """Release resources accessed when get_install_elements() was called"""
        if not self.ready:
            raise Exception("Configuration has not yet been fully loaded")
        rconf=self.get_repo_conf(install_conf.build_repo_id)
        if archive is None:
            (ts, barname)=rconf.get_latest_archive()
        else:
            if not rconf.archive_exists(archive):
                raise Exception(_("No archive '%s' in repository"))
            barname=archive

        if barname is not None:
            cdir=rconf.get_archive_dir_from_cache(barname)
            if cdir is None:
                try:
                    rconf.umount(barname)
                except:
                    pass

    def umount_all_repos(self):
        """Force unmounting all the repositories' archives which are still mounted"""
        if not self.ready:
            raise Exception("Configuration has not yet been fully loaded")
        for ruid in self._repo_configs:
            rconf=self._repo_configs[ruid]
            rconf.umount_all()

    #
    # helping the update process
    #
    def create_update_dir(self, ensure_empty=True):
        """Create a directory which the updgrade process can use"""
        path="%s/.tmp-update"%self.path
        if ensure_empty and os.path.exists(path):
            shutil.rmtree(path)
        os.makedirs(path, exist_ok=True)
        return path

    def merge_update(self):
        """Final step in the merge process: replace any directory in the update dir (see create_update_dir())
        which also exists in the global configuration directory"""
        if self.archives_cache_dir.startswith(self.path):
            raise Exception(_("Archives cache directory cannot be a subdirectory of the configuration's global directory"))
        upd_path=self.create_update_dir(ensure_empty=False)
        upd_fnames=os.listdir(upd_path)
        cur_fnames=os.listdir(self.path)
        for fname in cur_fnames:
            if fname in upd_fnames:
                cur_path="%s/%s"%(self.path, fname)
                if os.path.isdir(cur_path):
                    shutil.rmtree(cur_path)
                else:
                    os.remove(cur_path)
                shutil.move("%s/%s"%(upd_path, fname), cur_path)
        for fname in upd_fnames:
            if fname not in cur_fnames:
                shutil.move("%s/%s"%(upd_path, fname), "%s/%s"%(self.path, fname))

@dataclass
class ConfigStatus():
    valid: bool
    warnings: list[str]|None
    errors: list[str]|None
    todo: list[str]|None

class ConfigInterface(ABC):
    def __init__(self, global_conf:GlobalConfiguration, configfile:str):
        if not isinstance(global_conf, GlobalConfiguration):
            raise Exception("CODEBUG: @global_conf should be a GlobalConfiguration object")
        self._gconf=global_conf
        self._configfile=configfile

    @abstractproperty
    def id(self):
        pass

    @abstractproperty
    def descr(self):
        pass

    @abstractproperty
    def repo_id(self):
        pass

    @property
    def global_conf(self):
        return self._gconf

    @property
    def config_file(self):
        return self._configfile

    @property
    def config_dir(self):
        return os.path.dirname(self._configfile)

    @abstractproperty
    def status(self) -> ConfigStatus:
        """Get the status of the configuration"""
        pass

    def get_referenced_by_configurations(self) -> list[ConfigInterface]:
        """Get the configurations which reference this configuration (i.e. which need this configuration)"""
        res=[]
        for cid, conf in self.global_conf._build_configs.items():
            for rconf in conf.get_referenced_configurations():
                if rconf.id==self.id and conf not in res:
                    res.append(conf)
        for cid, conf in self.global_conf._install_configs.items():
            for rconf in conf.get_referenced_configurations():
                if rconf.id==self.id and conf not in res:
                    res.append(conf)

        for cid, conf in self.global_conf._format_configs.items():
            for rconf in conf.get_referenced_configurations():
                if rconf.id==self.id and conf not in res:
                    res.append(conf)
            
        for cid, conf in self.global_conf._domain_configs.items():
            for rconf in conf.get_referenced_configurations():
                if rconf.id==self.id and conf not in res:
                    res.append(conf)

        return res

    @abstractmethod
    def get_referenced_configurations(self) -> list[ConfigInterface]:
        """Get the configurations which are referenced this configuration (i.e. which this configuration needs)"""
        pass

    @classmethod
    @abstractmethod
    def create_new(global_conf:GlobalConfiguration, descr:str, subtype=None, extra=None) -> str:
        pass

    @abstractmethod
    def clone(self, other_global_conf:GlobalConfiguration, descr:str, map:dict[ConfigInterface, str]=None) -> str:
        """Clone a configuration, possibly into another global configuration
        @descr may be None if the new config's description should be the same as the cloned one
        Return: a dictionary to map the original ConfigInterface the cloned object's ID 
        """
        pass

    @abstractmethod
    def remove(self, must_be_kept:list[ConfigInterface]=None):
        """Remove the configuration"""
        pass

@dataclass
class L10N:
    timezone:str
    locale:str
    keyboard_layout:str|None=None
    keyboard_model:str|None=None
    keyboard_variant:str|None=None
    keyboard_option:str|None=None

    def to_dict(self) -> dict[str,str]:
        return {
            "timezone": self.timezone,
            "locale": self.locale,
            "keyboard-layout": self.keyboard_layout if self.keyboard_layout else "",
            "keyboard-model": self.keyboard_model if self.keyboard_model else "",
            "keyboard-variant": self.keyboard_variant if self.keyboard_variant else "",
            "keyboard-option": self.keyboard_option if self.keyboard_option else "",
        }

    def to_env_dict(self) -> dict[str,str]:
        return {
            "L10N_TIMEZONE": self.timezone,
            "L10N_LOCALE": self.locale,
            "L10N_KB_LAYOUT": self.keyboard_layout if self.keyboard_layout else "",
            "L10N_KB_MODEL": self.keyboard_model if self.keyboard_model else "",
            "L10N_KB_VARIANT": self.keyboard_variant if self.keyboard_variant else "",
            "L10N_KB_OPTION": self.keyboard_option if self.keyboard_option else "",
        }

class BuildConfig(ConfigInterface):
    """Represents a live Linux configuration"""
    def __init__(self, global_conf:GlobalConfiguration, configfile:str):
        super().__init__(global_conf, configfile)
        try:
            self._parse(json.load(open(configfile, "r")))
        except Exception as e:
            raise Exception(_(f"Invalid file '{configfile}' format: {str(e)}"))
        self._status=None

    @property
    def id(self):
        return self._id

    @property
    def l10n(self) -> L10N:
        """Get the l10n settings selected for the configuration"""
        return self._l10n

    @property
    def build_type(self):
        if "inseca-live-admin" in self._components:
            return BuildType.ADMIN
        if "inseca-live-wks" in self._components:
            return BuildType.WKS
        if "inseca-live-server" in self._components:
            return BuildType.SERVER
        return BuildType.SIMPLE

    @property
    def descr(self):
        return self._descr

    @property
    def status(self) -> ConfigStatus:
        if self._status is None:
            self._compute_status()
        return self._status

    def get_referenced_configurations(self) -> list[ConfigInterface]:
        if self.repo_id is not None:
            conf=self.global_conf.get_repo_conf(self.repo_id)
            return [conf]
        return []

    def _create_new(global_conf:GlobalConfiguration, descr:str, subtype:BuildType, path:str, ruid:str) -> str:
        buid="build-%s"%str(uuid.uuid4())
        (privdata_encrypt_key_priv, privdata_encrypt_key_pub)=x509.gen_rsa_key_pair()
        res_path=os.path.join(os.path.dirname(__file__), "../tools/resources")
        if subtype==BuildType.ADMIN:
            # create an ADMIN build configuration (no associated repo)
            repl={
                "dir": path,
                "descr": descr,
                "build": buid
            }
            data=util.load_file_contents(f"{res_path}/template-admin-build.json")
            data=ValueHolder.replace_variables(data, repl)
            os.makedirs(path, exist_ok=True)
            conf_file="%s/build-configuration.json"%path
            util.write_data_to_file(data, conf_file)

        else:
            # create a generic build config and its repo
            (build_sign_key_priv, build_sign_key_pub)=x509.gen_rsa_key_pair()
            (userdata_sign_key_priv, userdata_sign_key_pub)=x509.gen_rsa_key_pair()
            if ruid is None:
                ruid=RepoConfig.create_new(global_conf, f"Repository for build '{descr}'", RepoType.BUILD)
            repl={
                "dir": path,
                "descr": descr,
                "build": buid,
                "repo": ruid
            }
            data=util.load_file_contents(f"{res_path}/template-generic-build.json")
            data=ValueHolder.replace_variables(data, repl)
            os.makedirs(path, exist_ok=True)
            conf_file="%s/build-configuration.json"%path
            util.write_data_to_file(data, conf_file)

            build_sign_key_pub.copy_to("%s/build-sign-key.pub"%path)
            build_sign_key_priv.copy_to("%s/build-sign-key.priv"%path)
            userdata_sign_key_pub.copy_to("%s/userdata-sign-key.pub"%path)
            userdata_sign_key_priv.copy_to("%s/userdata-sign-key.priv"%path)

        privdata_encrypt_key_pub.copy_to("%s/privdata-encrypt-key.pub"%path)
        privdata_encrypt_key_priv.copy_to("%s/privdata-encrypt-key.priv"%path)

        return buid

    def create_new(global_conf:GlobalConfiguration, descr:str, subtype=None, extra=None) -> str:
        if subtype is not None and not isinstance(subtype, BuildType):
            raise Exception(f"Invalid repository sub type '{subtype}'")
        if subtype==BuildType.ADMIN:
            # create an ADMIN build configuration (no associated repo)
            path=identify_free_filename(global_conf.path+"/build-configurations", "build-adm")
        else:
            path=identify_free_filename(global_conf.path+"/build-configurations", "build")

        return BuildConfig._create_new(global_conf, descr, subtype, path, None)

    def clone(self, other_global_conf:GlobalConfiguration, descr:str, map:dict[ConfigInterface, str]=None) -> str:
        # The cloning actually creates a new build configuration (new keys, etc.) and
        # copies some attributes and extra files of this configuration
        gconf=self.global_conf if other_global_conf is None else other_global_conf
        if map is None:
            map={}

        try:
            nruid=None
            path=None
            nuid=None
            cloned=None
            gconf2=None

            # clone repo config.
            if self.repo_id is not None:
                rconf=self.global_conf.get_repo_conf(self.repo_id)
                nruid=rconf.clone(gconf, f"Repository for build '{descr}'", map)
            
            # copy all the resources of the build config to the path of the cloned config
            if self.build_type==BuildType.ADMIN:
                # create an ADMIN build configuration (no associated repo)
                path=identify_free_filename(gconf.path+"/build-configurations", "build-adm")
            else:
                path=identify_free_filename(gconf.path+"/build-configurations", "build")
            shutil.copytree(self.config_dir, path)

            # create new config
            nuid=BuildConfig._create_new(gconf, descr, self.build_type, path, nruid)

            #  using a new GlobalConfiguration object
            gconf2=GlobalConfiguration(gconf.path)
            cloned=gconf2.get_build_conf(nuid)
            data=json.loads(util.load_file_contents(cloned.config_file))
            data["components"]=self.components
            data["validity-months"]=self._validity_months
            data["version"]=self._version
            util.write_data_to_file(json.dumps(data, indent=4), cloned.config_file)

            map[self]=nuid
            if nruid is not None:
                map[rconf]=nruid
            return nuid
        except Exception as e:
            if rconf is not None:
                try:
                    if gconf2 is None:
                        gconf2=GlobalConfiguration(gconf.path)
                    rconf=gconf2.get_any_conf(nruid)
                except:
                    pass
            if path is not None:
                shutil.rmtree(path, ignore_errors=True)
            if cloned is not None:
                try:
                    cloned.remove()
                except:
                    pass
            raise e

    def remove(self, must_be_kept:list[str]=None):
        tokeep=[] if must_be_kept is None else must_be_kept

        if self not in tokeep:
            shutil.rmtree(self.config_dir, ignore_errors=True)
            if self.repo_id is not None:
                try:
                    rconf=self.global_conf.get_repo_conf(self.repo_id)
                    rconf.remove(must_be_kept)
                except Exception:
                    pass

    @property
    def repo_id(self):
        return self._repo_id

    @property
    def version(self):
        return self._version

    @property
    def valid_to(self):
        return self._valid_to

    @property
    def privdata_pubkey(self):
        """Full path of the file containing the public key to encrypt PRIVDATA"""
        if self._privdata_pubkey:
            return "%s/%s"%(self.config_dir, self._privdata_pubkey)
        return None

    @property
    def privdata_privkey(self):
        """Full path of the file containing the public key to encrypt PRIVDATA"""
        if self._privdata_privkey:
            return "%s/%s"%(self.config_dir, self._privdata_privkey)
        return None

    @property
    def signing_privkey(self):
        """Full path of the file containing the private signing key used to add a signature when publishing a new live build
        (the public key is also included in the live build itself).
        Relies on the 'signature' component being included in the live Linux, so this function may return None"""
        if "signature" in self._components:
            fname="%s/%s"%(self.config_dir, self._components["signature"]["build-skey-priv-file"])
            if not os.path.exists(fname):
                raise Exception(_("Missing live Linux signing private key file '%s'")%fname)
            return fname
        return None

    @property
    def signing_pubkey(self):
        """Full path of the file containing the public signing key for which the associated private key is used to add a signature when publishing a new live build
        (this public key is included in the live build itself).
        Relies on the 'signature' component being included in the live Linux, so this function may return None"""
        if "signature" in self._components:
            file=self._components["signature"]["build-skey-pub-file"]
            if file is not None:
                fname=f"{self.config_dir}/{file}"
                if not os.path.exists(fname):
                    raise Exception(_("Missing live Linux signing public key file '%s'")%fname)
                return fname
        return None

    @property
    def build_dir(self):
        return self._build_dir

    @property
    def components(self):
        """Get the list of components and their configuration."""
        return self._components

    @property
    def components_builtin_dir(self):
        return f"{self.global_conf.script_dir}/components"

    @property
    def components_extra_dir(self):
        components_path_extra=None
        if "INSECA_EXTRA_COMPONENTS" in os.environ:
            components_path_extra=os.environ["INSECA_EXTRA_COMPONENTS"]
            if not os.path.isdir(components_path_extra):
                components_path_extra=None # ignore thah buggy setting
        return components_path_extra

    @property
    def base_os_component(self):
        components_path_builtin=self.components_builtin_dir
        for component in self._components:
            comp_conf=f"{components_path_builtin}/{component}/config.json"
            if os.path.exists(comp_conf):
                cdata=json.load(open(comp_conf, "r"))
                if "base-os" in cdata["provides"]:
                    return component
        raise Exception("Missing a 'base-os' component")

    @property
    def image_iso_file(self):
        return "%s/%s/%s"%(self._build_dir, self._id, file_iso)

    @property
    def image_userdata_specs_file(self):
        return "%s/%s/%s"%(self._build_dir, self._id, file_userdata)

    @property
    def image_infos_file(self):
        return "%s/%s/%s"%(self._build_dir, self._id, file_infos)

    @property
    def userdata_specs(self):
        """Get the specifications of the USERDATA required by the live Linux created by the build configuration.
        Will be like:
        {
            "VPN-OpenVPN": {
                "ovpn-file": {
                    "descr": "OpenVPN configuration file",
                    "type": "file"
                }
            },
            "guest-os": {
                "os-image": {
                    "descr": "OS disk image file",
                    "type": "file"
                }
            }
        }
        """
        components_path_builtin=self.components_builtin_dir
        components_path_extra=self.components_extra_dir
        userdata_specs={}
        for component in self.components:
            comp_conf=None
            if components_path_extra:
                comp_conf="%s/%s/config.json"%(components_path_extra, component)
                if not os.path.exists(comp_conf):
                    comp_conf=None
            if not comp_conf:
                comp_conf="%s/%s/config.json"%(components_path_builtin, component)
            if os.path.exists(comp_conf):
                cdata=json.load(open(comp_conf, "r"))
                if "userdata" in cdata and len(cdata["userdata"])>0:
                    userdata_specs[component]=cdata["userdata"]
        return userdata_specs

    def _parse(self, data):
        if not isinstance(data, dict):
            raise Exception("Invalid configuration: not a dictionary")
        specs={
            "id": [str, False, True],
            "descr": [str, False, True],
            "l10n": [dict, True, False],
            "version": [str, False, True],
            "build-dir": [str, False, True],
            "repo": [str, True, True],
            "privdata-ekey-pub-file": [str, True, True],
            "privdata-ekey-priv-file": [str, True, True],
            "components": [dict, False, True],
            "validity-months": [int, False, True]
        }
        try:
            _validate_attributes(data, specs)
        except Exception as e:
            raise Exception(f"Invalid live configuration '{self.config_file}': {str(e)}")
        self._id=data["id"]
        self._repo_id=data["repo"]
        self._version=data["version"]
        self._validity_months=int(data["validity-months"])
        self._privdata_pubkey=data["privdata-ekey-pub-file"]
        self._privdata_privkey=data["privdata-ekey-priv-file"]

        now=datetime.date.today()
        month=now.month-1+self._validity_months
        year=now.year+month//12
        month=month%12+1
        day=min(now.day, calendar.monthrange(year,month)[1])
        self._valid_to=int(datetime.date(year, month, day).strftime('%s'))

        self._build_dir=data["build-dir"]
        self._components=data["components"]
        self._descr=data["descr"]

        if "l10n" in data:
            specs={
                "timezone": [str, False, True],
                "locale": [str, False, True],
                "keyboard-layout": [str, True, False],
                "keyboard-model": [str, True, False],
                "keyboard-variant": [str, True, False],
                "keyboard-option": [str, True, False]
            }
            l10ndata=data["l10n"]
            try:
                _validate_attributes(l10ndata, specs)
            except Exception as e:
                raise Exception(f"Invalid live configuration's l10n data '{self.config_file}': {str(e)}")
            self._l10n=L10N(timezone=l10ndata.get("timezone"), locale=l10ndata.get("locale"), keyboard_layout=l10ndata.get("keyboard-layout"),
                            keyboard_model=l10ndata.get("keyboard-model"), keyboard_variant=l10ndata.get("keyboard-variant"),
                            keyboard_option=l10ndata.get("keyboard-option"))
        else:
            self._l10n=L10N(timezone="UTC", locale="en_US.UTF-8", keyboard_layout="en", keyboard_model="pc105")

    def _get_pending_iso(self):
        builder=LiveBuilder.Builder(self.id)
        iso_img_file=builder.image_file
        if os.path.exists(iso_img_file):
            ts=os.path.getctime(iso_img_file)
            return (iso_img_file, ts, util.format_timestamp(ts))
        else:
            return (None, None, None)

    def _compute_status(self):
        warnings=[]
        errors=[]
        todo=[]

        # global check
        cdefs={} # key=component ID, value=component's configuration
        for cid in self._components:
            cdefs[cid]=None
            try:
                cfile=self.get_component_src_dir(cid)+"/config.json"
                if not os.path.exists(cfile):
                    errors.append(f"Component '{cid}' does not have any config.json configuration file")
                try:
                    cdata=json.load(open(cfile, "r"))
                except Exception as e:
                    errors.append(f"Invalid or unreadable config.json configuration file for component '{cid}'")
                cdefs[cid]=cdata
                if "provides" not in cdata:
                    errors.append(f"Configuration of component '{cid}' is invalid: no 'provides' attribute")
            except Exception as e:
                errors.append(str(e))

        # search the 'base' and 'components-init' features
        base=None
        cinit=None
        for cid in self._components:
            cdata=cdefs[cid]
            if cdata is not None:
                if "base-os" in cdata["provides"]:
                    if base:
                        errors.append("The 'base' feature is present in more than one component")
                    base=True
                if "components-init" in cdata["provides"]:
                    if cinit:
                        errors.append("The 'components-init' feature is present in more than one component")
                    cinit=True
        if not base:
            errors.append("Missing a 'base-os' component")
        if not cinit:
            errors.append("Missing a 'components-init' component")

        # if build type is not WKS or SERVER, then the components list should not include any component
        # which needs a USERDATA
        if self.build_type not in (BuildType.WKS, BuildType.SERVER):
            for cid in self._components:
                cdata=cdefs[cid]
                if cdata is not None and len (cdata["userdata"])>0:
                    errors.append(_("Configuration is not 'workstation' but included component '%s' requires some USERDATA")%cid)

        # repo. configuration
        archive_ts=0
        if self.repo_id is not None:
            rconf=self.global_conf.get_repo_conf(self.repo_id, exception_if_not_found=False)
            if rconf is None:
                errors.append(_(f"Inexistant associated repo '{self.repo_id}'"))
            else:
                if rconf.type!=RepoType.BUILD:
                    errors.append(_("Associated repo is not of type BUILD"))
                else:
                    # get timestamp of the last published archive
                    try:
                        (archive_ts, dummy)=rconf.get_latest_archive()
                    except Exception as e:
                        archive_ts=None
                        errors.append(str(e))

        # todo
        rebuild_needed=False
        publish_needed=False

        files_ts=get_last_file_modification_ts(self.config_dir, self.build_dir)
        for cid in self._components:
            if cdefs[cid] is not None:
                component_dir=self.get_component_src_dir(cid)
                component_ts=get_last_file_modification_ts(component_dir)
                if component_ts>files_ts:
                    files_ts=component_ts

        (iso_file, iso_ts, iso_strts)=self._get_pending_iso()
        if iso_file:
            if self.repo_id:
                publish_needed=True
        if archive_ts is not None and files_ts>archive_ts:
            if iso_file:
                if files_ts>iso_ts:
                    rebuild_needed=True
            else:
                rebuild_needed=True

        if rebuild_needed:
            if iso_file:
                todo.append(_("needs to be rebuilt (and existing build @ %s)")%iso_strts)
            else:
                todo.append(_("needs to be rebuilt"))
        if iso_file:
            if publish_needed:
                todo.append(_("needs to be published"))
            else:
                warnings.append(_("existing build @ %s")%iso_strts)

        self._status=ConfigStatus(len(errors)==0, warnings, errors, todo)

    def validate(self):
        """Check that the configuration is coherent"""
        if not self.status.valid:
            raise Exception("Configuration is invalid")


    def get_component_src_dir(self, component):
        components_path_builtin=self.components_builtin_dir
        components_path_extra=self.components_extra_dir
        if components_path_extra is not None and os.path.exists(f"{components_path_extra}/{component}"):
            return f"{components_path_extra}/{component}"
        if os.path.exists(f"{components_path_builtin}/{component}"):
            return f"{components_path_builtin}/{component}"
        raise Exception("Component '%s' not found"%component)

    def get_component_blobs_dirs(self, component, ignore_missing=False):
        base_os_component=self.base_os_component
        paths=[]
        path=f"{self.global_conf.path}/blobs/{base_os_component}/{component}"
        if ignore_missing or os.path.exists(path):
            paths.append(path)
        path=f"{self.global_conf.path}/blobs/generic/{component}"
        if ignore_missing or os.path.exists(path):
            paths.append(path)
        return paths

#
# Install configurations
#
class InstallConfig(ConfigInterface):
    """Represents an installation configuration"""
    def __init__(self, global_conf:GlobalConfiguration, configfile:str):
        super().__init__(global_conf, configfile)
        self._build_id=None
        try:
            self._parse(json.load(open(configfile, "r")))
        except Exception as e:
            err=str(e)
            raise Exception(_(f"Invalid file '{configfile}' format: {err}"))
        self._status=None

    @property
    def id(self):
        return self._id

    @property
    def descr(self):
        return self._data["descr"]

    @property
    def status(self) -> ConfigStatus:
        if self._status is None:
            self._compute_status()
        return self._status

    def get_referenced_configurations(self) -> list[ConfigInterface]:
        def _search_for_repos(global_conf:GlobalConfiguration, data: dict) -> list[ConfigInterface]:
            res=[]
            for key, value in data.items():
                if isinstance(value, dict):
                    res+=_search_for_repos(global_conf, value)
                elif isinstance(value, str):
                    conf=global_conf.get_any_conf(value, exception_if_not_found=False)
                    if conf is not None and conf not in res:
                        res.append(conf)
            return res

        # NB: we don't list the build configuration itself because it is only its repo config which is a dependency
        res=[]
        rbconf=self.global_conf.get_repo_conf(self.build_repo_id, exception_if_not_found=False)
        if rbconf is not None:
            res.append(rbconf)
        rconf=self.global_conf.get_repo_conf(self.repo_id, exception_if_not_found=False)
        if rconf is not None:
            res.append(rconf)
        return res + _search_for_repos(self.global_conf, self.userdata)

    def _create_new(global_conf:GlobalConfiguration, descr:str, path:str, bconf:BuildConfig, ruid:str) -> str:
        # create an install config and its repo
        if bconf is None:
            raise Exception(f"Install configuration has no associated build configuration")
        build_repo=bconf.repo_id
        if build_repo is None:
            raise Exception(f"Build configuration '{bconf.id}' does not have any associated repository")
        privdata_enc_privkey=bconf.privdata_privkey

        userdata_specs=bconf.userdata_specs
        userdata={}
        for component in userdata_specs:
            for entry in userdata_specs[component]:
                if userdata_specs[component][entry]["type"]=="file":
                    if component not in userdata:
                        userdata[component]={}
                    userdata[component][entry]=None
    
        (device_metadata_sign_key_priv, device_metadata_sign_key_pub)=x509.gen_rsa_key_pair()
        (attestation_sign_key_priv, attestation_sign_key_pub)=x509.gen_rsa_key_pair()

        iuid=f"install-{str(uuid.uuid4())}"
        created_conf=iuid
        if ruid is None:
            ruid=RepoConfig.create_new(global_conf, f"Repository for install '{descr}'", RepoType.INSTALL)
        password=cgen.generate_password()
        repl={
            "descr": descr,
            "install": iuid,
            "repo": ruid,
            "build": build_repo,
            "rescue": json.dumps(password)[1:-1] # properly encore password as JSON string
        }
        res_path=os.path.join(os.path.dirname(__file__), "../tools/resources")
        data=util.load_file_contents("%s/template-install.json"%(res_path))
        data=ValueHolder.replace_variables(data, repl, ignore_missing=True)

        conf=json.loads(data)
        conf["userdata"]=userdata
        os.makedirs(path, exist_ok=True)

        # associate the build signing key, if available
        build_sign_key_pub_file=bconf.signing_pubkey
        if build_sign_key_pub_file:
            shutil.copyfile(build_sign_key_pub_file, f"{path}/build-sign-key.pub")
            conf["build-skey-pub-file"]="build-sign-key.pub"

        conf_file=f"{path}/install-configuration.json"
        util.write_data_to_file(json.dumps(conf, indent=4, sort_keys=True), conf_file)

        device_metadata_sign_key_pub.copy_to(f"{path}/device-metadata-sign-key.pub")
        device_metadata_sign_key_priv.copy_to(f"{path}/device-metadata-sign-key.priv") # will be used by the install config
        attestation_sign_key_pub.copy_to(f"{path}/attestation-sign-key.pub")
        attestation_sign_key_priv.copy_to(f"{path}/attestation-sign-key.priv")
        if privdata_enc_privkey:
            shutil.copyfile(privdata_enc_privkey, f"{path}/privdata-encrypt-key.priv")

        # copy template data
        for fname in ("grub-config", "user-profile"):
            tmptar=tempfile.NamedTemporaryFile()
            tarobj=tarfile.open(tmptar.name, mode='w')
            tarobj.add(f"{res_path}/{fname}", arcname=".", recursive=True)
            tarobj.close()
            tarobj=tarfile.open(tmptar.name, mode='r')
            tarobj.extractall("%s/%s"%(path, fname))
        os.makedirs(f"{path}/user-documents", exist_ok=True)
        shutil.copyfile(f"{res_path}/default-wallpaper.jpg", f"{path}/default-wallpaper.jpg")
        return iuid

    def create_new(global_conf:GlobalConfiguration, descr:str, extra=None) -> str:
        if extra is None:
            raise Exception("Build configuration must be specified")
        if not isinstance(extra, BuildConfig):
            raise Exception(f"Invalid build configuration object '{extra}'")
        path=identify_free_filename(global_conf.path+"/install-configurations", "install")
        return InstallConfig._create_new(global_conf, descr, path, extra, None)

    def clone(self, other_global_conf:GlobalConfiguration, descr:str, map:dict[ConfigInterface, str]=None) -> str:
        # The cloning actually creates a new install configuration (new keys, etc.) and
        # copies the other files of this configuration
        gconf=self.global_conf if other_global_conf is None else other_global_conf
        if map is None:
            map={}

        try:
            path=None
            cloned=None
            gconf2=None

            # clone repo config.
            rconf=self.global_conf.get_repo_conf(self.repo_id)
            nruid=rconf.clone(gconf, f"Repository for install '{descr}'", map)

            # identify the build configuration to use
            bconf=None
            brconf=self.global_conf.get_repo_conf(self.build_repo_id)
            for ref in brconf.get_referenced_by_configurations():
                if isinstance(ref, BuildConfig):
                    bconf=ref
                    break

            if bconf is not None and other_global_conf is not None:
                # when cloning to another INSECA root, the referenced build config must also have been cloned
                # first (which is done for example by the inseca program)
                cid=map.get(bconf)
                if cid is None:
                    raise Exception("Associated build configuration has not been cloned")
                gconf2=GlobalConfiguration(gconf.path)
                bconf=gconf2.get_build_conf(cid)

            # copy all the resources of the install config to the path of the cloned config
            path=identify_free_filename(gconf.path+"/install-configurations", "install")
            shutil.copytree(self.config_dir, path)

            # create new config
            nuid=InstallConfig._create_new(gconf, descr, path, bconf, nruid)

            # copy components using a new GlobalConfiguration object
            gconf2=GlobalConfiguration(gconf.path) # needs to be re-created here anywaus because we added a new install config
            cloned=gconf2.get_install_conf(nuid)
            data=json.loads(util.load_file_contents(cloned.config_file))
            for part in ("dev-format", "install", "parameters", "userdata"):
                data[part]=self._data[part]
            util.write_data_to_file(json.dumps(data, indent=4), cloned.config_file)

            map[self]=nuid
            map[rconf]=nruid
            return nuid
        except Exception as e:
            try:
                if gconf2 is None:
                    gconf2=GlobalConfiguration(gconf.path)
                rconf=gconf2.get_any_conf(nruid)
                rconf.remove()
            except:
                pass
            if path is not None:
                shutil.rmtree(path, ignore_errors=True)
            if cloned is not None:
                try:
                    cloned.remove()
                except:
                    pass
            raise e

    def remove(self, must_be_kept:list[str]=None):
        tokeep=[] if must_be_kept is None else must_be_kept

        if self not in tokeep:
            shutil.rmtree(self.config_dir, ignore_errors=True)
            try:
                rconf=self.global_conf.get_repo_conf(self.repo_id)
                rconf.remove(must_be_kept)
            except Exception:
                pass

    @property
    def repo_id(self):
        return self._repo_id

    @property
    def build_id(self):
        """Get the build ID, which may be None if not yet computed by the GlobalConfiguration"""
        return self._build_id

    @build_id.setter
    def build_id(self, build_id):
        """Let the GlobalConfiguration define the build_id"""
        self._build_id=build_id

    @property
    def build_repo_id(self):
        return self._build_repo_id

    @property
    def parameters_core(self):
        """Get the list of "core" parameters, as specified in the source code (common to all configurations)"""
        return self._params_core

    @property
    def parameters_config(self):
        """Get the list of "config" parameters, as specified in the configuration itself"""
        return self._params_config

    @property
    def parameters(self):
        """Get the list of all the parameters"""
        return self._params_combined

    @property
    def overrides(self):
        """Get the values of parameters which are overriden by the configuration (and can thus not be changed
        by the admin)"""
        return self._overrides

    @property
    def devicemeta_pubkey(self):
        """Full path of the file containing the public key to verify the signnature of the device's metadata"""
        return "%s/%s"%(self.config_dir, self._devicemeta_pubkey)

    @property
    def devicemeta_privkey(self):
        """Full path of the file containing the private key to sign the device's metadata"""
        return "%s/%s"%(self.config_dir, self._devicemeta_privkey)

    @property
    def signing_pubkey(self):
        """Full path of the file containing the public signing key for which the associated private key is used to add a signature when a new live build was published
        (Refer to the associated's build config).
        """
        return "%s/%s"%(self.config_dir, self._build_sign_pubkey)

    @property
    def password_rescue(self):
        return self._password_rescue

    @property
    def userdata(self):
        """Get the USERDATA for the installation, will be like:
            "guest-os": {
                "os-image": "repo-f418dbc5-39bc-4065-919d-5814dd7c57e3"
            },
            "VPN-OpenVPN": {
                "ovpn-file": "repo-83f9d052-ba7f-42ad-9910-18805ab145e3"
            }
        """
        return self._userdata

    def _parse(self, data):
        if not isinstance(data, dict):
            raise Exception("Invalid configuration: not a dictionary")
        specs={
            "id": [str, False, True],
            "descr": [str, False, True],
            "build-repo": [str, False, True],
            "repo": [str, True, True],
            "parameters": [dict, True, True],
            "dev-format": [dict, False, True],
            "devicemeta-skey-priv-file": [str, False, True],
            "devicemeta-skey-pub-file": [str, False, True],
            "build-skey-pub-file": [str, True, True],
            "password-rescue": [str, False, True],
            "install": [dict, False, True],
            "userdata": [dict, False, False]
        }
        try:
            _validate_attributes(data, specs)
            params=data["parameters"]
            for pname in params:
                _validate_parameter_definition(params[pname])
        except Exception as e:
            raise Exception(_(f"Invalid install configuration '{self.config_file}': {str(e)}"))

        # top level information
        self._id=data["id"]
        self._build_repo_id=data["build-repo"]
        self._repo_id=data["repo"]
        self._devicemeta_pubkey=data["devicemeta-skey-pub-file"]
        self._devicemeta_privkey=data["devicemeta-skey-priv-file"]
        self._build_sign_pubkey=data["build-skey-pub-file"]
        self._password_rescue=data["password-rescue"]
        self._userdata={}
        if "userdata" in data:
            self._userdata=data["userdata"]

        # load the core configuration which contains the hard coded parts of any install configuration
        # and which needs to be "merged" (or combined) with the parts provided by the install configurations'
        # the user defined
        ptype=data["dev-format"].get("type", "hybrid") # defaults to "hybrid" if not specified
        if ptype=="hybrid":
            core_conf=json.load(open("%s/core-install-config-hybrid.json"%os.path.dirname(__file__), "r"))
        else:
            core_conf=json.load(open("%s/core-install-config.json"%os.path.dirname(__file__), "r"))

        # merge the configuration with the core configuration: parameters
        self._params_core=core_conf["parameters"]
        self._params_config=data["parameters"]
        self._params_combined=self._params_core.copy()
        for param in self._params_config:
            if param in self._params_core:
                raise Exception(_("Invalid parameter '%s': already part of core configuration")%param)
            self._params_combined[param]=self._params_config[param]

        # merge the configuration with the core configuration: dev-format
        conf_dev_format=data["dev-format"]
        dev_fmt=core_conf["dev-format"]
        for section in ("unprotected", "protected", "decryptors", "signatures"):
            if section in conf_dev_format:
                for entry in conf_dev_format[section]:
                    if entry in dev_fmt[section]:
                        raise Exception(_(f"Invalid configuration entry '{entry}' in section '{section}': already part of core configuration"))
                    dev_fmt[section][entry]=conf_dev_format[section][entry]
        self._dev_format=dev_fmt
        #print("SPEC: %s"%json.dumps(data, indent=4))

        # compute overrides
        self._overrides={}
        if "override" in conf_dev_format:
            self._overrides=conf_dev_format["override"].copy()

        self._data=data

    def _compute_status(self):
        warnings=[]
        errors=[]
        todo=[]

        # associated repo
        archive_ts=0
        if self.repo_id is None:
            errors.append(_("No associated repository configuration"))
        else:
            rconf=self.global_conf.get_repo_conf(self.repo_id, exception_if_not_found=False)
            if rconf is None:
                errors.append(_(f"Inexistant referenced repository '{self.repo_id}'"))
            else:
                if rconf.type!=RepoType.INSTALL:
                    errors.append(_("Referenced repository is not of type INSTALL"))
                else:
                    # get timestamp of the last published archive
                    try:
                        (archive_ts, dummy)=rconf.get_latest_archive()
                    except Exception as e:
                        archive_ts=None
                        errors.append(str(e))

        # associated build repo
        rconf=self.global_conf.get_repo_conf(self.build_repo_id, exception_if_not_found=False)
        if rconf is None:
            errors.append(_(f"Inexistant associated build repository '{self.build_repo_id}'"))
        elif rconf.type!=RepoType.BUILD:
            errors.append(_(f"Referenced build repository '{self.build_repo_id}' is not of type BUILD"))

        # associated build config
        if self.build_id is None:
            warnings.append(f"Missing associated build configuration")
        else:
            bconf=self.global_conf.get_build_conf(self.build_id, exception_if_not_found=False)
            if bconf is None:
                errors.append(_(f"Inexistant associated build configuration '{self.build_id}'"))
            else:
                if bconf.repo_id is None:
                    errors.append(_(f"No associated repository configuration"))

                if bconf.build_type not in (BuildType.WKS, BuildType.SERVER):
                    errors.append(_("Associated build configuration is not of type 'workstation' or 'server'"))

                # userdata checks
                userdata_specs=bconf.userdata_specs
                userdata=self.userdata
                for component in userdata_specs:
                    for entry in userdata_specs[component]:
                        edata=userdata_specs[component][entry]
                        if edata["type"]=="file":
                            if component not in userdata:
                                errors.append("Missing USERDATA specification for component '%s'"%component)
                            else:
                                if entry not in userdata[component]:
                                    errors.append("Missing USERDATA attribute '%s' for component '%s'"%(entry, component))
                                else:
                                    ruid=userdata[component][entry]
                                    if ruid:
                                        userdataconf=self.global_conf.get_repo_conf(ruid, exception_if_not_found=False)
                                        if userdataconf is None:
                                            errors.append("Referenced USERDATA repository '%s' for attribute '%s' of component '%s' does not exist"%(ruid, entry, component))
                                        elif userdataconf.type!=RepoType.USERDATA:
                                            errors.append("Referenced repository '%s' for attribute '%s' of component '%s' is not a USERDATA repository"%(ruid, entry, component))
                                    else:
                                        errors.append("Unspecified USERDATA repository for attribute '%s' of component '%s'"%(entry, component))

                                for entry in userdata[component]:
                                    if entry not in userdata_specs[component]:
                                        errors.append("Invalid USERDATA attribute '%s' for component '%s'"%(entry, component))
                for component in userdata:
                    if component not in userdata_specs:
                        errors.append("USERDATA specified but not used for component '%s'"%component)

                # checking match of keys
                path=self.config_dir
                i_privkey="%s/privdata-encrypt-key.priv"%path
                b_privkey=bconf.privdata_privkey
                if b_privkey is None:
                    if os.path.exists(i_privkey):
                        errors.append("PRIVDATA decrypt key is defined but useless ('%s')"%i_privkey)
                else:
                    if not os.path.exists(i_privkey):
                        errors.append("PRIVDATA decrypt key is missing ('%s')"%i_privkey)
                    else:
                        idata=util.load_file_contents(i_privkey, binary=True)
                        bdata=util.load_file_contents(b_privkey, binary=True)
                        if idata!=bdata:
                            errors.append("PRIVDATA decrypt key does not match associated build's key")

        # todo
        if archive_ts is not None:
            files_ts=get_last_file_modification_ts(self.config_dir)
            if archive_ts<files_ts:
                todo.append(_("needs to be published"))

        self._status=ConfigStatus(len(errors)==0, warnings, errors, todo)

    def validate(self):
        """Check that the configuration is coherent"""
        if not self.status.valid:
            raise Exception("Configuration is invalid")

    def export_complete_configuration(self):
        """Export the merged (complete) configuration as a struture, ready to be used"""
        exp=self._data.copy()
        exp["parameters"]=self._params_combined
        exp["dev-format"]=self._dev_format
        return exp

#
# Format configurations
#
class FormatConfig(ConfigInterface):
    """Represents a device formatter configuration"""
    def __init__(self, global_conf:GlobalConfiguration, configfile:str):
        super().__init__(global_conf, configfile)
        if not isinstance(global_conf, GlobalConfiguration):
            raise Exception("CODEBUG: @global_conf should be a GlobalConfiguration object")
        try:
            self._parse(json.load(open(configfile, "r")))
        except Exception as e:
            raise Exception(_(f"Invalid file '{configfile}' format: {str(e)}"))
        self._status=None

    @property
    def id(self):
        return self._id

    @property
    def descr(self):
        return self._data["descr"]

    @property
    def status(self) -> ConfigStatus:
        if self._status is None:
            self._compute_status()
        return self._status

    def get_referenced_configurations(self) -> list[ConfigInterface]:
        rconf=self.global_conf.get_repo_conf(self.repo_id)
        return [rconf]

    def _create_new(global_conf:GlobalConfiguration, descr:str, path:str, ruid:str) -> str:
        # create a format config and its repo
        (device_metadata_sign_key_priv, device_metadata_sign_key_pub)=x509.gen_rsa_key_pair()

        ifuid=f"format-{str(uuid.uuid4())}"
        created_conf=ifuid
        if ruid is None:
            ruid=RepoConfig.create_new(global_conf, f"Repository for format '{descr}'", RepoType.FORMAT)
        password=cgen.generate_password()
        repl={
            "descr": descr,
            "install": ifuid,
            "repo": ruid,
            "rescue": json.dumps(password)[1:-1] # properly encore password as JSON string
        }
        res_path=os.path.join(os.path.dirname(__file__), "../tools/resources")
        data=util.load_file_contents(f"{res_path}/template-format.json")
        data=ValueHolder.replace_variables(data, repl, ignore_missing=True)
        conf_file=f"{path}/format-configuration.json"
        os.makedirs(path, exist_ok=True)
        util.write_data_to_file(data, conf_file)

        device_metadata_sign_key_pub.copy_to(f"{path}/device-metadata-sign-key.pub")
        device_metadata_sign_key_priv.copy_to(f"{path}/device-metadata-sign-key.priv")
        return ifuid

    def create_new(global_conf:GlobalConfiguration, descr:str, extra=None) -> str:
        path=identify_free_filename(global_conf.path+"/format-configurations", "format")
        return FormatConfig._create_new(global_conf, descr, path, None)

    def clone(self, other_global_conf:GlobalConfiguration, descr:str, map:dict[ConfigInterface, str]=None) -> str:
        # The cloning actually creates a new format configuration (new keys, etc.) and
        # copies the other files of this configuration
        gconf=self.global_conf if other_global_conf is None else other_global_conf
        if map is None:
            map={}

        try:
            path=None
            cloned=None
            gconf2=None

            # clone repo config.
            rconf=self.global_conf.get_repo_conf(self.repo_id)
            nruid=rconf.clone(gconf, f"Repository for format '{descr}'", map)
            
            # copy all the resources of the install config to the path of the cloned config
            path=identify_free_filename(gconf.path+"/format-configurations", "format")
            shutil.copytree(self.config_dir, path)

            # create new config
            nuid=FormatConfig._create_new(gconf, descr, path, nruid)

            # copy components using a new GlobalConfiguration object
            gconf2=GlobalConfiguration(gconf.path)
            cloned=gconf2.get_format_conf(nuid)
            data=json.loads(util.load_file_contents(cloned.config_file))
            for part in ("dev-format", "parameters"):
                data[part]=self._data[part]
            util.write_data_to_file(json.dumps(data, indent=4), cloned.config_file)

            map[self]=nuid
            map[rconf]=nruid
            return nuid
        except Exception as e:
            try:
                if gconf2 is None:
                    gconf2=GlobalConfiguration(gconf.path)
                rconf=gconf2.get_any_conf(nruid)
                rconf.remove()
            except:
                pass
            if path is not None:
                shutil.rmtree(path, ignore_errors=True)
            if cloned is not None:
                try:
                    cloned.remove()
                except:
                    pass
            raise e

    def remove(self, must_be_kept:list[str]=None):
        tokeep=[] if must_be_kept is None else must_be_kept

        if self not in tokeep:
            shutil.rmtree(self.config_dir, ignore_errors=True)
            try:
                rconf=self.global_conf.get_repo_conf(self.repo_id)
                rconf.remove(must_be_kept)
            except Exception:
                pass

    @property
    def repo_id(self):
        return self._repo_id

    @property
    def parameters_core(self):
        """Get the list of "core" parameters, as specified in the source code (common to all configurations)"""
        return self._params_core

    @property
    def parameters_config(self):
        """Get the list of "config" parameters, as specified in the configuration itself"""
        return self._params_config

    @property
    def parameters(self):
        """Get the list of all the parameters"""
        return self._params_combined

    @property
    def overrides(self):
        """Get the values of parameters which are overriden by the configuration (and can thus not be changed
        by the admin)"""
        return self._overrides

    @property
    def devicemeta_pubkey(self):
        """Full path of the file containing the public key to verify the signnature of the device's metadata"""
        return "%s/%s"%(self.config_dir, self._devicemeta_pubkey)

    @property
    def devicemeta_privkey(self):
        """Full path of the file containing the private key to sign the device's metadata"""
        return "%s/%s"%(self.config_dir, self._devicemeta_privkey)

    @property
    def password_rescue(self):
        return self._password_rescue

    def _parse(self, data):
        if not isinstance(data, dict):
            raise Exception("Invalid configuration: not a dictionary")
        specs={
            "id": [str, False, True],
            "descr": [str, False, True],
            "repo": [str, True, True],
            "parameters": [dict, True, True],
            "dev-format": [dict, False, True],
            "devicemeta-skey-priv-file": [str, False, True],
            "devicemeta-skey-pub-file": [str, False, True],
            "password-rescue": [str, False, True]
        }
        try:
            _validate_attributes(data, specs)
            params=data["parameters"]
            for pname in params:
                _validate_parameter_definition(params[pname])
        except Exception as e:
            raise Exception(_(f"Invalid format configuration '{self.config_file}': {str(e)}"))

        # top level information
        self._id=data["id"]
        self._repo_id=data["repo"]
        self._devicemeta_pubkey=data["devicemeta-skey-pub-file"]
        self._devicemeta_privkey=data["devicemeta-skey-priv-file"]
        self._password_rescue=data["password-rescue"]
        self._userdata={}
        if "userdata" in data:
            self._userdata=data["userdata"]

        # load the core configuration which contains the hard coded parts of any format configuration
        # and which needs to be "merged" (or combined) with the parts provided by the format configurations'
        # the user defined
        core_conf=json.load(open("%s/core-format-config.json"%os.path.dirname(__file__), "r"))

        # merge the configuration with the core configuration: parameters
        self._params_core=core_conf["parameters"]
        self._params_config=data["parameters"]
        self._params_combined=self._params_core.copy()
        for param in self._params_config:
            if param in self._params_core:
                raise Exception(_("Invalid parameter '%s': already part of core configuration")%param)
            self._params_combined[param]=self._params_config[param]

        # merge the configuration with the core configuration: dev-format
        conf_dev_format=data["dev-format"]
        dev_fmt=core_conf["dev-format"]
        for section in ("unprotected", "protected", "decryptors", "signatures"):
            if section in conf_dev_format:
                for entry in conf_dev_format[section]:
                    if entry in dev_fmt[section]:
                        raise Exception(_(f"Invalid configuration entry '{entry}' in section '{section}': already part of core configuration"))
                    dev_fmt[section][entry]=conf_dev_format[section][entry]

        # add any partition specified in the format configuration to the already existing one in the core-format-config.json file
        if "partitions" in data["dev-format"]:
            dev_fmt["partitions"]=data["dev-format"]["partitions"]+dev_fmt["partitions"]
        self._dev_format=dev_fmt

        # compute overrides
        self._overrides={}
        if "override" in data["dev-format"]:
            self._overrides=data["dev-format"]["override"].copy()

        #print("SPEC: %s"%json.dumps(data, indent=4))
        self._data=data

    def export_complete_configuration(self):
        """Export the merged (complete) configuration as a struture, ready to be used"""
        exp=self._data.copy()
        exp["parameters"]=self._params_combined
        exp["dev-format"]=self._dev_format
        return exp

    def _compute_status(self):
        warnings=[]
        errors=[]
        todo=[]

        # associated repo
        archive_ts=0
        if self.repo_id is None:
            errors.append(_("No associated repository configuration"))
        else:
            rconf=self.global_conf.get_repo_conf(self.repo_id, exception_if_not_found=False)
            if rconf is None:
                errors.append(_(f"Inexistant referenced repository '{self.repo_id}'"))
            else:
                if rconf.type!=RepoType.FORMAT:
                    errors.append(_("Referenced repository is not of type FORMAT"))
                else:
                    # get timestamp of the last published archive
                    (archive_ts, dummy)=rconf.get_latest_archive()

        # todo
        files_ts=get_last_file_modification_ts(self.config_dir)
        if archive_ts<files_ts:
            todo.append(_("needs to be published"))

        self._status=ConfigStatus(len(errors)==0, warnings, errors, todo)

#
# Domain configurations
#
class DomainConfig(ConfigInterface):
    """Represents a domain configuration"""
    def __init__(self, global_conf:GlobalConfiguration, configfile:str):
        super().__init__(global_conf, configfile)
        try:
            self._parse(json.load(open(configfile, "r")))
        except Exception as e:
            raise Exception(_(f"Invalid file '{configfile}' format: {str(e)}"))
        self._status=None

    @property
    def id(self):
        return self._id

    @property
    def descr(self):
        return self._descr

    @property
    def status(self) -> ConfigStatus:
        if self._status is None:
            self._compute_status()
        return self._status

    def get_referenced_configurations(self) -> list[ConfigInterface]:
        conf=self.global_conf.get_repo_conf(self.repo_id)
        res=[conf]
        for confid in self.install_ids + self.format_ids:
            conf=self.global_conf.get_any_conf(confid)
            res.append(conf)
        return res

    def _create_new(global_conf:GlobalConfiguration, descr:str, ruid:str) -> str:
        conf_file=identify_free_filename(global_conf.path+"/domain-configurations", "domain", ".json")
        duid=f"domain-{str(uuid.uuid4())}"
        if ruid is None:
            ruid=RepoConfig.create_new(global_conf, f"Repository for domain '{descr}'", RepoType.DOMAIN)

        repl={
            "descr": descr,
            "domain": duid,
            "repo": ruid
        }
        res_path=os.path.join(os.path.dirname(__file__), "../tools/resources")
        data=util.load_file_contents("%s/template-domain.json"%(res_path))
        data=ValueHolder.replace_variables(data, repl)
        os.makedirs(os.path.dirname(conf_file), exist_ok=True)
        util.write_data_to_file(data, conf_file)
        return duid

    def create_new(global_conf:GlobalConfiguration, descr:str, subtype=None, extra=None) -> str:
        return DomainConfig._create_new(global_conf, descr, None)

    def clone(self, other_global_conf:GlobalConfiguration, descr:str, map:dict[ConfigInterface, str]=None) -> str:
        gconf=self.global_conf if other_global_conf is None else other_global_conf
        if map is None:
            map={}

        try:
            cloned=None
            gconf2=None

            # clone the repository
            rconf=self.global_conf.get_repo_conf(self.repo_id)
            nruid=rconf.clone(gconf, f"Repository for domain '{descr}'", map)

            # create a new domain config
            nuid=DomainConfig._create_new(gconf, descr, nruid)

            # copy components using a new GlobalConfiguration object
            gconf2=GlobalConfiguration(gconf.path)
            cloned=gconf2.get_domain_conf(nuid)
            data=json.loads(util.load_file_contents(cloned.config_file))
            data["install"]=self._install_ids
            data["format"]=self._format_ids
            util.write_data_to_file(json.dumps(data, indent=4), cloned.config_file)

            map[self]=nuid
            map[rconf]=nruid
            return nuid
        except Exception as e:
            try:
                if gconf2 is None:
                    gconf2=GlobalConfiguration(gconf.path)
                rconf=gconf2.get_any_conf(nruid)
                rconf.remove()
            except:
                pass
            if cloned is not None:
                cloned.remove()
            raise e

    def remove(self, must_be_kept:list[str]=None):
        tokeep=[] if must_be_kept is None else must_be_kept

        if self not in tokeep:
            os.remove(self.config_file)
            try:
                rconf=self.global_conf.get_repo_conf(self.repo_id)
                rconf.remove(must_be_kept)
            except Exception:
                pass

    @property
    def repo_id(self):
        return self._repo_id

    @property
    def install_ids(self):
        """Get the list of install configurations in the domain"""
        return self._install_ids

    @property
    def format_ids(self):
        """Get the list of format configurations in the domain"""
        return self._format_ids

    def _parse(self, data):
        if not isinstance(data, dict):
            raise Exception("Invalid configuration: not a dictionary")
        specs={
            "id": [str, False, True],    
            "descr": [str, False, True],
            "repo": [str, True, True],
            "install": [list, False, True],
            "format": [list, False, True]
        }
        try:
            _validate_attributes(data, specs)
        except Exception as e:
            raise Exception("Invalid live configuration '%s': %s"%(self.config_file, str(e)))
        self._id=data["id"]
        self._descr=data["descr"]
        self._repo_id=data["repo"]
        self._install_ids=data["install"]
        self._format_ids=data["format"]

    def _compute_status(self):
        warnings=[]
        errors=[]
        todo=[]

        # associated repo
        archive_ts=0
        if self.repo_id is None:
            errors.append(_("No associated repository configuration"))
        else:
            rconf=self.global_conf.get_repo_conf(self.repo_id, exception_if_not_found=False)
            if rconf is None:
                errors.append(_(f"Inexistant referenced repository '{self.repo_id}'"))
            else:
                if rconf.type!=RepoType.DOMAIN:
                    errors.append(_("Referenced repository is not of type DOMAIN"))
                else:
                    try:
                        # get timestamp of the last published archive
                        (archive_ts, dummy)=rconf.get_latest_archive()
                    except Exception as e:
                        errors.append(_(f"Could not get last archive: {str(e)}"))

        # referenced install configs.
        for uid in self.install_ids:
            conf=self.global_conf.get_install_conf(uid, exception_if_not_found=False)
            if conf is None:
                errors.append(_(f"Inexistant referenced install configuration '{uid}'"))

        # referenced format configs.
        for uid in self.format_ids:
            conf=self.global_conf.get_format_conf(uid, exception_if_not_found=False)
            if conf is None:
                errors.append(_(f"Inexistant referenced format configuration '{uid}'"))

        # todo
        files_ts=get_last_file_modification_ts(self.config_dir)
        if self.global_conf.proxy_pac_file is not None:
            pts=get_last_file_modification_ts(self.global_conf.proxy_pac_file)
            if pts>files_ts:
                files_ts=pts
        if archive_ts<files_ts:
            todo.append(_("needs to be published"))

        self._status=ConfigStatus(len(errors)==0, warnings, errors, todo)

#
# Repositories configurations
#
class RepoType(str, enum.Enum):
    """Different types of repositories"""
    BUILD="build"
    INSTALL="install"
    FORMAT="format"
    DOMAIN="domain"
    USERDATA="userdata"

class RepoConfig(ConfigInterface):
    """Represents a repository configuration"""
    def __init__(self, global_conf:GlobalConfiguration, configfile:str):
        super().__init__(global_conf, configfile)
        self._borg_repo=None
        try:
            self._parse(json.load(open(configfile, "r")))
        except Exception as e:
            err=str(e)
            raise Exception(_(f"Invalid file '{configfile}' format: {err}"))

        self._status=None

    def __del__(self):
        if self._borg_repo:
            self._borg_repo.umount_all()

    @property
    def id(self):
        return self._id

    @property
    def descr(self):
        return self._descr

    @property
    def repo_id(self):
        return None

    @property
    def status(self) -> ConfigStatus:
        if self._status is None:
            self._compute_status()
        return self._status

    def get_referenced_configurations(self) -> list[ConfigInterface]:
        # repositories don't reference any other configuration
        return []

    @classmethod
    def _identify_free_repo_path(cls, global_conf:GlobalConfiguration) -> tuple(str, str):
        if "INSECA_DEFAULT_REPOS_DIR" in os.environ:
            base_repo_data_path=os.environ["INSECA_DEFAULT_REPOS_DIR"]
        else:
            base_repo_data_path=f"{global_conf.path}/repos"
        base_repo_data_path=os.path.realpath(base_repo_data_path)
        index=0
        while True:
            name=f"repo.{index}"
            path1=f"{global_conf.path}/repo-configurations/{name}.json"
            path2=f"{base_repo_data_path}/{name}"
            if not os.path.exists(path1) and not os.path.exists(path2):
                return (path2, name)
            index+=1

    def create_new(global_conf:GlobalConfiguration, descr:str, subtype=None, extra=None) -> str:
        if subtype is None:
            raise Exception(f"No repository sub type specified")
        if not isinstance(subtype, RepoType):
            raise Exception(f"Invalid repository sub type '{subtype}'")

        # identify an available repo name and its data path
        (repo_data_path, name)=RepoConfig._identify_free_repo_path(global_conf)

        # preparations
        repo_conf_path=f"{global_conf.path}/repo-configurations/{name}.json"
        if os.path.exists(repo_conf_path):
            raise Exception(f"Repo configuration path '{repo_conf_path}' already exists")

        # create Borg repo
        borg_repo=borg.Repo(repo_data_path, None)
        password=borg_repo.init()
        
        # generate config template
        ruid=f"repo-{str(uuid.uuid4())}"
        conf={
            "id": ruid,
            "type": subtype.value,
            "descr": descr,
            "path": repo_data_path,
            "password": password,
            "compress": subtype!=RepoType.BUILD
        }
        util.write_data_to_file(json.dumps(conf, indent=4), repo_conf_path)
        return ruid

    def clone(self, other_global_conf:GlobalConfiguration, descr:str, map:dict[ConfigInterface, str]=None) -> str:
        # The cloning of a repo configuration actually copy all the ressources from the original repo and adapt the ID, while chaning the password
        gconf=self.global_conf if other_global_conf is None else other_global_conf
        if map is None:
            map={}

        # generate config template & elements
        gconf=other_global_conf if other_global_conf is not None else self.global_conf
        nuid=f"repo-{str(uuid.uuid4())}"
        password=cgen.generate_password()
        (repo_data_path, name)=RepoConfig._identify_free_repo_path(gconf)
        repo_conf_path=f"{gconf.path}/repo-configurations/{name}.json"
        if os.path.exists(repo_conf_path):
            raise Exception(f"Repo configuration path '{repo_conf_path}' already exists")
        conf={
            "id": nuid,
            "type": self.type.value,
            "descr": descr if descr is not None else self.descr,
            "path": repo_data_path,
            "password": password,
            "compress": self.compress
        }

        # copy repo's contents
        try:
            shutil.copytree(self.path, repo_data_path)

            # change password
            borg_repo=borg.Repo(repo_data_path, self.password)
            borg_repo.change_password(password)
            borg_repo.generate_new_id()

            # record new repo. configuration
            util.write_data_to_file(json.dumps(conf, indent=4), repo_conf_path)
            map[self]=nuid
            return nuid
        except Exception as e:
            shutil.rmtree(repo_data_path, ignore_errors=True)
            os.remove(repo_conf_path)
            raise e

    def remove(self, must_be_kept:list[str]=None):
        tokeep=[] if must_be_kept is None else must_be_kept

        if self not in tokeep:
            shutil.rmtree(self.path, ignore_errors=True)
            os.remove(self.config_file)

    @property
    def archives_cache_dir(self):
        return "%s/%s"%(self.global_conf.archives_cache_dir, self._id)

    @property
    def type(self):
        return self._type

    @property
    def path(self):
        return self._path

    @path.setter
    def path(self, path):
        """Set the path, should be done by the GlobalConfiguration object if the path is not already a full path"""
        if os.path.isabs(self.path):
            raise Exception("CODEBUG: path is already an absolute path, should not be changed")
        self._path=path

    @property
    def used_space(self):
        (status, out, err)=util.exec_sync(["du", "-sh", self.path])
        if status!=0:
            raise Exception(_(f"Could not get actual size of '{self.path}': {err}"))
        return out.split()[0]

    @property
    def password(self):
        return self._password
    
    @property
    def compress(self):
        return self._compress

    @property
    def borg_repo(self):
        """Get the associated Borg repository object"""
        if self._borg_repo is None:
            if self.global_conf.is_master:
                config_dir="%s/.borg/config"%self.global_conf.path
                cache_dir="%s/.borg/cache"%self.global_conf.path
            else:
                config_dir=None
                cache_dir=None
            self._borg_repo=borg.Repo(self.path, self.password, config_dir, cache_dir)
        return self._borg_repo

    def _parse(self, data):
        if not isinstance(data, dict):
            raise Exception(_("Invalid configuration: not a dictionary"))
        specs={
            "id": [str, False, True],
            "type": [str, False, True],
            "descr": [str, True, True],
            "path": [str, False, True],
            "password": [str, False, True],
            "compress": [bool, True, True]
        }
        try:
            _validate_attributes(data, specs)
        except Exception as e:
            raise Exception(_(f"Invalid repo configuration '{self.config_file}': {str(e)}"))
        self._id=data["id"]
        datapath=data["path"]
        if not os.path.isabs(datapath):
            if "INSECA_DEFAULT_REPOS_DIR" in os.environ:
                datapath=f"{os.environ['INSECA_DEFAULT_REPOS_DIR']}/{datapath}"
            else:
                datapath=f"{self.global_conf.path}/{datapath}"

        try:
            self._type=RepoType(data["type"])
        except Exception:
            raise Exception(_(f"Invalid repo configuration '{self.config_file}': invalid type '{self._type}'"))
        self._password=data["password"]
        self._compress=data["compress"]
        self._path=datapath
        self._descr=data["descr"]

    def get_borg_exec_env(self):
        return self.borg_repo.get_exec_env()

    def get_all_archives(self):
        """Get a list of all the archives as a dictionary indexed by the timestamp the archive was created
        and where values are the associated archives' name"""
        return self.borg_repo.get_all_archives()

    def get_latest_archive(self):
        """Get the most recent archive in the specified repository
        Returns a (ts, archive name) tuple"""
        return self.borg_repo.get_latest_archive()

    def archive_exists(self, archive_name):
        """Tells if a specific archive is in the repository"""
        return self.borg_repo.archive_exists(archive_name)

    def mount(self, archive_name):
        """Mounts the specified archive somewhere and returns the mount point"""
        return self.borg_repo.mount(archive_name)

    def umount(self, archive_name):
        """Unmounts the specified archive"""
        self.borg_repo.umount(archive_name)

    def umount_all(self):
        """Unmounts all the mounted archives"""
        self.borg_repo.umount_all()

    def extract_archive(self, archive_name, destdir):
        """Extract the whole contents of the specified archive in @destdir (which must already exist)"""
        self.borg_repo.extract_archive(archive_name, destdir)

    def cache_last_archive(self):
        """Ensures that the contents of the latest archive is present in @destdir
        For that purpose, a .<last archive name> file is also created in the @destdir directory"""
        shortcut="%s/last-archive"%self.archives_cache_dir
        (ts, lastarname)=self.get_latest_archive()
        if lastarname is not None:
            destdir="%s/%s"%(self.archives_cache_dir, lastarname)
            if not os.path.exists(destdir):
                # last archive has not been extracted
                tmpdest="%s.tmp"%destdir
                if os.path.exists(tmpdest):
                    shutil.rmtree(tmpdest)
                try:
                    # extract archive
                    os.makedirs(tmpdest, mode=0o700)
                    self.extract_archive(lastarname, tmpdest)
                    os.rename(tmpdest, destdir)

                    # add shortcut link
                    if os.path.exists(shortcut):
                        os.remove(shortcut)
                    os.symlink(lastarname, shortcut)
                except Exception as e:
                    shutil.rmtree(tmpdest, ignore_errors=True)
                    raise e

            # remove old archives if any
            if os.path.exists(self.archives_cache_dir):
                for fname in os.listdir(self.archives_cache_dir):
                    path="%s/%s"%(self.archives_cache_dir, fname)
                    if fname!=lastarname and os.path.isdir(path):
                        shutil.rmtree(path, ignore_errors=True)
                if len(os.listdir(self.archives_cache_dir))==1:
                    if os.path.exists(shortcut):
                        os.remove(shortcut)

    def get_archive_dir_from_cache(self, arname):
        """Get the absolute path to a cached (already extracted) archive's contents"""
        try:
            path="%s/%s"%(self.archives_cache_dir, arname)
            if os.path.isdir(path):
                return path
        except:
            pass
        return None

    def export(self, new_path=None):
        """Exports the configuration as a structure, optionaly defining a new path for the repository"""
        return {
            "id": self.id,
            "type": self.type,
            "descr": self.descr,
            "path": new_path if new_path is not None else self.path,
            "password": self.password,
            "compress": self.compress
        }

    def _compute_status(self):
        warnings=[]
        errors=[]

        if not os.path.isdir(self.path):
            errors.append(_(f"Actual data path {self.path} does not exist or is not a directory"))
        else:
            try:
                self.borg_repo.check()
            except Exception as e:
                errors.append(f"Repository error: {str(e)}")

        self._status=ConfigStatus(len(errors)==0, warnings, errors, [])

#
# Global configuration
#
def init_root_config():
        """Creates the initial structure of an INSECA global configuration"""
        if "INSECA_ROOT" not in os.environ:
            raise Exception("No root directory specified (to contain all the INSECA configuration)")
        root=os.environ["INSECA_ROOT"]
        if os.path.exists(root) and len(os.listdir(root))>0:
            raise Exception(_("Root directory '%s' is not empty")%root)
        else:
            os.makedirs(root, exist_ok=True)

        # top directories
        for dir in ("build-configurations", "install-configurations",
                    "format-configurations", "repos", "repo-configurations",
                    "domain-configurations", "storage-credentials",
                    "blobs", "blobs/generic", "components"):
            path="%s/%s"%(root, dir)
            os.makedirs(path)

        # directories to store blobs per component providing the "base-os" feature
        script_dir=os.path.dirname(os.path.realpath(os.path.dirname(sys.argv[0])))
        for component in os.listdir(f"{script_dir}/components"):
            comp_conf=f"{script_dir}/components/{component}/config.json"
            if os.path.exists(comp_conf):
                cdata=json.load(open(comp_conf, "r"))
                if "base-os" in cdata["provides"]:
                    os.makedirs(f"{root}/blobs/{component}")

        # conf
        conf={"deploy": {
            "cloud": {},
            "local": {}
        }}
        util.write_data_to_file(json.dumps(conf, indent=4), "%s/inseca.json"%root)

def get_gconf(force_reload=False):
    """Get the last-created GlobalConfiguration object, and reload it if required
    If the configuration is not available or invalid, an exception will be raised."""
    cache=None
    if get_gconf._gconf:
        if not force_reload:
            return get_gconf._gconf
        try:
            cache=get_gconf._gconf.archives_cache_dir
        except Exception:
            pass

    get_gconf._gconf=GlobalConfiguration()
    if cache is None:
        if not get_gconf._gconf.is_master:
            if not "INSECA_DEFAULT_REPOS_DIR" in os.environ:
                raise Exception("INSECA_DEFAULT_REPOS_DIR environment variable is not defined")
            get_gconf._gconf.archives_cache_dir="%s/.archives-cache"%os.environ["INSECA_DEFAULT_REPOS_DIR"]
    else:
        get_gconf._gconf.archives_cache_dir=cache

    Sync.proxy_pac_file=get_gconf._gconf.proxy_pac_file
    return get_gconf._gconf
get_gconf._gconf=None

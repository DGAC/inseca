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
import json
import enum
import datetime
import calendar
import shutil
import sys
import Utils as util
import Filesystem
import Sync
import Borg as borg

# Gettext stuff
import gettext
lib_dir=os.path.dirname(__file__)
gettext.bindtextdomain("inseca-lib", lib_dir+"/locales")
gettext.textdomain("inseca-lib")
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
    if data["type"] not in ("str", "filesystem", "password", "timestamp", "int", "file", "size-mb"):
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

#
# Build configurations
#
class BuildType(str, enum.Enum):
    """Different types of build configurations"""
    SIMPLE="simple"
    ADMIN="admin"
    WKS="workstation"

class BuildConfig:
    """Represents a live Linux configuration"""
    def __init__(self, global_conf, configfile):
        if not isinstance(global_conf, GlobalConfiguration):
            raise Exception("CODEBUG: @global_conf should be a GlobalConfiguration object")
        self._gconf=global_conf
        self._configfile=configfile
        try:
            self._parse(json.load(open(configfile, "r")))
        except Exception as e:
            err=str(e)
            raise Exception(_(f"Invalid file '{configfile}' format: {err}"))
        self._scriptdir=os.path.realpath(os.path.dirname(sys.argv[0]))

    @property
    def id(self):
        return self._id

    @property
    def build_type(self):
        if "inseca-live-admin" in self._components:
            return BuildType.ADMIN
        if "inseca-live-wks" in self._components:
            return BuildType.WKS
        return BuildType.SIMPLE

    @property
    def descr(self):
        return self._descr

    @property
    def config_file(self):
        return self._configfile

    @property
    def config_dir(self):
        return os.path.dirname(self._configfile)

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
            fname="%s/%s"%(self.config_dir, self._components["signature"]["build-skey-pub-file"])
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
            "Windows-VM": {
                "win-image": {
                    "descr": "Windows disk image file",
                    "type": "file"
                }
            }
        }
        """
        components_path_builtin="%s/../components"%os.path.dirname(os.path.realpath(__file__))
        components_path_extra=None
        if "INSECA_EXTRA_COMPONENTS" in os.environ:
            components_path_extra=os.environ["INSECA_EXTRA_COMPONENTS"]
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
            raise Exception("Invalid live configuration '%s': %s"%(self._configfile, str(e)))
        self._id=data["id"]
        self._repo_id=data["repo"]
        self._version=data["version"]
        self._privdata_pubkey=data["privdata-ekey-pub-file"]
        self._privdata_privkey=data["privdata-ekey-priv-file"]

        now=datetime.date.today()
        month=now.month-1+int(data["validity-months"])
        year=now.year+month//12
        month=month%12+1
        day=min(now.day, calendar.monthrange(year,month)[1])
        self._valid_to=int(datetime.date(year, month, day).strftime('%s'))

        self._build_dir=data["build-dir"]
        self._components=data["components"]
        self._descr=data["descr"]

    def validate(self):
        """Check that the configuration is coherent"""
        # global check
        cdefs={} # key=component ID, value=component's configuration
        for cid in self._components:
            cpath=self.get_component_src_path(cid)
            if not os.path.exists(cpath):
                raise Exception("Component '%s' does not have any config.json configuration file"%cid)
            try:
                cdata=json.load(open(cpath+"/config.json", "r"))
            except Exception as e:
                raise Exception("Invalid or unreadable config.json configuration file for component '%s'"%cid)
            cdefs[cid]=cdata
            if "provides" not in cdata:
                raise Exception("Configuration of component '%s' is invalid: no 'provides' attribute"%cid)

        # search the 'base' and 'components-init' features
        base=None
        cinit=None
        for cid in self._components:
            cdata=cdefs[cid]
            if "base" in cdata["provides"]:
                if base:
                    raise Exception("The 'base' feature is present in more than one component")
                base=True
            if "components-init" in cdata["provides"]:
                if cinit:
                    raise Exception("The 'components-init' feature is present in more than one component")
                cinit=True
        if not base:
            raise Exception("Missing a 'base' component")
        if not cinit:
            raise Exception("Missing a 'components-init' component")

        # if build type is not WKS, then the components list should not include any component
        # which needs a USERDATA
        if self.build_type!=BuildType.WKS:
            for cid in self._components:
                cdata=cdefs[cid]
                if len (cdata["userdata"])>0:
                    raise Exception(_("Build configuration is not 'workstation' but included component '%s' requires some USERDATA")%cid)

    def get_component_src_path(self, component):
        path="%s/../components/%s"%(self._scriptdir, component)
        if os.path.exists(path):
            return path
        if "INSECA_EXTRA_COMPONENTS" in os.environ:
            path="%s/%s"%(os.environ["INSECA_EXTRA_COMPONENTS"], component)
            if os.path.exists(path):
                return path
        raise Exception("Component '%s' not found"%component)

#
# Install configurations
#
class InstallConfig:
    """Represents an installation configuration"""
    def __init__(self, global_conf, configfile):
        if not isinstance(global_conf, GlobalConfiguration):
            raise Exception("CODEBUG: @global_conf should be a GlobalConfiguration object")
        self._gconf=global_conf
        self._configfile=configfile
        self._build_id=None
        try:
            self._parse(json.load(open(configfile, "r")))
        except Exception as e:
            err=str(e)
            raise Exception(_(f"Invalid file '{configfile}' format: {err}"))

    @property
    def id(self):
        return self._id

    @property
    def descr(self):
        return self._data["descr"]

    @property
    def config_file(self):
        return self._configfile

    @property
    def config_dir(self):
        return os.path.dirname(self._configfile)

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
            "Windows-VM": {
                "win-image": "repo-f418dbc5-39bc-4065-919d-5814dd7c57e3"
            },
            "VPN-OpenVPN": {
                "ovpn-file": "repo-83f9d052-ba7f-42ad-9910-18805ab145e3"
            }
        """
        return self._userdata

    @property
    def gconf(self):
        """Get the associated GlobalConfiguration object"""
        return self._gconf

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
            config_file=self._configfile
            err=str(e)
            raise Exception(_("Invalid install configuration '{config_file}': {err}"))

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
        self._data=data

    def validate(self):
        """Check that the configuration is coherent"""
        if self.build_id:
            bconf=self._gconf.get_build_conf(self.build_id)
            if bconf.build_type!=BuildType.WKS:
                raise Exception(_("Build configuration is not of type 'workstation'"))

    def export_complete_configuration(self):
        """Export the merged (complete) configuration as a struture, ready to be used"""
        exp=self._data.copy()
        exp["parameters"]=self._params_combined
        exp["dev-format"]=self._dev_format
        return exp

#
# Format configurations
#
class FormatConfig:
    """Represents a device formatter configuration"""
    def __init__(self, global_conf, configfile):
        if not isinstance(global_conf, GlobalConfiguration):
            raise Exception("CODEBUG: @global_conf should be a GlobalConfiguration object")
        self._gconf=global_conf
        self._configfile=configfile
        self._build_id=None
        try:
            self._parse(json.load(open(configfile, "r")))
        except Exception as e:
            err=str(e)
            raise Exception(_(f"Invalid file '{configfile}' format: {err}"))

    @property
    def id(self):
        return self._id

    @property
    def descr(self):
        return self._data["descr"]

    @property
    def config_file(self):
        return self._configfile

    @property
    def config_dir(self):
        return os.path.dirname(self._configfile)

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

    @property
    def gconf(self):
        """Get the associated GlobalConfiguration object"""
        return self._gconf

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
            config_file=self._configfile
            err=str(e)
            raise Exception(_(f"Invalid format configuration '{config_file}': {err}"))

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
        self._dev_format=dev_fmt
        #print("SPEC: %s"%json.dumps(data, indent=4))
        self._data=data

    def export_complete_configuration(self):
        """Export the merged (complete) configuration as a struture, ready to be used"""
        exp=self._data.copy()
        exp["parameters"]=self._params_combined
        exp["dev-format"]=self._dev_format
        #print("export_complete_configuration: %s"%json.dumps(exp, indent=4))
        return exp

#
# Domain configurations
#
class DomainConfig:
    """Represents a domain configuration"""
    def __init__(self, global_conf, configfile):
        if not isinstance(global_conf, GlobalConfiguration):
            raise Exception("CODEBUG: @global_conf should be a GlobalConfiguration object")
        self._gconf=global_conf
        self._configfile=configfile
        try:
            self._parse(json.load(open(configfile, "r")))
        except Exception as e:
            err=str(e)
            raise Exception(_(f"Invalid file '{configfile}' format: {err}"))

    @property
    def id(self):
        return self._id

    @property
    def descr(self):
        return self._descr

    @property
    def config_file(self):
        return self._configfile

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
            raise Exception("Invalid live configuration '%s': %s"%(self._configfile, str(e)))
        self._id=data["id"]
        self._descr=data["descr"]
        self._repo_id=data["repo"]
        self._install_ids=data["install"]
        self._format_ids=data["format"]

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

class RepoConfig:
    """Represents a repository configuration"""
    def __init__(self, global_conf, configfile):
        if not isinstance(global_conf, GlobalConfiguration):
            raise Exception("CODEBUG: @global_conf should be a GlobalConfiguration object")
        self._gconf=global_conf
        self._configfile=configfile
        self._borg_repo=None
        try:
            self._parse(json.load(open(configfile, "r")))
        except Exception as e:
            err=str(e)
            raise Exception(_(f"Invalid file '{configfile}' format: {err}"))

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
    def config_file(self):
        return self._configfile

    @property
    def config_dir(self):
        return os.path.dirname(self._configfile)

    @property
    def archives_cache_dir(self):
        return "%s/%s"%(self._gconf.archives_cache_dir, self._id)

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
        if self._borg_repo is None:
            if self._gconf.is_master:
                config_dir="%s/.borg/config"%self._gconf.path
                cache_dir="%s/.borg/cache"%self._gconf.path
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
            config_file=self._configfile
            err=str(e)
            raise Exception(_(f"Invalid repo configuration '{config_file}': {err}"))
        self._id=data["id"]
        if os.path.isabs(data["path"]) and not os.path.exists(data["path"]):
            config_file=self._configfile
            path=data["path"]
            raise Exception(_(f"Invalid repo configuration '{config_file}': path '{path}' does not exist"))
        try:
            self._type=RepoType(data["type"])
        except Exception:
            config_file=self._configfile
            raise Exception(_(f"Invalid repo configuration '{config_file}': invalid type '{self._type}'"))
        self._password=data["password"]
        self._compress=data["compress"]
        self._path=data["path"]
        self._descr=data["descr"]

    def get_borg_exec_env(self):
        return self.borg_repo.get_exec_env()

    def is_locked(self):
        """Tell if the repository is locked by Borg (i.e. another process is using it or there is a stale lock)"""
        return self.borg_repo.is_locked()

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

    def remove(self):
        """Remove all information about the repository:
        - the configuration
        - the data
        - the cached archives
        """
        os.remove(self.config_file)
        shutil.rmtree(self.path)
        shutil.rmtree(self.archives_cache_dir)

#
# Global configuration
#
class GlobalConfiguration:
    """Represents a global INSECA configuration.
    Creating a new object allows one to take into account an updated configuration"""
    def init_root_config():
        """Creates the initial structure of an INSECA global configuration"""
        if "INSECA_ROOT" not in os.environ:
            raise Exception("No root directory specified (to contain all the INSECA configuration)")
        root=os.environ["INSECA_ROOT"]
        if os.path.exists(root) and len(os.listdir(root))>0:
            raise Exception(_("Root directory '%s' is not empty")%root)
        else:
            os.makedirs(root, exist_ok=True)

        # directories
        for dir in ("build-configurations", "install-configurations",
                    "format-configurations", "repos", "repo-configurations",
                    "domain-configurations", "storage-credentials"):
            path="%s/%s"%(root, dir)
            os.makedirs(path)

        # conf
        conf={"deploy": {
            "cloud": {},
            "local": {}
        }}
        util.write_data_to_file(json.dumps(conf, indent=4), "%s/inseca.json"%root)

    def __init__(self, path=None):
        if path is None:
            if not "INSECA_ROOT" in os.environ:
                raise Exception(_("INSECA_ROOT environment variable is not defined"))
            path=os.environ["INSECA_ROOT"]
            if not os.path.isdir(path):
                raise Exception(_("Directory '%s' pointed by INSECA_ROOT environment variable does not exist")%path)
        self._path=os.path.realpath(path)

        # Check that the top level directories are present
        for fname in ("install-configurations", "format-configurations", "repo-configurations", "domain-configurations"):
            fpath="%s/%s"%(self._path, fname)
            if not os.path.exists(fpath):
                raise Exception(_("Top directory '%s' is missing")%fname)
            if not os.path.isdir(fpath):
                raise Exception(_("'%s' should be a directory")%fname)

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

        self._check_coherence()

        self._archives_cache_dir=None # must be defined before use, no default value
        if not self.is_master:
            if "INSECA_CACHE_DIR" in os.environ:
                self.archives_cache_dir=os.environ["INSECA_CACHE_DIR"]

    @property
    def path(self):
        """Points to the path of the global configuration (i.e. $INSECA_ROOT)"""
        return self._path

    def get_relative_path(self, path):
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
        return list(self._build_configs.keys())

    @property
    def install_configs(self):
        return list(self._install_configs.keys())

    @property
    def format_configs(self):
        return list(self._format_configs.keys())

    @property
    def domain_configs(self):
        return list(self._domain_configs.keys())

    @property
    def repo_configs(self):
        return list(self._repo_configs.keys())

    @property
    def proxy_pac_file(self):
        return self._proxy_pac_file

    @property
    def is_master(self):
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
        if way_out:
            name="W"+target
        else:
            name="R"+target
        if name in self._sync_configs:
            return self._sync_configs[name]
        raise Exception(_("Unknown synchronization target '%s'")%target)

    def get_all_sync_objects(self, way_out):
        """Get all the sync. targets for the specified type (see get_target_sync_object())"""
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
                if conf.id in self._all_conf_ids:
                    path=self.get_relative_path(cfile)
                    raise Exception(_(f"Build configuration '{conf.id}' already exists (from '{path}')"))
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
                if conf.id in self._all_conf_ids:
                    path=self.get_relative_path(cfile)
                    raise Exception(_(f"Install configuration '{conf.id}' already exists (from '{path}')"))
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
            if conf.id in self._all_conf_ids:
                path=self.get_relative_path(cfile)
                raise Exception(_(f"Format configuration '{conf.id}' already exists (from '{path}')"))
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
            if conf.id in self._all_conf_ids:
                path=self.get_relative_path(cfile)
                raise Exception(_(f"Install configuration '{conf.id}' already exists (from '{path}')"))
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
                    path=self.get_relative_path(cpath)
                    raise Exception(_(f"Repository configuration '{conf.id}' already exists (from '{path}')"))
                if not os.path.isabs(conf.path):
                    if "INSECA_DEFAULT_REPOS_DIR" in os.environ:
                        conf.path="%s/%s"%(os.environ["INSECA_DEFAULT_REPOS_DIR"], conf.path)
                    else:
                        conf.path="%s/repos/%s"%(self.path, conf.path)
                self._repo_configs[conf.id]=conf
                self._all_conf_ids+=[conf.id]

    def _check_coherence(self):
        # checking install configs
        for iid in self._install_configs:
            iconf=self._install_configs[iid]
            if iconf.build_id is not None:
                if iconf.build_id not in self._build_configs:
                    path=self.get_relative_path(iconf.config_file)
                    raise Exception(_(f"Install configuration '' references inexistant build ID '{iconf.build_id}'"))
                bconf=self.get_build_conf(iconf.build_id)
                if bconf.repo_id is None:
                    path=self.get_relative_path(iconf.config_file)
                    raise Exception(_(f"Install configuration '{path}' references live Linux build configuration which has no associated repository"))

            if iconf.build_repo_id not in self._repo_configs:
                path=self.get_relative_path(iconf.config_file)
                raise Exception(_(f"Install configuration '{path}' references inexistant build repository 'iconf.build_repo_id'"))
            rconf=self._repo_configs[iconf.build_repo_id]
            if rconf.type!=RepoType.BUILD:
                path=self.get_relative_path(iconf.config_file)
                raise Exception(_(f"Install configuration '{path}' references build repo ID '{iconf.build_repo_id}' which is not of type BUILD"))

            if iconf.repo_id is not None:
                if not iconf.repo_id in self._repo_configs:
                    path=self.get_relative_path(iconf.config_file)
                    raise Exception(_(f"Install configuration '{path}' references inexistant repo ID '{iconf.repo_id}'"))
                rconf=self._repo_configs[iconf.repo_id]
                if rconf.type!=RepoType.INSTALL:
                    raise Exception(_("Install configuration '%s' references repo ID which is not of type INSTALL")%
                                    self.get_relative_path(iconf.config_file))

        # checking format configs
        for iid in self._format_configs:
            fconf=self._format_configs[iid]
            if fconf.repo_id is not None:
                if fconf.repo_id not in self._repo_configs:
                    path=self.get_relative_path(fconf.config_file)
                    raise Exception(_(f"Format configuration '{path}' references inexistant repo ID '{fconf.repo_id}'"))
                rconf=self._repo_configs[fconf.repo_id]
                if rconf.type!=RepoType.FORMAT:
                    raise Exception(_("Format configuration '%s' references repo ID which is not of type FORMAT")%
                                    self.get_relative_path(fconf.config_file))

        # checking build configs
        for iid in self._build_configs:
            bconf=self._build_configs[iid]
            if bconf.repo_id is not None:
                if bconf.repo_id not in self._repo_configs:
                    path=self.get_relative_path(bconf.config_file)
                    raise Exception(_(f"Build configuration '{path}' references inexistant repo ID '{bconf.repo_id}'"))
                rconf=self._repo_configs[bconf.repo_id]
                if rconf.type!=RepoType.BUILD:
                    raise Exception(_("Build configuration '%s' references repo ID which is not of type BUILD")%
                                    self.get_relative_path(bconf.config_file))

        # check domain configs
        for duid in self._domain_configs:
            dconf=self._domain_configs[duid]
            if dconf.repo_id not in self._repo_configs:
                path=self.get_relative_path(dconf.config_file)
                raise Exception(_(f"Domain configuration '{path}' references inexistant repo ID '{dconf.repo_id}'"))
            rconf=self._repo_configs[dconf.repo_id]
            if rconf.type!=RepoType.DOMAIN:
                path=self.get_relative_path(dconf.config_file)
                raise Exception(_(f"Domain configuration '{path}' references domain repo ID '{dconf.repo_id}' which is not of type DOMAIN"))
            for iuid in dconf.install_ids:
                if iuid not in self._install_configs:
                    raise Exception(_("Invalid 'install-ref' part in domain configuration: references unknown install configuration '%s'")%iuid)

        # check userdata coherence in install configs
        # TODO

    def get_build_conf(self, build_conf, exception_if_not_found=True):
        """Get a build config. object from its ID or actual config file path,
        or its description (or part of it)"""
        if build_conf in self._build_configs:
            return self._build_configs[build_conf]

        # interpret @build_conf as a path
        rpath=os.path.realpath(build_conf)
        if os.path.exists(rpath):
            for uid in self._build_configs:
                if self._build_configs[uid].config_file==rpath:
                    return self._build_configs[uid]

        # interpret @build conf as description
        lc=build_conf.lower()
        res=None
        for uid in self._build_configs:
            conf=self._build_configs[uid]
            if lc in conf.descr.lower():
                if res:
                    raise Exception(_("More than one matching configuration"))
                else:
                    res=conf
        if res:
            return res

        if exception_if_not_found:
            raise Exception(_("Unknown build configuration '%s'")%build_conf)
        return None

    def get_install_conf(self, install_conf, exception_if_not_found=True):
        """Get an install config. object from its ID or actual config file path,
        or its description (or part of it)"""
        if install_conf in self._install_configs:
            return self._install_configs[install_conf]

        # interpret @install_conf as a path
        rpath=os.path.realpath(install_conf)
        if os.path.exists(rpath):
            for uid in self._install_configs:
                if self._install_configs[uid].config_file==rpath:
                    return self._install_configs[uid]
    
        # interpret @install_conf as description
        lc=install_conf.lower()
        res=None
        for uid in self._install_configs:
            conf=self._install_configs[uid]
            if lc in conf.descr.lower():
                if res:
                    raise Exception(_("More than one matching configuration"))
                else:
                    res=conf
        if res:
            return res

        if exception_if_not_found:
            raise Exception(_("Unknown install configuration '%s'")%install_conf)
        return None

    def get_format_conf(self, format_conf, exception_if_not_found=True):
        """Get a format config. object from its ID or actual config file path
        or its description (or part of it)"""
        if format_conf in self._format_configs:
            return self._format_configs[format_conf]

        # interpret @format_conf as a path
        rpath=os.path.realpath(format_conf)
        if os.path.exists(rpath):
            for uid in self._format_configs:
                if self._format_configs[uid].config_file==rpath:
                    return self._format_configs[uid]

        # interpret @format_conf as description
        lc=format_conf.lower()
        res=None
        for uid in self._format_configs:
            conf=self._format_configs[uid]
            if lc in conf.descr.lower():
                if res:
                    raise Exception(_("More than one matching configuration"))
                else:
                    res=conf
        if res:
            return res

        if exception_if_not_found:
            raise Exception(_("Unknown format configuration '%s'")%format_conf)
        return None

    def get_domain_conf(self, domain_conf, exception_if_not_found=True):
        """Get an install config. object from its ID or actual config file path
        or its description (or part of it)"""
        if domain_conf in self._domain_configs:
            return self._domain_configs[domain_conf]

        # interpret @domain_conf as a path
        rpath=os.path.realpath(domain_conf)
        if os.path.exists(rpath):
            for uid in self._domain_configs:
                if self._domain_configs[uid].config_file==rpath:
                    return self._domain_configs[uid]

        # interpret @domain_conf as description
        lc=domain_conf.lower()
        res=None
        for uid in self._domain_configs:
            conf=self._domain_configs[uid]
            if lc in conf.descr.lower():
                if res:
                    raise Exception(_("More than one matching configuration"))
                else:
                    res=conf
        if res:
            return res

        if exception_if_not_found:
            raise Exception(_("Unknown domain configuration '%s'")%domain_conf)
        return None

    def get_repo_conf(self, repo_conf, exception_if_not_found=True):
        """Get a repo config. object from its ID or actual config file path"""
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

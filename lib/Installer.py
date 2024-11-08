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

#
# This file contains all the functions to:
# - create an INSECA install or update its live Linux
# - format a device
#

import os
import json
import uuid
import tarfile
import tempfile
import shutil
import Utils as util
import CryptoGen as cgen
import CryptoPass as cpass
import CryptoX509 as x509
import PartitionEncryption as enc
import SpecBuilder
import Device
import Live
import FingerprintChunks as fpchunks
import ValueHolder as valh
import Configurations as confs

import gettext
lib_dir=os.path.realpath(os.path.dirname(__file__))
locales_dir=f"{os.path.dirname(lib_dir)}/locales"
gettext.bindtextdomain("inseca", locales_dir)
gettext.textdomain("inseca")
_ = gettext.gettext

_debug=False

def get_userdata_file_real_path(iconf, component, name, value):
    """Returns the real path to a 'file' userdata resource:
    """
    if value is None:
        return None
    if not os.path.isabs(value):
        # mount the USERDATA repo in which the file is supposed to be
        userdata=iconf.userdata
        found=False
        if userdata and component in userdata and name in userdata[component]:
            uvalue=userdata[component][name]
            gconf=confs.get_gconf()
            rconf=gconf.get_repo_conf(uvalue, exception_if_not_found=False)
            if rconf is None:
                raise Exception("Misconfigured installation configuration for component '%s' and parameter '%s': value '%s' is not a repository"%
                                (component, name, uvalue))
            (ts, lastarname)=rconf.get_latest_archive()
            if lastarname is None:
                raise Exception("No archive available in repository '%s' for component '%s' and parameter '%s'"%(value, component, name))
            mp=rconf.get_archive_dir_from_cache(lastarname)
            if not mp:
                mp=rconf.mount(lastarname)
            nvalue="%s/%s"%(mp, value)
            if os.path.isfile(nvalue):
                found=True
                value=nvalue
            else:
                raise Exception("No file named '%s' for component '%s' and parameter '%s'"%(value, component, name))
        if not found:
            raise Exception("Misconfigured installation configuration: 'userdata' section required for component '%s' and parameter '%s'"%
                            (component, name))
    elif not os.path.exists(value):
        raise Exception("Missing userdata file '%s'"%value)
    return value

def _verify_live_file(filename, signing_pubkey):
    """Verify the signature of a live Linux's ISO file's associated files"""
    if signing_pubkey is None:
        util.print_event(f"NOT verifying signature of the '{os.path.basename(filename)}' file (not signed)")
        return
    if not os.path.exists(signing_pubkey):
        util.print_event(f"NOT verifying signature of the '{os.path.basename(filename)}' file (no public signing key file)")
        return

    util.print_event(f"Verifying signature of the '{os.path.basename(filename)}' file")
    sigfile="%s.sign"%filename
    if not os.path.exists(sigfile):
        raise Exception("Missing expected signature file '%s'"%sigfile)
    sobj=x509.CryptoKey(None, util.load_file_contents(signing_pubkey))
    hash=cgen.compute_hash_file(filename)
    sig=util.load_file_contents(sigfile)
    sobj.verify(hash, sig)

class ParamsSet:
    """Object used to handle the parameters required by an install or format configuration.
    In case of an Install configuration, the paramaters required by the components of a live Linux image (userdata)
    are merged (in a "_components" section).

    This object also validates that a set of (named parameter, value) provides all the values for the expected parameters, and
    allows one to get that associated value.
    """
    def __init__(self, conf, user_data_file=None):
        if not isinstance(conf, confs.InstallConfig) and not isinstance(conf, confs.FormatConfig):
            raise Exception("Code bug: @config must be an InstallConfig or a FormatConfig object")

        self._conf=conf
        if user_data_file:
            if not os.path.exists(user_data_file):
                raise Exception("Missing file '%s'"%user_data_file)
            self._user_data=json.load(open(user_data_file, "r"))
        else:
            self._user_data={}

        self._params=None # merged list of parameters
        self._values=None # will be defined upon validation

    @property
    def params(self):
        """Consolidated list of parameters. The ones required by the live Linux components are in the
        '_component' sub dictionary"""
        if self._params is None:
            res=self._conf.parameters.copy()
            components={}
            for entry in self._user_data:
                components[entry]=self._user_data[entry]
            res["_components"]=components
            self._params=res
        return self._params

    def validate(self, values):
        """Validate that @values provides values for all the required parameters"""
        for param in self.params:
            if param=="_components":
                continue
            pspec=self.params[param]
            if param not in values:
                raise Exception("Missing value for parameter '%s'"%param)
            value=values[param]
            confs.validate_parameter_value(pspec, value, self._conf.config_dir)

        for component in self.params["_components"]:
            centry=self.params["_components"][component]
            for param in centry:
                pspec=centry[param]
                if component not in values["_components"]:
                    raise Exception("Missing user data for component '%s'"%component)
                if not isinstance(values["_components"][component], dict):
                    raise Exception("Invalid user data for component '%s' (expected a dict)"%component)
                if param not in values["_components"][component]:
                    raise Exception("Missing value for parameter '%s'"%param)
                value=values["_components"][component][param]
                if pspec["type"]=="file":
                    value=get_userdata_file_real_path(self._conf, component, param, value)
                confs.validate_parameter_value(pspec, value, self._conf.config_dir)

        self._values=values

    def get_value_for_param(self, param, component=None):
        """Get the value associated with a param"""
        if self._values is None:
            raise Exception("Code bug: params set not yet validated")
        if component is not None:
            if component not in self._values["_components"]:
                raise Exception("Unknown component '%s'"%component)
            if param not in self._values["_components"][component]:
                raise Exception("Undefined parameter '%s'"%param)
            return self._values["_components"][component][param]
        else:
            if param not in self._values:
                raise Exception("Undefined parameter '%s'"%param)
            return self._values[param]


class Installer:
    """Object to actually create an INSECA installation or format a device, depending on the actual @conf object
    passed"""
    def __init__(self, conf, params, targetfile, live_iso_file, user_data_file, build_infos=None):
        """
        - @conf: an InstallConfig or FormatConfig object
        - @params: the parameter's values (for all the required parameters)
        - @targetfile: where the installation will occur
        - @live_iso_file and @user_data_file: ISO image file and associated params file
        - @user_data_file
        - @build_infos: build infos (version, build type, etc)

        NB: if @conf is an InstallConfig object, then the build configuration which generated the live Linux
            should be of type WKS or SERVER.
        """
        assert isinstance(conf, confs.InstallConfig) or isinstance(conf, confs.FormatConfig)

        if live_iso_file is not None:
            live_iso_file=os.path.realpath(live_iso_file)
            user_data_file=os.path.realpath(user_data_file)
            for fname in (live_iso_file, user_data_file):
                if fname:
                    if not os.path.exists(fname):
                        raise Exception("Missing file '%s'"%fname)

        self._target=targetfile
        self._conf=conf
        self._config_data=conf.export_complete_configuration()
        if isinstance(conf, confs.InstallConfig):
            assert isinstance(build_infos, dict)
            assert "build-type" in build_infos
            assert "valid-from" in build_infos
            build_type=confs.BuildType(build_infos["build-type"])
            assert build_type in (confs.BuildType.WKS, confs.BuildType.SERVER)
            self._config_data["install"]=valh.replace_variables(self._config_data["install"], params)
            self._valid_from_ts=int(build_infos["valid-from"])

            if "l10n" in build_infos:
                l10ndata=build_infos["l10n"]
                self._l10n=confs.L10N(timezone=l10ndata.get("timezone"), locale=l10ndata.get("locale"), keyboard_layout=l10ndata.get("keyboard-layout"),
                            keyboard_model=l10ndata.get("keyboard-model"), keyboard_variant=l10ndata.get("keyboard-variant"),
                            keyboard_option=l10ndata.get("keyboard-option"))
            else:
                self._l10n=confs.L10N(timezone="UTC", locale="en_US.UTF-8", keyboard_layout="en", keyboard_model="pc105")
                self._l10n=confs.L10N(timezone="UTC", locale="fr_FR.UTF-8", keyboard_layout="fr", keyboard_model="pc105")
            print(f"L10n is: {self._l10n}")

        self._live_iso_file=live_iso_file
        self._params=params
        self._pset=ParamsSet(self._conf, user_data_file)
        self._dev=Device.Device(self._target)

        # generated secrets
        self._blob0=None # actual password
        self._blob1_priv=None # TMP file
        self._blob1_pub=None # TMP file
        self._sec_password=None # actual password

    def validate(self):
        """Validate the coherence and exhaustivity of all the provided information"""
        self._pset.validate(self._params)

    def _get_actual_path(self, path):
        """Get the actual path with regards to the directory in which the config file is located"""
        if not os.path.isabs(path):
            path="%s/%s"%(self._conf.config_dir, path)
        if not os.path.exists(path):
            raise Exception("No such file or directory '%s'"%path)
        return path

    def _install_low_level(self):
        """First step in the installation: format device and install Grub"""
        # create complete specifications
        tmp=util.Temp(json.dumps(self._config_data))
        builder=SpecBuilder.Builder(self._target, tmp.name)
        for key in self._params:
            if key=="_components":
                continue
            builder.set_parameter_value(key, self._params[key], self._conf.config_dir)
        if isinstance(self._conf, confs.InstallConfig):
            builder.set_parameter_value("blob0", self._blob0)

        specs=builder.get_specifications()
        #print("SPECS: %s"%json.dumps(specs, indent=4))

        # check all the partitions we need are present
        if isinstance(self._conf, confs.InstallConfig):
            for partition_id in (Live.partid_internal, Live.partid_data):
                found=False
                for partdata in specs["partitions"]:
                    if partdata["id"]==partition_id:
                        found=True
                        break
                if not found:
                    raise Exception("Required partition '%s' not present in specifications"%partition_id)

        # Formatting device
        util.print_event("Formating device")
        self._dev.format(specs)
        self._dev.seal_metadata(specs)

        # finish here if we have a format config
        if isinstance(self._conf, confs.FormatConfig):
            return

        # install GRUB (EFI), from the live Linux ISO
        if specs["type"]!="dos":
            efi_mp=self._dev.mount(Live.partid_efi)
            util.print_event("Installing Grub (EFI)")
            self._dev.install_grub_efi(self._live_iso_file, efi_mp)

        # install GRUB (legacy BIOS)
        if specs["type"]!="gpt":
            util.print_event("Installing Grub (legacy BIOS)")
            self._dev.install_grub_bios()

        # install GRUB common config files
        util.print_event("Installing Grub configuration")
        grubresdir=f"{os.path.dirname(__file__)}/grub-config"
        tmp=util.Temp()
        tarobj=tarfile.open(tmp.name, mode="w")
        for (dirpath, dirnames, fnames) in os.walk(grubresdir):
            for fname in fnames:
                path=f"{dirpath}/{fname}"
                if fname=="grub.cfg":
                    value=f"timezone={self._l10n.timezone} lang={self._l10n.locale} locales={self._l10n.locale}"
                    if self._l10n.keyboard_layout:
                        value+=f" keyboard-layouts={self._l10n.keyboard_layout}"
                    if self._l10n.keyboard_model:
                        value+=f" keyboard-model={self._l10n.keyboard_model}"
                    if self._l10n.keyboard_variant:
                        value+=f" keyboard-variants={self._l10n.keyboard_variant}"
                    if self._l10n.keyboard_option:
                        value+=f" keyboard-options={self._l10n.keyboard_option}"

                    # switch to the specified l10n
                    current_lang=os.environ.get("LANG")
                    os.environ["LANG"]=self._l10n.locale

                    t=tempfile.NamedTemporaryFile()
                    data=util.load_file_contents(path)
                    data=valh.replace_variables(data, {
                        "l10n": value,
                        "boot": _("Boot"),
                        "stop": _("Stop PC"),
                        "restart": _("Restart PC")
                    })
                    print(f"GRUB: {data}")

                    # revert to the default l10n
                    os.environ["LANG"]=current_lang

                    util.write_data_to_file(data, t.name)
                    t.flush()
                    tarobj.add(t.name, arcname=path[len(grubresdir)+1:])
                else:
                    tarobj.add(path, arcname=path[len(grubresdir)+1:])
        tarobj.close()
        grub_install_dirs=self._dev.install_grub_configuration(tmp.name, Live.partid_live)

        # install GRUB install specific files
        grubresdir=self._get_actual_path(self._config_data["install"]["grub"])
        for fname in os.listdir(grubresdir):
            if fname.endswith(".png"):
                srcpath="%s/%s"%(grubresdir, fname)
                if not os.path.isfile(srcpath):
                    raise Exception("No '%s' file in installation config"%fname)
                for dir in grub_install_dirs:
                    destpath="%s/%s"%(dir, fname)
                    shutil.copyfile(srcpath, destpath)
        util.print_event("Sealing device's metadata")
        self._dev.seal_metadata(specs)
        util.print_event("Low level done")

        # keep track of the actual secrets to mount partitions, will be used later
        for part_data in specs["partitions"]:
            if part_data["password"] is not None:
                self._dev.set_partition_secret(part_data["id"], "password", part_data["password"])
        #print("LAYOUT: %s"%json.dumps(self._dev.get_partitions_layout(), indent=4))

    def _install_live_linux(self):
        """Install the live Linux on the device (in the live0 partition)"""
        # mount the live Linux ISO and copy files from it
        with tempfile.TemporaryDirectory() as tmpdirname:
            (status, out, err)=util.exec_sync(["mount", "-o", "ro,loop", self._live_iso_file, tmpdirname])
            if status!=0:
                raise Exception("Could not mount the live Linux file '%s': %s"%(self._live_iso_file, err))
            try:
                mp=self._dev.mount(Live.partid_live)
                os.makedirs("%s/live0"%mp, mode=0o700)
                os.makedirs("%s/live1"%mp, mode=0o700)
                Live.install_live_linux_files_from_iso(mp+"/live0", tmpdirname)
                os.symlink("live0", mp+"/live")
                util.write_data_to_file("%s"%self._valid_from_ts, mp+"/live/valid-from-ts")
            finally:
                (status, out, err)=util.exec_sync(["umount", tmpdirname])

    def _create_resources_map(self):
        """Create a structure to prepare data to be writen to partitions on the device"""
        return {
            Live.partid_dummy: {},
            Live.partid_efi: {},
            Live.partid_live: {},
            Live.partid_internal: {},
            Live.partid_data: {}
        } # for each partition:
          # - key: path once copied on the device in the specified partition
          # - value: a list with (in that order):
          #   1- a Temp object, or a path to a file, or None (to ensure directory is still created even if empty)
          #   2- the permissions (like 0o644), or None (useful for FAT filesystem where permissions don't exist)

    def _write_resources_from_map(self, resources):
        """Actually write the data on the device's partitions, @resources must have been created by _create_resources_map()"""
        for part_id in resources:
            for relpath in resources[part_id]:
                mp=self._dev.mount(part_id)
                (srcobj, perms)=resources[part_id][relpath]
                util.print_event("Copying '%s'..."%os.path.basename(relpath))
                dest="%s/%s"%(mp, relpath)
                if srcobj is None:
                    os.makedirs(dest, exist_ok=True)
                else:
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    if isinstance(srcobj, str):
                        shutil.copyfile(srcobj, dest)
                    else:
                        shutil.copyfile(srcobj.name, dest)
                if perms is not None:
                    os.chmod(dest, perms)
        util.print_event("Syncing all writes")
        os.sync()

    def _install_resources(self):
        if not isinstance(self._conf, confs.InstallConfig):
            raise Exception("Code bug: @config must be an InstallConfig object")
        resources=self._create_resources_map()

        # blob0, encrypted with user password
        salt=cpass.generate_salt()
        password=cpass.harden_password_for_blob0(self._params["password-user"], salt)
        eobj=cpass.CryptoPassword(password)
        eblob=eobj.encrypt(self._blob0)
        user_uuid=str(uuid.uuid4())
        cn="Live user"
        if "firstname" in self._params and "lastname" in self._params:
            cn="%s %s"%(self._params["firstname"], self._params["lastname"])
        elif "project" in self._params:
            cn=self._params["project"]
        entry={user_uuid: {
            "mode": "password",
            "salt": salt,
            "enc-blob": eblob,
            "cn": cn
        }}
        tmp=util.Temp(data=json.dumps(entry))
        resources[Live.partid_dummy]["/resources/blob0.json"]=[tmp, 0o400]

        # blob1, encrypted with blob0
        eobj=cpass.CryptoPassword(self._blob0)
        eblob=eobj.encrypt(self._blob1_priv.get_contents())
        tmp=util.Temp(data=eblob)
        resources[Live.partid_dummy]["/resources/blob1.priv.enc"]=[tmp, 0o400]
        resources[Live.partid_dummy]["/resources/blob1.pub"]=[self._blob1_pub, 0o400]

        # prepare key configuration
        key_id=str(uuid.uuid4())
        gconf=self._conf.global_conf
        rconf=gconf.get_repo_conf(self._conf.build_repo_id)
        kc={
            "device-id": key_id,
            "install-config-id": self._config_data["id"],
            "build-repo-config": {
                "id": rconf.id,
                "password": rconf.password,
                "compress": rconf.compress
            }
        }
        resources[Live.partid_internal]["credentials/storage"]=[None, 0o700]
        kc["storage-sources"]={} # key=storage target, value= root of the associated SyncConfig object
        sync_obj_found=False
        for sync_obj in gconf.get_all_sync_objects(False):
            try:
                kc["storage-sources"][sync_obj.name]=sync_obj.root
                if sync_obj.conf_file is not None:
                    # copy associated config file if any
                    resources[Live.partid_internal]["credentials/storage/%s"%sync_obj.name]=[sync_obj.conf_file, 0o644]
                sync_obj_found=True
            except:
                pass
        if not sync_obj_found:
            raise Exception("No available Sync. object found, updates will not be available")
        tmp=util.Temp(data=json.dumps(kc))
        resources[Live.partid_internal]["resources/config.json"]=[tmp, 0o400]

        # prepare key's attestation
        attestation={
            "device-id": key_id,
            "install-config-id": self._config_data["id"],
            "build-repo-config": rconf.id,
            "install-config-descr":self._config_data["descr"]
        }
        allparams=self._conf.parameters
        for param in allparams:
            pentry=allparams[param]
            if "attest" in pentry and pentry["attest"]:
                attestation[param]=self._params[param]
        attestation["hardware-id"]=self._dev.get_hardware_id()

        privkey_file=self._get_actual_path(self._config_data["install"]["attestation-skey-priv-file"])
        attest_data=json.dumps(attestation, sort_keys=True)
        sobj=x509.CryptoKey(privkey_data=util.load_file_contents(privkey_file), pubkey_data=None)
        attest_sign=sobj.sign(attest_data)
        attestation={
            "signature": attest_sign,
            "attestation": attestation
        }
        tmp=util.Temp(data=json.dumps(attestation))
        resources[Live.partid_internal]["credentials/attestation.json"]=[tmp, 0o400]
        #print("ATTESTATION: %s"%json.dumps(attestation, indent=4))

        # private key to decrypt the privdata.tar.enc file
        privkey_file=self._get_actual_path(self._config_data["install"]["privdata-ekey-priv-file"])
        resources[Live.partid_internal]["credentials/privdata-ekey.priv"]=[privkey_file, 0o400]

        # signing key (for device authentication)
        pubkey_file=self._conf.devicemeta_pubkey
        resources[Live.partid_dummy]["resources/meta-sign.pub"]=[pubkey_file, None]

        # prepare blob1 encryption usage
        blob1_priv=self._blob1_priv.get_contents()
        blob1_pub=self._blob1_pub.get_contents()
        eobj=x509.CryptoKey(blob1_priv, blob1_pub)

        # write all to device _BEFORE_ computing the integrity fingerprint
        self._write_resources_from_map(resources)

        # umount partitions where we won't write anymore
        util.print_event("Unmounting partitions")
        for partid in (Live.partid_dummy, Live.partid_efi, Live.partid_live):
            self._dev.umount(partid)

        # prepare hashing of the live partition
        mp=self._dev.mount(Live.partid_live)
        (chunks, hash, log0)=fpchunks.compute_files_chunks(mp)
        if _debug:
            os.makedirs("/tmp/debug", exist_ok=True)
            util.write_data_to_file(json.dumps(chunks, indent=4), "/tmp/debug/chunks")
            util.write_data_to_file(hash, "/tmp/debug/hash-create")
            util.write_data_to_file(json.dumps(log0, indent=4), "/tmp/debug/log-create")

        resources=self._create_resources_map() # new fresh start
        tmp=eobj.encrypt(json.dumps(chunks), return_tmpobj=True)
        resources[Live.partid_dummy]["resources/chunks.enc"]=[tmp, 0o400]
        self._write_resources_from_map(resources)

        # determine integrity fingerprint and log
        # !!! TO DEVELOPERS: beyond this point, we must not write anymore to any of the partitions part of the integrity computation !!!
        (ifp, log)=Live.compute_integrity_fingerprint(self._dev, blob1_priv, hash)
        log+=[{"live": log0}]
        tmp=util.Temp(data=json.dumps(log))
        resources=self._create_resources_map() # new fresh start
        resources[Live.partid_internal]["resources/integrity-fingerprint-log.json"]=[tmp, 0o400]
        if _debug:
            util.write_data_to_file(json.dumps(log, indent=4), "/tmp/debug/log-create")

        # generate random password for the live partition (we don't use the one already defined by the device's formatting)
        # and encrypt it using ifp
        int_password=util.gen_random_bytes(64)
        eobj=cpass.CryptoPassword(ifp)
        eblob=eobj.encrypt(int_password)
        tmp=util.Temp(data=eblob)
        resources[Live.partid_dummy]["resources/internal-pass.enc"]=[tmp, 0o400]

        current_password=self._dev.get_partition_secret(Live.partid_internal, "password")
        partinfo=self._dev.get_partition_info_for_id(Live.partid_internal)
        obj=enc.Enc("luks", partinfo["part-file"], password=current_password)
        obj.add_password(int_password)

        # encrypt data's password
        data_password=self._dev.get_partition_secret(Live.partid_data, "password")
        eblob=eobj.encrypt(data_password)
        tmp=util.Temp(data=eblob)
        resources[Live.partid_internal]["credentials/data-pass.enc"]=[tmp, 0o400]

        # other resources
        for name in ["default-profile", "default-documents"]:
            resources[Live.partid_internal][name]=[None, 0o755]
            resdir=self._get_actual_path(self._config_data["install"][name])
            for fname in os.listdir(resdir):
                path="%s/%s"%(resdir, fname)
                if not os.path.isfile(path):
                    raise Exception("'%s' is not a file (in '%s')"%(path, name))
                resources[Live.partid_internal]["%s/%s"%(name, fname)]=[path, 0o444]
                if name!="default-profile":
                    resources[Live.partid_data][fname]=[path, None]

        for name in ["default-wallpaper"]:
            resdir=self._get_actual_path(self._config_data["install"][name])
            resources[Live.partid_internal]["/resources/%s"%name]=[resdir, 0o644]

        # write all to device
        self._write_resources_from_map(resources)

    def _install_build_repo(self):
        """Copy the build repo's contents"""
        if not isinstance(self._conf, confs.InstallConfig):
            raise Exception("Code bug: @config must be an InstallConfig object")
        # NB: the build repo's definition is already present in the devices's config file (config.json)
        mp=self._dev.mount(Live.partid_internal)
        util.print_event("Copying live Linux repository...")
        gconf=self._conf.global_conf
        rconf=gconf.get_repo_conf(self._conf.build_repo_id)
        targetdir="%s/build-repo"%mp
        shutil.copytree(rconf.path, targetdir, symlinks=True)
        os.chmod(targetdir, 0o700)
        util.print_event("Syncing all writes")
        os.sync()

    def _install_userdata(self):
        if not isinstance(self._conf, confs.InstallConfig):
            raise Exception("Code bug: @config must be an InstallConfig object")
        resources=self._create_resources_map()
        resources[Live.partid_internal]["components"]=[None, 0o700] # components dir

        params=self._pset.params
        for component in params["_components"]:
            specs={}
            specs_trace={}
            component_dir="components/%s"%component
            resources[Live.partid_internal][component_dir]=[None, 0o755] # this component's dir
            for param in params["_components"][component]:
                pspec=params["_components"][component][param]
                value=self._pset.get_value_for_param(param, component)
                specs[param]=value
                if pspec["type"]=="file":
                    if value is not None:
                        vpath=get_userdata_file_real_path(self._conf, component, param, value)
                        fname=str(uuid.uuid4())
                        resources[Live.partid_internal]["%s/%s"%(component_dir, fname)]=[vpath, 0o644]
                        specs[param]=fname
                        specs_trace[param]=value

            tmp=util.Temp(data=json.dumps(specs, indent=4))
            resources[Live.partid_internal]["%s/userdata.json"%component_dir]=[tmp, 0o644]
            tmp=util.Temp(data=json.dumps(specs_trace, indent=4))
            resources[Live.partid_internal]["%s/userdata-trace.json"%component_dir]=[tmp, 0o644]

        # write all to device
        self._write_resources_from_map(resources)

    def install(self):
        """Perform the installation"""
        # generate secrets
        self._blob0=util.gen_random_bytes(64)
        (self._blob1_priv, self._blob1_pub)=x509.gen_rsa_key_pair()
        self._sec_password=util.gen_random_bytes(64)

        # actual installation
        try:
            self._install_low_level()
            if isinstance(self._conf, confs.InstallConfig):
                # files verifications
                _verify_live_file(self._live_iso_file, self._conf.signing_pubkey)
                base=os.path.dirname(self._live_iso_file)
                _verify_live_file(f"{base}/infos.json", self._conf.signing_pubkey)
                _verify_live_file(f"{base}/live-linux.userdata-specs", self._conf.signing_pubkey)

                # actual install
                self._install_live_linux()
                self._install_resources()
                self._install_build_repo()
                self._install_userdata()
        finally:
            self._conf.global_conf.umount_all_repos()
            self._dev.umount_all()

class DeviceInstaller(Installer):
    """Creates an installation on a physical device"""
    def __init__(self, iconf, live_iso_file, user_data_file, params, devfile, build_infos):
        if not isinstance(devfile, str) or not devfile.startswith("/dev/"):
            raise Exception("Invalid disk file name '%s'"%devfile)
        Installer.__init__(self, iconf, params, devfile, live_iso_file, user_data_file, build_infos)

class ImageInstaller(Installer):
    """Creates an installation as a new VM image file"""
    def __init__(self, iconf, live_iso_file, user_data_file, params, imagefile, size_g, build_infos):
        if not isinstance(size_g, int) or size_g<=0:
            raise Exception("Invalid disk image size '%s'"%size_g)
        if not isinstance(imagefile, str):
            raise Exception("Invalid disk file name '%s'"%imagefile)
        imagefile=os.path.realpath(imagefile)

        # remove the file if it existed
        if os.path.exists(imagefile):
            os.remove(imagefile)

        # create VM image file
        (status, out, err)=util.exec_sync(["qemu-img", "create", "-f", "qcow2", imagefile, "%sG"%size_g])
        if status!=0:
            raise Exception("Could not create disk image '%s': %s"%(imagefile, err))

        # parent init
        Installer.__init__(self, iconf, params, imagefile, live_iso_file, user_data_file, build_infos)

class DeviceFormatter(Installer):
    """Formats a physical device"""
    def __init__(self, fconf, params, devfile):
        if not devfile.startswith("/dev/"):
            raise Exception("Invalid disk file name '%s'"%devfile)
        Installer.__init__(self, fconf, params, devfile, None, None)

class Updater:
    def __init__(self, blob0, signing_pubkey, mp_dummy, mp_live, mp_internal, 
                 password_internal, password_data, live_iso_file, targetfile):
        if not os.path.exists(live_iso_file):
            raise Exception("Missing file '%s'"%live_iso_file)
        live_iso_file=os.path.realpath(live_iso_file)
        self._live_iso_file=live_iso_file
        self._dev=Device.Device(targetfile)

        self._signing_pubkey=signing_pubkey
        self._blob0=blob0
        self._mp_dummy=mp_dummy
        self._mp_live=mp_live
        self._mp_internal=mp_internal

        self._int_password=password_internal
        self._data_password=password_data

    def _install_live_linux(self):
        """Install the live Linux on the device (in the live0 partition)"""
        # get the current slot index
        livelink="%s/live"%self._mp_live
        path=os.readlink(livelink)
        if path[-1]=="0":
            current_index=0
        elif path[-1]=="1":
            current_index=1
        else:
            raise Exception("CODEBUG: the 'live' link points to invalid live target '%s'"%path)

        new_index=0 if current_index==1 else 1
        util.print_event("Using live Linux slot %s"%new_index)

        # mount the live Linux ISO and copy files from it
        with tempfile.TemporaryDirectory() as tmpdirname:
            util.print_event("Mounting live Linux's ISO file")
            (status, out, err)=util.exec_sync(["mount", "-o", "ro,loop", self._live_iso_file, tmpdirname])
            if status!=0:
                raise Exception("Could not mount the live Linux file '%s': %s"%(self._live_iso_file, err))
            try:
                Live.install_live_linux_files_from_iso(self._mp_live+"/live%s"%new_index, tmpdirname)
                os.remove(livelink)
                os.symlink("live%s"%new_index, livelink)
            finally:
                (status, out, err)=util.exec_sync(["umount", tmpdirname])

    def update(self):
        """Actually performs the live Linux update"""
        # get blob1_priv & pub
        eobj0=cpass.CryptoPassword(self._blob0)        
        blob1_pub=util.load_file_contents("%s/resources/blob1.pub"%self._mp_dummy)
        data=util.load_file_contents("%s/resources/blob1.priv.enc"%self._mp_dummy)
        blob1_priv=eobj0.decrypt(data).decode()

        # files verifications
        _verify_live_file(self._live_iso_file, self._signing_pubkey)
        base=os.path.dirname(self._live_iso_file)
        _verify_live_file(f"{base}/infos.json", self._signing_pubkey)
        _verify_live_file(f"{base}/live-linux.userdata-specs", self._signing_pubkey)

        # install new live Linux
        self._install_live_linux()

        # install GRUB (EFI), from the live Linux ISO
        efi_mp=self._dev.mount(Live.partid_efi)

        # remove useless files to make some space
        ufile="%s/boot/grub/fonts/unicode.pf2"%efi_mp
        if os.path.exists(ufile):
            util.print_event("Removing %s"%ufile)
            os.remove(ufile)

        util.print_event("Updating Grub (EFI)")
        self._dev.install_grub_efi(self._live_iso_file, efi_mp)

        (chunks, hash, log0)=fpchunks.compute_files_chunks(self._mp_live)
        if _debug:
            os.makedirs("/tmp/debug", exist_ok=True)
            util.write_data_to_file(json.dumps(chunks, indent=4), "/tmp/debug/chunks")
            util.write_data_to_file(hash, "/tmp/debug/hash-create")
            util.write_data_to_file(json.dumps(log0, indent=4), "/tmp/debug/log-create")

        # encrypt integrity chunks
        eobj=x509.CryptoKey(None, blob1_pub)
        tmp=eobj.encrypt(json.dumps(chunks), return_tmpobj=True)

        fname="%s/resources/chunks.enc"%self._mp_dummy
        tmp.copy_to(fname)
        os.chmod(fname, 0o400)

        (ifp, log)=Live.compute_integrity_fingerprint(self._dev, blob1_priv, hash)
        log+=[{"live": log0}]
        tmp=util.Temp(data=json.dumps(log))
        fname="%s/resources/integrity-fingerprint-log.json"%self._mp_internal
        tmp.copy_to(fname)
        os.chmod(fname, 0o400)
        if _debug:
            util.write_data_to_file(json.dumps(log, indent=4), "/tmp/debug/log-create")

        # encrypt access to internal password
        eobj=cpass.CryptoPassword(ifp)
        eblob=eobj.encrypt(self._int_password)
        tmp=util.Temp(data=eblob)
        fname="%s/resources/internal-pass.enc"%self._mp_dummy
        tmp.copy_to(fname)
        os.chmod(fname, 0o400)

        # encrypt access to data password
        eblob=eobj.encrypt(self._data_password)
        tmp=util.Temp(data=eblob)
        fname="%s/credentials/data-pass.enc"%self._mp_internal
        tmp.copy_to(fname)
        os.chmod(fname, 0o400)

class DeviceUpdater(Updater):
    """Update an installation which is on a physical device"""
    def __init__(self, blob0, signing_pubkey, mp_dummy, mp_live, mp_internal, 
                 password_internal, password_data, live_iso_file, devfile):
        if not isinstance(devfile, str) or not devfile.startswith("/dev/"):
            raise Exception("Invalid disk file name '%s'"%devfile)
        Updater.__init__(self, blob0, signing_pubkey, mp_dummy, mp_live, mp_internal, 
                         password_internal, password_data, live_iso_file, devfile)

class ImageUpdater(Updater):
    """Update an installation which is a VM image file"""
    def __init__(self, blob0, signing_pubkey, mp_dummy, mp_live, mp_internal, 
                 password_internal, password_data, live_iso_file, imagefile):
        if not isinstance(imagefile, str):
            raise Exception("Invalid disk file name '%s'"%imagefile)
        imagefile=os.path.realpath(imagefile)

        # check that the file exists
        if not os.path.exists(imagefile):
            raise Exception("No VM disk image file '%s'"%imagefile)

        # parent init
        Updater.__init__(self, blob0, signing_pubkey, mp_dummy, mp_live, mp_internal, 
                         password_internal, password_data, live_iso_file, imagefile)

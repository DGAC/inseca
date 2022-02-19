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

#
# This script builds a Live Linux ISO image from a description of its contents
# specified in a file from the command line
#

import sys
import json
import datetime
import os
import tarfile
import shutil

import namesgenerator
import Utils as util
import CryptoX509 as x509
import Configurations as confs
import Sync

def get_actual_mp(path):
    path=os.path.realpath(path)
    while not os.path.ismount(path):
        path=os.path.dirname(path)
    return path

class Builder:
    def __init__(self, build_conf):
        gconf=confs.GlobalConfiguration()
        bconf=gconf.get_build_conf(build_conf)

        self._gconf=gconf
        self._confdir=os.path.realpath(bconf.config_dir)
        self._bconf=bconf
        self._name=namesgenerator.get_random_name()
        self._scriptdir=os.path.realpath(os.path.dirname(sys.argv[0]))
        self._privdata_pubkey=None
        privdata_pubkey=bconf.privdata_pubkey
        if privdata_pubkey:
            self._privdata_pubkey=util.load_file_contents(privdata_pubkey)

        self._builddir=bconf.build_dir
        if os.path.exists (self._builddir) and not os.path.isdir(self._builddir):
            raise Exception("Invalid build-dir '%s'"%self._builddir)

        self._livedir="%s/%s.building"%(self._builddir, bconf.id)
        self._build_data_file="%s/build-data"%(bconf.config_dir)
        self._components=bconf.components

    @property
    def image_file(self):
        return self._bconf.image_iso_file

    @property
    def build_data_file(self):
        return self._build_data_file

    @property
    def userdata_specs_file(self):
        return self._bconf.image_userdata_specs_file

    @property
    def livedir(self):
        return self._livedir

    def prepare_build_dir(self):
        os.makedirs(self._livedir, exist_ok=True)
        self.clean_build_dir()
        self._packages_list_dir="%s/config/package-lists"%self._livedir
        self._packages_extra_dir="%s/config/packages.chroot"%self._livedir
        self._fs_dir="%s/config/includes.chroot"%self._livedir

        for entry in (self._packages_list_dir, self._packages_extra_dir, self._fs_dir):
            os.makedirs(entry, exist_ok=True)

    def get_component_src_path(self, component):
        path="%s/../components/%s"%(self._scriptdir, component)
        if os.path.exists(path):
            return path
        if "INSECA_EXTRA_COMPONENTS" in os.environ:
            path="%s/%s"%(os.environ["INSECA_EXTRA_COMPONENTS"], component)
            if os.path.exists(path):
                return path
        raise Exception("Component '%s' not found"%component)

    def _compute_userdata_parameters(self):
        """Compute all the user data parameters (required by some components during
        the install phase).
        Ex:
        { "Windows-VM" : {
            "win-image" : { 
              "descr" : "Windows disk image file",
              "type" : "str"
            }
        } }
        """
        all_params={}
        for component in self._components:
            cpath=self.get_component_src_path(component)
            cconf_file="%s/config.json"%cpath
            if os.path.exists(cconf_file):
                data=json.load(open(cconf_file, "r"))
                for param in data["userdata"]:
                    if component not in all_params:
                        all_params[component]={}
                    all_params[component][param]=data["userdata"][param]
        return all_params

    def _encrypt_privdata(self):
        """Encrypt all the component"s resources with the resources public key"""
        res_file="%s/privdata.tar"%self._fs_dir
        res_dir="%s/privdata"%self._fs_dir
        if not os.path.exists(res_dir):
            return

        # create TAR archive of all the PRIVDATA resources
        resources=os.listdir(res_dir)
        if len(resources)==0:
            return

        if self._privdata_pubkey is None:
            raise Exception("Some components specified some PRIVDATA, but no encryption public key has been provided")
        tar=tarfile.open(res_file, mode="w")
        for entry in resources:
            tar.add("%s/%s"%(res_dir, entry), arcname=entry)
        tar.close()
    
        # encrypt TAR archive
        data=util.load_file_contents(res_file, binary=True)
        obj=x509.CryptoKey(None, self._privdata_pubkey)
        tmp=obj.encrypt(data, return_tmpobj=True)
        tmp.copy_to("%s.enc"%res_file)
        if "INSECA_DONT_BUILD" not in os.environ:
            os.remove(res_file)
            shutil.rmtree(res_dir)

    def _encrypt_live_config_code(self):
        """Encrypt all the component"s resources with the resources public key"""
        res_file="%s/live-config.tar"%self._fs_dir
        res_dir="%s/live-config"%self._fs_dir
        if not os.path.exists(res_dir):
            return

        # create TAR archive of all the resources config code
        resources=os.listdir(res_dir)
        if len(resources)==0:
            return
        if self._privdata_pubkey is None:
            raise Exception("Some components have specific init code, but no encryption public key has been provided")
        tar=tarfile.open(res_file, mode="w")
        for entry in resources:
            tar.add("%s/%s"%(res_dir, entry), arcname=entry)
        tar.close()
    
        # encrypt TAR archive
        data=util.load_file_contents(res_file, binary=True)
        obj=x509.CryptoKey(None, self._privdata_pubkey)
        tmp=obj.encrypt(data, return_tmpobj=True)
        tmp.copy_to("%s.enc"%res_file)
        if "INSECA_DONT_BUILD" not in os.environ:
            os.remove(res_file)
            shutil.rmtree(res_dir)

    def copy_resources(self):
        """Copy all the resources from each component in the live Linux's build directory"""
        # prepare file to append build data to
        util.write_data_to_file("""\n=== building '%s' ===
Version: %s
Name: %s
"""%(self._bconf.id, self._bconf.version, self._name), self._build_data_file, append=True)

        # copy each component
        for component in self._components:
            print("Preparing component '%s'"%component)
            cpath=self.get_component_src_path(component)
            component_files=os.listdir(cpath)
            if not os.path.isdir(cpath):
                raise Exception("Component '%s' is not a directory"%component)

            # copy livebuild's structural files first
            for fname in component_files:
                if fname[0]=="_" and fname!="_ATTIC":
                    path="%s/%s"%(cpath, fname)
                    if os.path.isdir(path):
                        arname="%s/ar-%s"%(self._builddir, fname)
                        shutil.make_archive(arname, "tar", path) # the ".tar" extension is automatically added
                        target_dir="%s/%s"%(self._livedir, fname[1:])
                        shutil.unpack_archive("%s.tar"%arname, target_dir, "tar")
                        os.remove("%s.tar"%arname)
                    elif fname.endswith(".tar"):
                        shutil.unpack_archive(path, self._livedir, "tar")

            # copy all other elements
            for fname in component_files:
                path="%s/%s"%(cpath, fname)
                if fname=="packages.list":
                    shutil.copy(path, "%s/%s.list.chroot"%(self._packages_list_dir, component))

                elif fname=="packages.deb":
                    for dfile in os.listdir(path):
                        shutil.copy("%s/%s"%(path, dfile), self._packages_extra_dir)

                elif fname in ["_ATTIC"]:
                    pass # ignore that file/directory

                elif fname[0]=="_":
                    pass # already done

                elif fname=="live-config":
                    # copy component's init code
                    arname="%s/lc-%s"%(self._builddir, fname)
                    shutil.make_archive(arname, "tar", path) # the ".tar" extension is automatically added
                    shutil.unpack_archive("%s.tar"%arname, "%s/live-config/%s"%(self._fs_dir, component), "tar")
                    os.remove("%s.tar"%arname)

                elif os.path.isdir(path):
                    # copy contents of dir to the root of the live image
                    arname="%s/ar-%s.tar"%(self._builddir, fname)
                    tarobj=tarfile.open(arname, "w", dereference=False)
                    tarobj.add(path, arcname=fname)
                    tarobj.close()
                    tarobj=tarfile.open(arname, "r")
                    tarobj.extractall(self._fs_dir)
                    os.remove(arname)

                else:
                    # ignore that file
                    pass

            # run prepare.sh/py scripts
            exec_env=os.environ.copy()
            exec_env["BUILD_DIR"]=self._livedir
            exec_env["BUILD_DATA_FILE"]=self._build_data_file
            exec_env["COMPONENT_DIR"]=cpath
            exec_env["CONF_DIR"]=self._confdir
            exec_env["LIVE_DIR"]=self._fs_dir
            exec_env["LIBS_DIR"]=os.path.realpath(self._scriptdir+"/../lib")
            exec_env["PYTHONPATH"]=":".join(sys.path)
            for fname in component_files:
                if fname in ["prepare.sh", "prepare.py"]:
                    tmpfile=util.Temp()
                    cconf=self._components[component]
                    util.write_data_to_file(json.dumps(cconf), tmpfile.name)
                    exec_env["CONF_DATA_FILE"]=tmpfile.name
                    exec_env["PRIVDATA_DIR"]="%s/privdata/%s"%(self._fs_dir, component)

                    path="%s/%s"%(cpath, fname)
                    (status, out, err)=util.exec_sync([path], exec_env=exec_env)
                    if status!=0:
                        raise Exception("Prepare script failed: %s"%err)

        # protect resources
        self._encrypt_privdata()
        self._encrypt_live_config_code()

    def compute_user_data_specs(self):
        # aggregate component's extra info
        params=self._compute_userdata_parameters()
        os.makedirs(os.path.dirname(self.userdata_specs_file), exist_ok=True)
        util.write_data_to_file(json.dumps(params, sort_keys=True), self.userdata_specs_file)

    def _interrut_callback(self, child):
        self._build_interrupted=True
        # kill the docker process (ATTN: does not kill or remove the Docker container)
        child.kill()

    def build(self):
        # check that the build directory does not have the noexec or nodev options (like /tmp)
        (status, out, err)=util.exec_sync(["findmnt", "-J", get_actual_mp(self._builddir)])
        if status!=0:
            raise Exception(f"Could not get the mountpoint of build dir '{self._builddir}': {err}")
        data=json.loads(out)
        options=data["filesystems"][0]["options"].split(",")
        if "noexec" in options or "nodev" in options:
            raise Exception("Invalid build-dir '%s': mounted with the 'noexec' or 'nodev' option"%self._builddir)

        # generate keyinfos.json file
        data={
            "version": "%s %s"%(self._bconf.version, self._name),
            "valid-from": util.get_timestamp(),
            "valid-to": self._bconf.valid_to
        }
        path="%s/opt/share"%self._fs_dir
        fname="%s/keyinfos.json"%path
        os.makedirs(path, exist_ok=True)
        util.write_data_to_file(json.dumps(data, indent=4, sort_keys=True), fname)

        built_iso="%s/live-image-amd64.hybrid.iso"%self._livedir

        # remove last build log, if any        
        buildlog="%s/%s.last-build"%(self._builddir, self._bconf.id)
        try:
            os.remove(buildlog)
        except Exception:
            pass

        # proxy settings
        proxy=""
        if "http_proxy" in os.environ:
            proxy=os.environ["http_proxy"]
        else:
            Sync.proxy_pac_file=self._gconf.proxy_pac_file
            proxy_data=Sync.find_suitable_proxy()
            if proxy_data is not None:
                proxy=proxy_data["http"]
        if proxy:
            util.print_event("Using HTTP proxy '%s'"%proxy)
        else:
            util.print_event("Not using any HTTP proxy")

        # build live image
        print("Build information is appended to '%s'"%self._build_data_file)
        now=datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        util.write_data_to_file("Started: %s UTC\n"%now, self._build_data_file, append=True)
        print("Building Live image...")
        #args=["docker", "run", "-m", "3192m", "--cpus=1", "--privileged", "--rm", "-v", "%s:/live"%self._livedir,
        #      "-e", "http_proxy=%s"%proxy, "--name", self._bconf.id, "live-build"]
        args=["docker", "run", "-m", "3192m", "--privileged", "--rm", "-v", "%s:/live"%self._livedir,
              "-e", "http_proxy=%s"%proxy, "--name", self._bconf.id, "live-build"]

        self._build_interrupted=False
        (status, out, err)=util.exec_sync(args, interrupt_callback=self._interrut_callback)

        file=open(buildlog, "a")
        file.write("---------- LAST BUILD STDOUT ----------\n")
        file.write(out)
        file.write("\n---------- LAST BUILD STDERR ----------\n")
        file.write(err)
        file.close()

        if status!=0 or not os.path.exists(built_iso):
            now=datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            if self._build_interrupted:
                util.write_data_to_file("Interrupted: %s UTC\n\n"%now, self._build_data_file, append=True)
                # remove the build Docker container
                util.exec_sync(["docker", "rm", "-f", self._bconf.id])
                raise Exception("Build interrupted")
            else:
                util.write_data_to_file("Failed: %s UTC\n\n"%now, self._build_data_file, append=True)
                raise Exception("Could not build Live image, see the '%s' file"%buildlog)

        # keep built ISO
        print("Copying generated ISO file...")
        iso_dir=os.path.dirname(self.image_file)
        os.makedirs(iso_dir, exist_ok=True)
        shutil.move(built_iso, self.image_file)

        # if run as sudo, set the permissions to the original user
        if "SUDO_UID" in os.environ and "SUDO_GID" in os.environ:
            uid=int(os.environ["SUDO_UID"])
            gid=int(os.environ["SUDO_GID"])
            os.chown(iso_dir, uid, gid)
            os.chown(self.image_file, uid, gid)

        # log info
        now=datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        util.write_data_to_file("Finished: %s UTC\n\n"%now, self._build_data_file, append=True)

    def clean_build_dir(self):
        """Clean up the build dir, while keeping the ISO images"""
        # remove files using the "live-build" Docker image
        print("Cleaning up build directory")
        args=["docker", "run", "--rm", "-v", "%s:/live"%self._livedir,
              "live-build", "shred"]
        (status, out, err)=util.exec_sync(args)
        if status!=0:
            raise Exception("Could not clean build environment: %s"%err)
        try:
            os.rmdir(self._livedir)
        except Exception:
            pass

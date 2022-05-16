#!/usr/bin/python3

import os
import syslog
import json
import shutil
import Utils as util

vmfile="/internal/guest-os/guest-os.img"

# link to the actual VM file
if not os.path.exists(vmfile):
    resfile="%s/userdata.json"%os.environ["USERDATA_DIR"]
    if os.path.exists(resfile): 
        component_conf=json.load(open(resfile, "r"))
        path=component_conf["os-image"]
        if path is not None:
            evmfile="%s/%s"%(os.environ["USERDATA_DIR"], path)
            if os.path.exists(evmfile):
                try:
                    os.chmod(evmfile, 0o644)
                    dirname=os.path.dirname(vmfile)
                    os.makedirs(dirname, mode=0o700 , exist_ok=True)
                    shutil.chown(dirname, "libvirt-qemu", "libvirt-qemu")
                    os.link(evmfile, vmfile)
                    syslog.syslog(syslog.LOG_INFO, "guest-os.img file set up")
                except Exception as e:
                    syslog.syslog(syslog.LOG_ERR, "Could not link '%s' to '%s': %s"%(evmfile, vmfile, str(e)))

# remove Windows icon if VM's HDD image is not present
if not os.path.exists(vmfile):
    system_desktop_files_path="/usr/share/applications/"
    user_desktop_files_path="/home/insecauser/.local/share/applications/"
    desktop_file="windows.desktop"
    for dir in (system_desktop_files_path, user_desktop_files_path):
        path="%s/windows.desktop"%dir
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception as e:
                syslog.syslog(syslog.LOG_ERR, "Error removing desktop file '%s': %s"%(path, str(e)))

# re-start or stop the fairshell-virt-system service
# (re-start at least because the config file was specified as build data
# and has thus been changed before this script was called)
if os.path.exists(vmfile):
    (status, out, err)=util.exec_sync(["systemctl", "restart", "fairshell-virt-system"])
    if status!=0:
        syslog.syslog(syslog.LOG_ERR, "Could not restart the fairshell-virt-system service: %s"%err)
else:
    (status, out, err)=util.exec_sync(["systemctl", "stop", "fairshell-virt-system"])
    if status!=0:
        syslog.syslog(syslog.LOG_ERR, "Could not stop the fairshell-virt-system service: %s"%err)

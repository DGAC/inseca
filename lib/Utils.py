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

import shutil
import subprocess
import re
import os
import sys
import enum
import datetime
import tempfile
import base64
import time
import syslog
import json
import sys
import signal

# NB about locales (http://jaredmarkell.com/docker-and-locales/ & https://stackoverflow.com/questions/28405902/how-to-set-the-locale-inside-a-docker-container):
# apt-get install -y locales
# sed -i -e 's/# fr_FR.UTF-8 UTF-8/fr_FR.UTF-8 UTF-8/' /etc/locale.gen
# dpkg-reconfigure --frontend=noninteractive locales
# export LANG=fr_FR.UTF-8

debug=False
print_events=False

def create_exec_env_C():
    env=os.environ.copy()
    env["LANG"]="C"
    return env

def is_run_as_root():
    """Tell if the application is run as root or not"""
    return True if os.getuid()==0 else False

def _exec_sync_interrupted(sig, dummy):
    """Signal handler called when a SIGINT or SIGTERM signal is received"""
    proc=_exec_sync_interrupted.proc
    if proc is not None:
        _exec_sync_interrupted.callback(proc)
_exec_sync_interrupted.proc=None
_exec_sync_interrupted.callback=None

def exec_sync(args, stdin_data=None, as_bytes=False, exec_env=None, cwd=None, C_locale=False, timeout=None, interrupt_callback=None):
    """Run a command and wait for it to terminate, returns (exit code, stdout, stderr)
    Notes:
    - @stdin_data allows to specify some input data, while @as_bytes specifies if the output data
      need to be converted to a string (when False), or left as a bytes array (True), or passed to stdout
      if None.
    - if @C_locale is True, then the LANG environment variable is set to "C" (useful when parsing output which
      repends on the locale)
    - if @timeout is specified, then the sub process is killed after that number of seconds and the return code is 250
    """
    if debug:
        logmsg="==> "
        if stdin_data:
            logmsg+='@echo -n "%s" | '%stdin_data
        logmsg+=' '.join(args)
        print("%s"%logmsg)

    if C_locale:
        if exec_env:
            raise Exception("The @exec_env and @C_locale can't be both specified")
        exec_env=os.environ.copy()
        exec_env["LANG"]="C.UTF-8"
        exec_env["LC_ALL"]="C.UTF-8"

    # start process
    if as_bytes==None:
        outs=sys.stdout
        errs=sys.stderr
    else:
        outs=subprocess.PIPE
        errs=subprocess.PIPE
    if stdin_data==None:
        bdata=None
        sub=subprocess.Popen(args, stdout=outs, stderr=errs, env=exec_env, cwd=cwd)
    else:
        bdata=stdin_data
        if isinstance(bdata, str):
            bdata=bdata.encode()
        sub = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=outs, stderr=errs, env=exec_env, cwd=cwd)

    # let process run
    try:
        if interrupt_callback is not None:
            _exec_sync_interrupted.proc=sub
            _exec_sync_interrupted.callback=interrupt_callback
            handl_SIGINT=signal.signal(signal.SIGINT, _exec_sync_interrupted)
            handl_SIGTERM=signal.signal(signal.SIGTERM, _exec_sync_interrupted)
        (out, err)=sub.communicate(input=bdata, timeout=timeout)
        retcode=sub.returncode
    except subprocess.TimeoutExpired:
        sub.kill()
        (out, err)=sub.communicate(timeout=timeout)
        retcode=250
    finally:
        if interrupt_callback is not None:
            signal.signal(signal.SIGINT, handl_SIGINT)
            signal.signal(signal.SIGTERM, handl_SIGTERM)
            _exec_sync_interrupted.proc=None
            _exec_sync_interrupted.callback=None

    # prepare returned values
    sout=None
    serr=None
    if as_bytes==False:
        sout=re.sub (r'[\r\n]+$', '', out.decode())
        serr=re.sub (r'[\r\n]+$', '', err.decode())
    elif as_bytes==True:
        sout=out
        serr=err
    return (retcode, sout, serr)

def exec_async(args, exec_env=None):
    """Run a command in the background
    Returns: a subprocess.Popen object
    """
    import subprocess
    return subprocess.Popen(args, env=exec_env)

def write_data_to_file(data, filename, append=False, perms=None):
    """Creates a file with the specified data and filename"""
    mode="wb"
    if append:
        mode="ab"

    if perms:
        original_umask=os.umask(0)
        opt=os.O_TRUNC
        if append:
            opt=os.O_APPEND
        fd=os.open(filename, os.O_CREAT | os.O_RDWR | opt, perms)
        os.umask(original_umask)
        file=os.fdopen(fd, mode)
        stat=os.stat(filename)
        if stat.st_mode & 0o777 !=perms:
            raise Exception("Invalid permissions for '%s': expected %s and got %s"%(filename, oct(perms), oct(stat.st_mode & 0o777)))
    else:
        file=open(filename, mode)

    rdata=data
    if isinstance(rdata, str):
        rdata=data.encode()
    if rdata is not None:
        file.write(rdata)
    file.close()

def load_file_contents(filename, binary=False):
    """Load the contents of a file in memory, as a string if @binary is False,
    or a bytearray if @binary is True"""
    with open(filename, "rb") as file:
        if binary:
            return file.read()
        else:
            return file.read().decode()

def gen_random_bytes(size=32):
    """Generate some random data"""
    if not isinstance(size, int):
        raise Exception("CODEBUG: expected a size as integer")
    args=["/usr/bin/openssl", "rand", str(size)]
    (status, out, err)=exec_sync(args, as_bytes=True)
    if status!=0:
        raise Exception ("Could not generate random data of %d bytes: %s"%(size, err))
    randbytes=base64.b64encode(out).decode()
    # NB: OpenSSL does not like binary passwords, if they contain a 0, they are truncated (may also generate an error if first byte is 0)
    return randbytes

def add_padding(path, reserved_kb=0):
        """Create (or modify if it exists) a file with random data to fill the partition to which @path belongs,
        while leaving al least @reserved_kb free space. The padding file is named 'PADDING'.
        """
        # get available free space
        (status, out, err)=exec_sync(["df", "-k", "--output=size,used", path])
        if status!=0:
            raise Exception("Could not get amount of free space: %s"%err)
        # out will be like:
        # 1K-blocks    Used
        #   5840832 5824448
        lines=out.splitlines()
        res=lines[1].split()
        size=int(res[0])
        used=int(res[1])
        to_pad=(size-used-reserved_kb)*1024
        if to_pad==0:
            return

        # create/update padding file
        BUF_SIZE = 524288 # 512kb chunks
        padfile="%s/.padding"%path
        if os.path.exists(padfile) and to_pad<0:
            # truncate padding file
            size=os.path.getsize(padfile)
            with open(padfile, "w+") as d:
                d.truncate(size+to_pad)
        else:
            if to_pad<0:
                raise Exception("Situation should not happen!")
            
            with open("/dev/urandom", "rb") as s:
                bytesread=0
                buf_size=BUF_SIZE
                while buf_size>128:
                    # open padding file
                    if os.path.exists(padfile):
                        d=open(padfile, "ab")
                    else:
                        d=open(padfile, "wb")

                    # write as much as possible with current buffer size
                    while True:
                        to_read=buf_size
                        if to_pad-bytesread-to_read<0:
                            to_read=to_pad-bytesread
                        rd=s.read(to_read)
                        try:
                            wlen=d.write(rd)
                            print("wrote %s bytes"%wlen)
                            bytesread+=wlen
                            if bytesread>=to_pad:
                                break
                        except OSError as e:
                            try:
                                d.close()
                            except Exception:
                                # we really need to stop playing the game
                                buf_size=0
                                break
                            if e.errno==28:
                                break # => padding file will be reopened
                            else:
                                raise e

                    # change buffer size
                    buf_size=int(buf_size/4)
                    print("New buffer size: %s"%buf_size)
                print("We're done!")

def delay_to_text(delay):
    """Converts a delay in seconds to a textual representation."""
    rh=int(delay/3600)
    remain=delay-rh*3600
    rm=int(remain/60)
    rs=remain-rm*60
    if rh==0 and rm <10:
        return "%02dmn %02ds"%(rm, rs)
    else:
        return "%02dh %02dmn"%(rh, rm)

class Temp:
    """Temporary file handling.
    The difference with the objects in the tempfile module are that this object is only a simple
    wrapper around a file descriptor, ensuring that the temp file is actuelly removed when the object
    is destroyed.
    User the @fd and @data attributes to access the object.
    """
    def __init__(self, data=None):
        (self.fd, self.name)=tempfile.mkstemp()
        if data != None:
            if isinstance(data,str):
                data=data.encode()
            os.write(self.fd, data)
            os.fdatasync(self.fd)

    def __del__(self):
        # Close the FD, but don't raise an exception in case of error
        try:
            os.close(self.fd)
        except:
            pass
        if not "KEEP_TEMP_FILES" in os.environ:
            os.unlink(self.name)

    def get_contents(self, binary=False):
        return load_file_contents(self.name, binary)

    def copy_to(self, filename):
         shutil.copyfile(self.name, filename)

def get_disk_sizes(devfile):
    """Get the size of the disk as a pair: (size in bytes, size of the sectors in bytes)
    """
    if devfile.startswith("/dev/loop"):
        # if we have mounted a qcow image file, then use qemu-img
        try:
            (status, out, err)=exec_sync(["/sbin/losetup", "-J", "-l"])
            if status!=0:
                raise Exception(err)
            data=json.loads(out)["loopdevices"]
            for entry in data:
                if entry["name"]==devfile:
                    bfile=entry["back-file"]
                    (status, out, err)=exec_sync(["qemu-img", "info", "--output=json", bfile])
                    if status!=0:
                        raise Exception(err)
                    data2=json.loads(out)
                    return (data2["virtual-size"], entry["log-sec"])
            raise Exception("No backend file for loop device '%s'"%devfile)
        except Exception as e:
            raise Exception("Could not list loop devices: %s"%str(e))

    (status, out, err)=exec_sync(["/bin/lsblk", "-n", "-d", "--bytes", "-o", "SIZE,LOG-SEC", devfile])
    if status!=0:
        raise Exception("Could not determine disk size for '%s'; %s"%(devfile, err))
    parts=out.split()
    return (int(parts[0]), int(parts[1]))

def get_device_serial(devfile):
    if not devfile.startswith("/dev/") or devfile.startswith("/dev/loop") or devfile.startswith("/dev/nbd"):
        return ""
    args=["/bin/lsblk", "-n", "-d", "-o", "SERIAL", devfile]
    (status, out, err)=exec_sync(args)
    if status!=0:
        raise Exception("Could not get SN of '%s': %s"%(devfile, err))
    return out

def get_device_model(devfile):
    # for now return an empty string as there are variations among the different flavors of Linux
    # which return different string
    if not devfile.startswith("/dev/") or devfile.startswith("/dev/loop") or devfile.startswith("/dev/nbd"):
        return "VM image file"

    args=["/bin/lsblk", "-n", "-d", "-P", "-o", "VENDOR,MODEL", devfile]
    (status, out, err)=exec_sync(args)
    if status!=0:
        raise Exception("Could not get model of '%s': %s"%(devfile, err))
    parts=[out[0:out.find("MODEL=")], out[out.find("MODEL="):]]
    nparts=[]
    for p in parts:
        # p will be like: MODEL="Voyager GTX     "
        sp=p.split("=")
        p=sp[1].strip()
        p=p[1:len(p)-1].strip()
        p=re.sub(r'[ _-]*', '', p).lower() # remove spaces, - and _ as these depend on the Linux version used
        nparts+=[p]
    return ' '.join(nparts)

class LabelType(str, enum.Enum):
    DOS = "dos"
    GPT = "gpt"
    HYBRID = "hybrid"

def get_device_label_type(devfile):
    """Get the device's partition scheme: DOS, GPT or HYBRID, or None if no partitioning detected"""
    (status, out, err)=exec_sync(["/sbin/gdisk", "-l", devfile], C_locale=True, stdin_data="\n")
    if status!=0:
        raise Exception("Could not get information about device '%s': %s"%(devfile, err))
    if "GPT with hybrid MBR" in out:
        return LabelType.HYBRID

    (status, out, err)=exec_sync(["/sbin/fdisk", "-l", devfile], C_locale=True)
    if status!=0:
        raise Exception("Could not get information about device '%s': %s"%(devfile, err))

    for line in out.splitlines():
        if line.startswith("Disklabel type:"):
            parts=line.split()
            return LabelType(parts[2])
    return None

def get_partition_infos(partfile, enforce_known_filesystem=True):
    """Get partition's type and label"""
    try:
        counter=0
        while counter<20:
            (status, out, err)=exec_sync(["/sbin/blkid", "-p", "-s", "TYPE", "-s", "LABEL", partfile])
            if status!=0:
                counter+=1
                time.sleep(0.5)
            else:
                import Filesystem as filesystem
                fstype=None
                label=None
                for block in out.split():
                    if "=" in block:
                        parts=block.split('"')
                        if parts[0]=="LABEL=":
                            label=parts[1]
                        elif parts[0]=="TYPE=":
                            fstype=parts[1]
                if fstype:
                    fstype=fstype.upper()
                    if fstype=="VFAT":
                        fstype="FAT"
                if fstype and not "LUKS" in fstype:
                    if enforce_known_filesystem:
                        return (filesystem.fstype_from_string(fstype).value, label)
                    else:
                        return (fstype, label)
                else:
                    return (None, label)
        raise Exception("Could not determine filesystem type for '%s'; %s"%(partfile, err))
    except Exception as e:
        print("** get_partition_infos(%s) => %s"%(partfile, str(e)))
        raise e
        return (None, None)

lsblk_wait_time=10 # wait up to 10' for a device to be there
def get_encrypted_partition_mapped_elements(part_name):
    """Get the current map name for the partition (for ex. like "/dev/mapper/luks-82993631-f0c9-4fd6-b97e-53d2f12f714e")
    and the mount point, or (None, None) if not opened"""
    counter=0
    while counter<lsblk_wait_time:
        (status, out, err)=exec_sync(["/bin/lsblk", "-n", "-l", "-p", "-o", "NAME,MOUNTPOINT", part_name],
                                     C_locale=True)
        if status!=0:
            if "not a block device" in err:
                # kernel might not yet be ready
                counter+=1
                time.sleep(1)
            else:
                raise Exception("Could not get mount status of '%s': %s"%(part_name, err))
        else:
            break

    if out!="":
        for line in out.splitlines():
            if line!="":
                parts=line.split(maxsplit=1)
                if parts[0]!=part_name:
                    if len(parts)==2:
                        return (parts[0], parts[1])
                    else:
                        return (parts[0], None)
    return (None, None)

def get_timestamp(as_str=False, utc=True):
    """Get the current UTC timestamp, in Unix time format, as an integer or a
    string if @as_str is True."""
    if utc:
        now=datetime.datetime.utcnow()
    else:
        now=datetime.datetime.now()
    ts=int(datetime.datetime.timestamp(now))
    if as_str:
        return "{:012d}".format(ts)
    else:
        return ts

def get_disks():
    disks={}
    (status, out, err)=exec_sync(["/bin/lsblk", "-n", "-b", "-o", "NAME,ROTA,HOTPLUG,TYPE,SIZE,VENDOR,MODEL", "--nodeps"])
    if status!=0:
        raise Exception("Could not list system's disks: %s"%err)
    for line in out.splitlines():
        parts=line.split()
        if len(parts)>=5 and parts[3] in ("disk", "loop"):
            devfile="/dev/%s"%parts[0]
            rota=True if parts[1]=="1" else False
            internal=False if parts[2]=="1" else True
            if len(parts)>=6:
                model=" ".join(parts[5:])
            elif parts[0].startswith("nbd"):
                model="VM image disk"
            elif parts[0].startswith("loop"):
                model="Loop disk"
                internal=False
            else:
                model=""
            (status, out2, err)=exec_sync(["/bin/lsblk", "-n", "-o", "MOUNTPOINT", devfile])
            if status!=0:
                raise Exception("Could not list mountpoints of disk '%s': %s"%(devfile, err))
            disks[devfile]={
                "useable": True,
                "live": False,
                "internal-disk": internal,
                "ssd": not rota,
                "size-G": int(int(parts[4])/1000/1000/1000),
                "model": model
            }
            parts2=out2.splitlines()
            if "/" in parts2:
                disks[devfile]["useable"]=False

            for mp in parts2:
                if "/lib/live" in mp:
                    disks[devfile]["useable"]=False
                    disks[devfile]["live"]=True
                    break
    return disks

def get_virtual_machine_disk_size(imagefile):
    """Returns the size of the VM image in bytes"""
    (status, out, err)=exec_sync(["/usr/bin/qemu-img", "info", imagefile])
    if status!=0:
        raise Exception("Could not analyse image file '%s': %s"%(imagefile, err))
    for line in out.splitlines():
        if line.startswith("virtual size"): # like: virtual size: 30G (32212254720 bytes)
            parts=line.split("(")
            parts=parts[1].split()
            return int(parts[0])
    raise Exception("Could not parse output of 'qemu-img info'")

def get_partition_data_sizes(partition_path):
    """Get total and available sizes in bytes"""
    (status, out, err)=exec_sync(["/bin/df", "-B", "1024", partition_path])
    if status!=0:
        raise Exception("Can't analyse partition size")
    else:
        lines=out.splitlines()
        parts=lines[1].split()
        sizetotal_m=int(parts[1])*1024
        sizefree_m=int(parts[3])*1024
        return (sizetotal_m, sizefree_m)

def get_hw_descr():
    (status, out, err)=exec_sync(["/usr/sbin/dmidecode", "-s", "system-manufacturer"])
    if status!=0:
        raise Exception("Could not get system's manufacturer: %s"%err)
    manufacturer=out

    (status, out, err)=exec_sync(["/usr/sbin/dmidecode", "-s", "system-version"])
    if status!=0:
        raise Exception("Could not get system's version: %s"%err)
    version=out

    (status, out, err)=exec_sync(["/usr/sbin/dmidecode", "-s", "processor-family"])
    if status!=0:
        raise Exception("Could not get system's processor family: %s"%err)
    proc=out

    (status, out, err)=exec_sync(["/usr/sbin/dmidecode", "-s", "processor-frequency"])
    if status!=0:
        raise Exception("Could not get system's processor's frequency: %s"%err)
    freq=out
    result="%s %s (%s @ %s)"%(manufacturer, version, proc, freq)
    syslog.syslog(syslog.LOG_INFO, "WH infos: %s"%result)
    return result

def get_hw_mem():
    data=load_file_contents("/proc/meminfo")
    for line in data.splitlines():
        if line.startswith("MemTotal:"):
            parts=line.split()
            syslog.syslog(syslog.LOG_INFO, "HW total mem: %d"%(int(parts[1])*1024))
            return int(parts[1])*1024
    return None

def get_root_live_partition():
    """Get the live partition from which the system has booted.
    Returns devfile, for ex.: /dev/vda3"""
    # get the overlay's 'lower dir'
    (status, out, err)=exec_sync(["mount"])
    if status!=0:
        raise Exception("Could not list mount points: %s"%err)
    mounts=out
    ovline=None
    for line in mounts.splitlines():
        if line.startswith("overlay on / type overlay "):
            #  line will be like: overlay on / type overlay (rw,noatime,lowerdir=/run/live/rootfs/filesystem.squashfs/,upperdir=/run/live/overlay/rw,workdir=/run/live/overlay/work)
            ovline=line
            break
    if ovline is None:
        raise Exception("Could not identify the overlay filesystem")

    parts=re.split(r'\(|\)', ovline)
    params=re.split(r',', parts[1])
    found=False
    for param in params:
        if param.startswith("lowerdir="):
            (dummy, lowerdir)=param.split("=")
            # dir will be something like "/run/live/rootfs/filesystem.squashfs/"
            found=True
            break
    if not found:
        raise Exception("Could not identify overlay's lower dir")

    # get the loop device associated with the overlay's lower dir
    loopdev=None
    if lowerdir[-1]=="/":
        lowerdir=lowerdir[:-1]
    for line in mounts.splitlines():
        if "on %s type squashfs"%lowerdir in line:
            (loopdev, dummy)=line.split(" ", 1)
            break
    if loopdev!="/dev/loop0": # at this point, should always be loop0, otherwise something is very wrong...
        raise Exception("Unexpected loop device '%s'"%loopdev)

    # get the file serving as backend for the loopdev
    (status, out, err)=exec_sync(["/sbin/losetup", "-l", "-J", loopdev]) # as JSON!
    if status!=0:
        raise Exception("Could not list loop devices set up: %s"%err)
    data=json.loads(out)
    backend=data["loopdevices"][0]["back-file"]

    # get the mounted device partition holding that backend file
    (status, out, err)=exec_sync(["df", backend])
    if status!=0:
        raise Exception("Could not use df: %s"%err)
    first=True
    for line in out.splitlines():
        if first:
            first=False
        else:
            (devfile, dummy)=line.split(" ", 1)
            # devfile will be like "/dev/vda3"
            if not devfile.startswith("/dev/vd") and not devfile.startswith("/dev/sd"):
                raise Exception("Invalid boot partition '%s'"%devfile)
            return devfile
    raise Exception("Internal error: boot partition is not mounted, where is the '%s' file ???"%backend)

def get_device_of_partition(partfile):
    """Get the device file from a device partition, for example:
    /dev/nvme0n1p3 => /dev/nvme0n1
    /dev/sda3 => /dev/sda
    """
    inv=partfile[::-1]
    parts=inv.split("p", maxsplit=1)
    if len(parts)>1 and len(parts[1])>len("/dev/sd"):
        # ex: /dev/nvme0n1p3
        return parts[1][::-1]
    while True:
        if inv[0] in "0123456789":
            inv=inv[1:]
        else:
            break
    return inv[::-1]

def get_partition_of_device(devfile, partnum):
    """Get the devide file for the specified partition number.
    For example:
    ("/dev/sda", 3) => "/dev/sda3"
    ("/dev/nvme0n1", 3) => "/dev/nvme0n1p3"
    """
    if devfile.startswith("/dev/nvme"):
        return "%sp%s"%(devfile, partnum)
    return "%s%s"%(devfile, partnum)

def wait_for_partition(partfile, timeout=10):
    """Wait for the specified partition to be present, and raise an exception if not after @timeout seconds"""
    counter=0
    while counter<timeout:
        if os.path.exists(partfile):
            return
        counter+=1
        time.sleep(1)
    raise Exception("No device file for partition '%s'"%partfile)

def print_event(event, log=True):
    if log:
        syslog.syslog(syslog.LOG_INFO, event)
    if print_events:
        print("%s: %s"%(get_timestamp(), event), flush=True)

def change_user_comment(user, comment):
    """Change user comment, used in the UI"""
    (status, out, err)=exec_sync(["usermod", "-c", comment, user])
    if status==0:
        syslog.syslog(syslog.LOG_INFO, "Usermod to '%s'"%comment)
    else:
        syslog.syslog(syslog.LOG_ERR, "Failed to usermod to '%s'"%(comment, err))

def chown_r(filename, uid, gid):
    os.chown(filename, uid, gid)
    if os.path.isdir(filename):
        for fname in os.listdir(filename):
            chown_r(f"{filename}/{fname}", uid, gid)
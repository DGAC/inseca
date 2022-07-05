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

import datetime
import Jobs as jobs
import gi
import syslog
gi.require_version("Gtk", "3.0")
from gi.repository import GObject
from gi.repository import Gtk

import dbus
import dbus.mainloop.glib

import Utils as util
import Configurations

class PluggedDevices(GObject.Object):
    """Maintains a list of DevInfo objects, one for each plugged device"""
    __gsignals__ = {
        "changed": (GObject.SIGNAL_RUN_FIRST, None, ())
    }
    def __init__(self):
        GObject.Object.__init__(self)
        self._devices={} # key=devfile, value=associated DevInfo

        # use UDisks2 (on DBus) to be notified when a partition is mounted
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self._system_bus=dbus.SystemBus()

    def get_dev_infos(self, devfile):
        """Get the DevInfo associated to the specified device"""
        if devfile in self._devices:
            return self._devices[devfile]
        return None

    def get_devices(self):
        """Get the list of all the devices' names"""
        res=list(self._devices.keys())
        res.sort()
        return res

    def update(self, after_plug_event=True):
        """Update the list of devices, to be called upon device event notification.
        If @after_plug_event if True, a small sleep is performed first"""
        #print("Updating plugged devices list!!! (wait: %s)"%after_plug_event)
        job=jobs.GetPluggedDevicesJob2(after_plug_event)
        job.start()
        job.wait_with_ui()
        if job.exception:
            raise job.exception
        disks_data=job.result

        # analyse devices
        ndevices={}
        for devfile in disks_data:
            deventry=disks_data[devfile]
            if not deventry["useable"]:
                continue
            eobj=self.get_dev_infos(devfile)
            if eobj:
                ndevices[devfile]=eobj
                del self._devices[devfile]
            else:
                # create new object
                deventry["devfile"]=devfile
                obj=DevInfo(deventry)
                ndevices[devfile]=obj
        self._devices=ndevices

        # use UDisks2 (on DBus) to be notified when a partition is mounted
        for obj in _get_udisks2_devices(self._system_bus):
            obj.connect_to_signal("PropertiesChanged", self._udisks_prop_changed, path_keyword="sender_path")

        # tell the world the object has changed
        self.emit("changed")

    def _udisks_prop_changed(self, dbus_interface, changed_properties, invalidated_properties, sender_path):
        if dbus_interface=="org.freedesktop.UDisks2.Filesystem":
            syslog.syslog(syslog.LOG_INFO, "Notification from UDISKS for %s"%sender_path)
            print("Notification from UDISKS for %s"%sender_path)
            self.emit("changed")

def _get_udisks2_devices(system_bus):
    """Get the list of devices' partitions implementing the org.freedesktop.UDisks2.Filesystem interface as DBus objects"""
    devices=[]
    udisks_mgr=system_bus.get_object("org.freedesktop.UDisks2", "/org/freedesktop/UDisks2")
    om=dbus.Interface(udisks_mgr, "org.freedesktop.DBus.ObjectManager")
    mo=om.GetManagedObjects()
    for path in mo:
        # @path is dbus.ObjectPath object
        v=mo[path]
        fsi = v.get("org.freedesktop.UDisks2.Filesystem", None)
        if fsi:
            devices+=[system_bus.get_object("org.freedesktop.UDisks2", path)]
    return devices

class DevicesListUI(Gtk.ComboBoxText):
    def __init__(self, devlist_obj):
        if not isinstance(devlist_obj, PluggedDevices):
            raise Exception("CODEBUG: invalid @devlist_obj")
        Gtk.ComboBoxText.__init__(self)
        self.set_hexpand(True)
        self._devlist_obj=devlist_obj
        self._devlist_obj.connect("changed", self._update)

    def _update(self, dummy):
        # get the current select item, except if it's the internal disk device
        cur_sel=self.get_active_text()
        cur_di=self.get_selected_devinfo()
        if cur_di and cur_di.is_internal:
            cur_sel=None

        # clear the current list
        self.remove_all()

        # populate the new list
        index=0
        devices_list=self._devlist_obj.get_devices()
        for devfile in devices_list:
            dev_obj=self._devlist_obj.get_dev_infos(devfile)

            # compute description (in case there is more than one device of the same type plugged)
            if dev_obj.is_internal:
                descr=dev_obj.descr
            else:
                descr=None
                for devfile2 in devices_list:
                    if devfile2!=devfile:
                        dev_obj2=self._devlist_obj.get_dev_infos(devfile2)
                        if dev_obj.descr==dev_obj2.descr:
                            descr="%s (@%s, %s)"%(dev_obj.descr, dev_obj.plugged_ts, devfile)
                if not descr:
                    descr="%s (@%s)"%(dev_obj.descr, dev_obj.plugged_ts)

            self.append_text(descr)
            if cur_sel==descr:
                self.set_active(index)
            index+=1

        # if there is only one plugged device and it's not the internal disk device, automatically select it
        if len(devices_list)==1:
            dev_obj=self._devlist_obj.get_dev_infos(devices_list[0])
            if not dev_obj.is_internal:
                self.set_active(0)
    
    def get_selected_devinfo(self):
        """Get the DevInfo of the currently selected device, or None"""
        try:
            sel=self.get_active()
            if sel>=0:
                devices=self._devlist_obj.get_devices()
                return self._devlist_obj.get_dev_infos(devices[sel]) # the devices list may not be on par with the combo box if we are calling this
                                                                     # function from within the self._update() function
        except:
            pass
        return None

    def get_selected_devfile(self):
        """Get the devfile of the currently selected device, or None"""
        sel=self.get_active()
        if sel>=0:
            devices=self._devlist_obj.get_devices()
            return devices[sel]
        return None


class DevInfo:
    """Gathers all the information for a plugged device"""
    def __init__(self, deventry):
        """
        @deventry ex.: {
            "useable": true,
            "live": false,
            "internal-disk": false,
            "ssd": false,
            "size-G": 123,
            "model": "Verbatim STORE_N_GO",
            "descr": "Verbatim STORE_N_GO (123 Go)",
            "devfile": "/dev/sdd"
        }
        """
        self._conf_obj=None
        self._mountpoints={} # key=part ID, value=mount point as a temp
        self._update(deventry)
        now=datetime.datetime.now()
        self._ts=datetime.datetime.strftime(now, "%H:%M:%S")

    @property
    def devfile(self):
        return self._devfile

    @property
    def descr(self):
        return self._descr

    @property
    def is_internal(self):
        return self._is_internal

    @property
    def valid(self):
        """Tells if the device has been created by an INSECA install or format configuration"""
        return self._valid

    @property
    def meta_verified(self):
        return self._meta_verified

    @property
    def config_id(self):
        return self._confid

    @property
    def config_obj(self):
        return self._conf_obj

    @property
    def creation_date(self):
        return self._creation_date

    @property
    def attributes(self):
        return self._attributes

    @property
    def data_partitions(self):
        return self._data_partitions

    @property
    def plugged_ts(self):
        return self._ts

    def _get_data_partition(self, part_id):
        for data_part in self.data_partitions:
            if data_part["id"]==part_id:
                return data_part
        raise Exception("Could not find any data partition with ID '%s'"%part_id)

    def mount(self, part_id):
        """Mount a partition from its ID
        Returns the mount point"""
        job=jobs.DeviceMountJob(self.devfile, part_id)
        job.start()
        job.wait_with_ui()
        if job.exception is not None:
            raise job.exception
        return job.result

    def umount(self, part_id):
        """Umount a partition from its ID"""
        job=jobs.DeviceUmountJob(self.devfile, part_id)
        job.start()
        job.wait_with_ui()
        if job.exception is not None:
            raise job.exception

    def get_mountpoint(self, part_id):
        data_part=self._get_data_partition(part_id)
        (status, out, err)=util.exec_sync(["/bin/lsblk", "-n", "-o", "MOUNTPOINT", "%s%s"%(self.devfile, data_part["devfile-ext"])])
        if status==0:
            # we will have more than one line for encrypted devices, as the lsblk command will display the mounted "dependencies" 
            for line in out.splitlines():
                if line:
                    return line
            return None
        raise Exception("Could not determine partition '%s' mountpoint: %s"%(self.devfile, err))

    def _update(self, deventry):
        """Integrate the result of the "inseca dev-ident" execution, to populate all the
        RO properties of the object"""
        # safe init variables
        self._valid=False
        self._creation_date="N/A"
        self._confid=None
        self._conf_obj=None
        self._attributes=[]
        self._meta_verified=False
        self._data_partitions=[]

        try:
            self._devfile=deventry["devfile"]
            self._descr=deventry["descr"]
            self._is_internal=deventry["internal-disk"]
        except Exception as e:
            raise Exception("CODEBUG: invalid @deventry argument '%s'"%deventry)

        # run device identification
        try:
            job=jobs.DeviceIdentifyJob(self._devfile)
            job.start()
            job.wait_with_ui()
            if job.exception:
                raise job.exception
            ident_result=job.result
        except Exception as e:
            return # FIXME: log the error somewhere
        self._valid=True
        #print('ident_result: %s'%json.dumps(ident_result, indent=4))

        try:
            gconf=Configurations.get_gconf()
            udata=ident_result["unprotected"]
            if "confid" in udata:
                self._confid=udata["confid"]
                self._conf_obj=gconf.get_install_conf(self._confid, exception_if_not_found=False)
                if not self._conf_obj:
                    self._conf_obj=gconf.get_format_conf(self._confid, exception_if_not_found=False)

                self._creation_date=udata["creation-date"]
                attrs=[]
                for key in udata:
                    if key not in ("creation-date", "creation-date-ts", "confid", "verified"):
                        value=udata[key]
                        attrs+=["%s: %s"%(key, value)]
                self._attributes=attrs

                self._meta_verified=udata["verified"]

                self._data_partitions=[]
                is_data_part=False
                for partdata in ident_result["dev-format"]["partitions"]:
                    partid=partdata["id"]
                    if not is_data_part:
                        if partid in ("data", "internal"):
                            is_data_part=True
                    if is_data_part:
                        self._data_partitions+=[partdata]

        except Exception as e:
            raise Exception("CODEBUG: invalid 'inseca dev-ident' result")


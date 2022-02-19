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

import gi
gi.require_version("Gtk", "3.0")
gi.require_version('Pango', '1.0')
from gi.repository import Gtk

import Utils as util
import Configurations
import PluggedDevices as pdev
import Job as genjob
import Jobs as jobs

#
# support component UI
#
class Component:
    """Providing support for an already created INSECA installation"""
    def __init__(self, ui, builder):
        self._ui=ui
        self._page_widget=builder.get_object("infos")
        self._back_button=builder.get_object("back-button")
        self._infos_date=builder.get_object("infos-label-creation-date")
        self._infos_config=builder.get_object("infos-label-config")
        self._infos_extra=builder.get_object("infos-label-extra")
        self._infos_status=builder.get_object("infos-status")
        self._mounted_grid=builder.get_object("mounted-grid")

        self._combo_device=pdev.DevicesListUI(self._ui.plugged_devices_obj)
        grid=builder.get_object("infos-form")
        grid.attach(self._combo_device, 1, 0, 1, 1)
        self._combo_device.show()

        # extra buttons for actions
        bbox=builder.get_object("actions-bbox")
        self._live_linux_update_button=Gtk.Button(label="Update Live Linux")
        self._live_linux_update_button.connect("clicked", self._live_linux_update)
        bbox.add(self._live_linux_update_button)

        self._internal_page_change=False
        self._sid=None

    def page_shown_cb(self, page_widget):
        if self._internal_page_change:
            return
        if page_widget==self._page_widget:
            self._sid=self._combo_device.connect("changed", self._update_device_infos)
            self._update_device_infos(None)
        else:
            self._live_linux_update_button.hide()
            if self._sid is not None:
                self._sid=self._combo_device.disconnect(self._sid)
                self._sid=None

    def _live_linux_update(self, button):
        """Force the update of the Live Linux on the INSECA installation"""
        devinfo=self._combo_device.get_selected_devinfo()
        self._ui.show_message("Updating device")
        try:
            job=jobs.InsecaRunJob(["--verbose", "dev-update-linux", devinfo.devfile], "Updating device", self._ui.feedback_component)
            job.start()
            self._live_linux_update_button.set_sensitive(False)
            self._back_button.set_sensitive(False)

            job.wait_with_ui()
            if job.exception is not None:
                util.print_event("Failed: %s"%str(job.exception))
                raise job.exception
        except genjob.JobCancelled:
            self._ui.show_page("infos")
        except Exception as e:
            self._ui.show_error(str(e))
            self._ui.show_page("infos")
        finally:
            self._live_linux_update_button.set_sensitive(True)
            self._back_button.set_sensitive(True)
            self._ui.show_page("infos")

    def _update_device_infos(self, dummy):
        self._update_displayed_infos()

    def _update_displayed_infos(self):
        """Update a device's infos and returns the device's detected configuration"""
        # safe default display
        self._infos_date.set_text("N/A")
        self._infos_config.set_text("N/A")
        self._infos_extra.set_text("N/A")
        self._infos_status.set_text("N/A")
        self._live_linux_update_button.hide()

        def torem(child, container):
            container.remove(child)
        self._mounted_grid.foreach(torem, self._mounted_grid)
        self._mounted_grid.hide()

        # display actual device's associated data
        self._internal_page_change=True
        self._ui.show_message("Analysing device")
        try:
            devinfo=self._combo_device.get_selected_devinfo()
            if not devinfo:
                return

            self._back_button.set_sensitive(False)
            self._infos_date.set_text(devinfo.creation_date)

            conf=devinfo.config_obj
            if conf:
                if isinstance(conf, Configurations.InstallConfig):
                    self._live_linux_update_button.show()
                self._infos_config.set_text(conf.descr)
            else:
                self._infos_config.set_text("N/A")

            if devinfo.meta_verified:
                self._infos_status.set_markup("<span foreground=\"green\" weight=\"bold\">VERIFIED</span>")
            else:
                self._infos_status.set_markup("<span foreground=\"red\" weight=\"bold\">NOT VERIFIED</span>")

            if len(devinfo.attributes)>0:
                self._infos_extra.set_text("\n".join(devinfo.attributes))
            else:
                self._infos_extra.set_text("N/A")

            # data mount points
            if len(devinfo.data_partitions)>0:
                top=0
                for data_part in devinfo.data_partitions:
                    part_id=data_part["id"]
                    label="Partition %s"%data_part["devfile-ext"]
                    if data_part["encryption"]:
                        label+=", %s"%data_part["encryption"]
                    if data_part["filesystem"]:
                        label+=" (%s)"%data_part["filesystem"]
                    try:
                        mp=devinfo.get_mountpoint(part_id)
                    except:
                        mp=None
                    if mp:
                        link=Gtk.LinkButton(label=label)
                        link.set_uri("file://%s"%mp)
                        link.devinfo=devinfo
                        self._mounted_grid.attach(link, 0, top, 1, 1)
                    else:
                        label=Gtk.Label(label=label)
                        label.set_justify(Gtk.Justification.LEFT)
                        label.set_margin_end(10)
                        self._mounted_grid.attach(label, 0, top, 1, 1)
                    if mp:
                        button=Gtk.Button(label="umount")
                    else:
                        button=Gtk.Button(label="mount")

                    button.devinfo=devinfo
                    button.part_id=part_id
                    button.do_mount=False if mp else True
                    button.connect("clicked", self._mount_umount_cb)

                    self._mounted_grid.attach(button, 1, top, 1, 1)
                    top+=1
                self._mounted_grid.show_all()

        except Exception as e:
            self._ui.show_error(str(e))
            self._ui.show_page("infos")
        finally:
            self._back_button.set_sensitive(True)
            self._ui.show_page("infos")
            self._internal_page_change=False

    def _mount_umount_cb(self, button):
        """Mount or Umount a data partition"""
        devinfo=button.devinfo
        part_id=button.part_id
        self._internal_page_change=True
        self._ui.show_message("Mounting partition")
        try:
            self._live_linux_update_button.set_sensitive(False)
            if button.do_mount:
                print("Mounting %s"%devinfo.devfile)
                devinfo.mount(part_id)
            else:
                print("UMounting %s"%devinfo.devfile)
                devinfo.umount(part_id)
            # update the display
            self._update_displayed_infos()
        except genjob.JobCancelled:
            self._ui.show_page("infos")
        except Exception as e:
            self._ui.show_error(str(e))
            self._ui.show_page("infos")
        finally:
            self._live_linux_update_button.set_sensitive(True)
            self._back_button.set_sensitive(True)
            self._ui.show_page("infos")
            self._internal_page_change=False

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

import Jobs as jobs
import Utils as util
import PluggedDevices as pdev

#
# wipe component UI
#
class Component:
    """Allows one to erase everything on a device"""
    def __init__(self, ui, builder):
        self._ui=ui

        self._page_widget=builder.get_object("wipe")
        self._cancel_button=builder.get_object("cancel-button")
        self._back_button=builder.get_object("back-button")

        self._combo_device1=pdev.DevicesListUI(self._ui.plugged_devices_obj)
        grid=builder.get_object("wipe-form")
        grid.attach(self._combo_device1, 1, 0, 1, 1)
        self._combo_device1.show()
        self._combo_device1.connect("changed", self._device_changed_cb)

        self._combo_device2=pdev.DevicesListUI(self._ui.plugged_devices_obj)
        grid=builder.get_object("wipe-form")
        grid.attach(self._combo_device2, 1, 1, 1, 1)
        self._combo_device2.show()
        self._combo_device2.connect("changed", self._device_changed_cb)

        # extra buttons for actions
        bbox=builder.get_object("actions-bbox")
        self._wipe_button=Gtk.Button(label="Erase")
        self._wipe_button.connect("clicked", self._wipe_cb)
        bbox.add(self._wipe_button)
        self._wipe_button.set_sensitive(False)

    def page_shown_cb(self, page_widget):
        if page_widget==self._page_widget:
            self._wipe_button.show()
        else:
            self._wipe_button.hide()


    def _device_changed_cb(self, button):
        """Update the sensitiveness of the 'erase' button"""
        self._wipe_button.set_sensitive(False)
        devinfo1=self._combo_device1.get_selected_devinfo()
        if not devinfo1:
            return
        devinfo2=self._combo_device2.get_selected_devinfo()
        if devinfo1==devinfo2:
            self._wipe_button.set_sensitive(True)

    def _wipe_cb(self, button):
        """Actually erase a device"""
        devinfo1=self._combo_device1.get_selected_devinfo()
        if not devinfo1:
            return
        devinfo2=self._combo_device2.get_selected_devinfo()
        if devinfo1!=devinfo2:
            return

        self._ui.show_message("Erasing device")
        
        try:
            job=jobs.InsecaRunJob(["--verbose", "dev-wipe", "--confirm", devinfo1.devfile], "Erasing device", feedback_component=self._ui.feedback_component)
            job.start()

            self._wipe_button.hide()
            self._cancel_button.show()
            sid=self._cancel_button.connect("clicked", self._cancel_job, job)
            self._back_button.set_sensitive(False)

            job.wait_with_ui()
            if job.exception is not None:
                util.print_event("Failed: %s"%str(job.exception))
                raise job.exception
        except Exception as e:
            self._ui.show_error(str(e))
            self._ui.show_page("wipe")
        finally:
            self._back_button.set_sensitive(True)
            self._wipe_button.show()
            self._cancel_button.hide()
            self._cancel_button.disconnect(sid)
            self._ui.show_page("wipe")

    def _cancel_job(self, widget, job):
        job.cancel()
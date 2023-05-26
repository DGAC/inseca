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
import syslog
import Utils as util
import Sync
import Job
import Jobs as jobs
import Configurations

from gi.repository import GLib

util.print_events=True

#
# resources update UI
#
class Component:
    """Update (download) resources from the cloud or a local directory or mass storage device"""
    def __init__(self, ui, builder, live_context):
        self._ui=ui
        self._builder=builder
        self._page_widget=self._builder.get_object("resources")
        self._back_button=self._builder.get_object("back-button")
        self._repos_store_path=None
        self._internal_page_change=False
        self._update_counter=0
        self._nm=Sync.NetworkMonitor()
        GLib.timeout_add(1000, self._monitor_network_changes)
        self._ui.plugged_devices_obj.connect("changed", self._device_changed_cb)
        self._page_widget.connect("destroy", self._destroy_cb)
        self._context=live_context

    def _destroy_cb(self, dummy):
        self._nm.stop()

    def _get_gconf(self, force_reload=False):
        try:
            self._repos_store_path=None
            gconf=Configurations.get_gconf(force_reload)
            if not gconf.is_master:
                self._repos_store_path=os.environ["INSECA_DEFAULT_REPOS_DIR"]
            return gconf
        except Exception:
            return None

    def page_shown_cb(self, page_widget):
        """Callback function called when there is a notebook page change"""
        if page_widget==self._page_widget:
            if self._internal_page_change:
                return
            try:
                self._internal_page_change=True
                gconf=self._get_gconf()
                if not gconf or gconf.is_master:
                    # for master configuration, no download possible at all
                    self._builder.get_object("button-manage-resources").set_sensitive(False)
                else:
                    self._ui.show_page("message")
                    self._update_sync_capabilities()
            finally:
                self._ui.show_page("resources")
                self._internal_page_change=False

    def _monitor_network_changes(self):
        if self._nm.changed:
            syslog.syslog(syslog.LOG_INFO, "Network settings changed")
            self._update_sync_capabilities()
        return True # keep GLib's timer

    def _device_changed_cb(self, dummy):
        """Callback function called when the user inserted or removed a device
        """
        syslog.syslog(syslog.LOG_INFO, "Device plugged or unplugged")
        self._update_counter=10
        GLib.timeout_add(1000, self._update_sync_capabilities) # give time to the OS to mount the device's partitions

    def _update_sync_capabilities(self):
        # sync. with other INSECA admin device
        inseca_button=self._builder.get_object("button_sync_other_inseca")
        inseca_button.set_sensitive(self._ui.other_inseca_devfile is not None)

        # download from cloud or "local" directory
        cloud_button=self._builder.get_object("button_sync_cloud")
        cloud_button.set_sensitive(False)
        local_button=self._builder.get_object("button_sync_local")
        local_button.set_sensitive(False)

        gconf=self._get_gconf()
        if gconf:
            self._sync_objects=gconf.get_all_sync_objects(way_out=False)
        else:
            self._sync_objects=[]

        if gconf.is_master:
            # for master configuration, no download possible at all
            self._builder.get_object("button-manage-resources").set_sensitive(False)
        else:
            # update buttons' sensitivity depending on configurations being useable
            for sobj in self._sync_objects:
                if sobj.is_local:
                    if sobj.is_available:
                        local_button.set_sensitive(True)
                else:
                    if sobj.is_available:
                        cloud_button.set_sensitive(True)
        self._update_counter-=1
        if self._update_counter<=0:
            self._update_counter=0
            return False # remove GLib's timer, if any
        else:
            return True # keep GLib's timer

    def update_stats(self):
        label=self._builder.get_object("resources-stats")
        label.set_text("")
        # TODO

    def _update_configuration(self, sync_obj):
        """Uses the DOMAIN repositories to create a new global configuration, replacing the previous one if no error occurred"""
        if self._repos_store_path is None:
            raise Exception("CODEBUG: self._repos_store_path is None")
        if sync_obj is None:
            raise Exception("CODEBUG: situation should not happen")
        try:
            self._ui.show_message("Downloading and extracting resources")
            self._back_button.set_sensitive(False)

            job=jobs.InsecaRunJob(["--verbose", "sync-pull", sync_obj.name], "Mise à jour de la configuration",
                                  feedback_component=self._ui.feedback_component, live_context=self._context)
            job.start()
            job.wait_with_ui()
            if job.exception is not None:
                util.print_event("Failed: %s"%str(job.exception))
                raise job.exception

        except Exception as e:
            self._ui.show_error(str(e))
        finally:
            self._back_button.set_sensitive(True)
            self._ui.show_page("resources")

    def download_cloud(self):
        """Download repos from the cloud"""
        # use the 1st available sync. object
        for sobj in self._sync_objects:
            if not sobj.is_local:
                if sobj.is_available:
                    self._update_configuration(sobj)
                    return
        self._ui.show_error("No Cloud configuration available")

    def download_local(self):
        """Downloads repos from a 'local' directory (which can also be a plugged mass storage device)"""
        # use the 1st available sync. object
        for sobj in self._sync_objects:
            if sobj.is_local:
                if sobj.is_available:
                    self._update_configuration(sobj)
                    return
        self._ui.show_error("No local configuration available")

    def sync_other_inseca_device(self):
        """Synchronize repos using another INSECA admin device, in a way that the most recent
        versions of any repos is on both devices"""
        print("TODO")

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
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

import CryptoGen as cgen
import Jobs as jobs
import Utils as util

#
# component to change the proxy settings
#
class Component:
    """Allow one to define HTTP proxy settings"""
    def __init__(self, ui, builder, live_context):
        self._ui=ui
        self._context=live_context

        self._page_widget=builder.get_object("proxy-settings")
        self._proxy_rb_auto=builder.get_object("proxy_rb_auto")
        self._proxy_rb_manual=builder.get_object("proxy_rb_manual")
        self._proxy_rb_none=builder.get_object("proxy_rb_none")
        self._proxy_http_entry=builder.get_object("http_proxy_entry")

        if self._context:
            self._proxy_rb_auto.connect("toggled", self._rb_toggled_cb)
            self._proxy_rb_manual.connect("toggled", self._rb_toggled_cb)
            self._proxy_rb_none.connect("toggled", self._rb_toggled_cb)
            self._proxy_http_entry.connect("changed", self._entry_changed)

            proxy=os.environ.get("http_proxy")
            if proxy:
                if proxy=="none":
                    self._proxy_rb_none.set_active(True)
                else:
                    self._proxy_http_entry.set_text(proxy)
                    self._proxy_rb_manual.set_active(True)
            else:
                self._proxy_rb_auto.set_active(True)
        else:
            self._proxy_rb_auto.set_active(True)

    def _handle_proxy_value(self):
        proxy=self._proxy_http_entry.get_text()
        if proxy.startswith("http://") or proxy.startswith("https://"):
            self._context.set_http_proxy(util.ProxyMode.MANUAL, proxy)
            os.environ["INSECA_NO_HTTP_PROXY"]=""
        else:
            self._context.set_http_proxy(util.ProxyMode.NONE, None)
            os.environ["INSECA_NO_HTTP_PROXY"]="1"

    def _rb_toggled_cb(self, rb):
        if not rb.get_active():
            return # we don't care about the "untoggle" signal of a radio button
        if rb==self._proxy_rb_auto:
            self._proxy_http_entry.set_sensitive(False)
            self._context.set_http_proxy(util.ProxyMode.AUTO, None)
            os.environ["INSECA_NO_HTTP_PROXY"]="0"
        elif rb==self._proxy_rb_manual:
            self._proxy_http_entry.set_sensitive(True)
            self._handle_proxy_value()
        else:
            self._proxy_http_entry.set_sensitive(False)
            self._context.set_http_proxy(util.ProxyMode.NONE, None)
            os.environ["INSECA_NO_HTTP_PROXY"]="1"
    
    def _entry_changed(self, dummy):
        """Called when an entry to define the password has been changed"""
        self._handle_proxy_value()
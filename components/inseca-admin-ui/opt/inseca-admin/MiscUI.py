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
from gi.repository import GObject
from gi.repository import Gtk
from gi.repository import GdkPixbuf

import CryptoGen as cgen
import Filesystem as filesystem

def create_label_widget(pspec):
    label=Gtk.Label(label="%s:"%pspec["descr"])
    label.set_justify(Gtk.Justification.RIGHT)
    label.set_halign(Gtk.Align.END)
    label.set_valign(Gtk.Align.START)
    return label

class StrEntry(Gtk.Entry):
    """Simple UI entry for strings"""
    __gsignals__ = {
        "data_changed": (GObject.SIGNAL_RUN_FIRST, None, ())
    }
    def __init__(self, spec):
        Gtk.Entry.__init__(self)
        self._spec=spec
        self.connect("changed", self._changed_cb)
        if "value" in self._spec:
            self.set_text(str(self._spec["value"]))

    def _changed_cb(self, dummy):
        self.emit("data_changed")

    def get_value(self):
        return self.get_text()

class PasswordEntry(Gtk.VBox):
    """UI entry for passwords"""
    __gsignals__ = {
        "data_changed": (GObject.SIGNAL_RUN_FIRST, None, ())
    }

    def __init__(self, spec):
        Gtk.VBox.__init__(self)
        self._spec=spec
        self._pass0=self._create_password_entry()
        label=Gtk.Label(label="+ confirmation")
        label.set_halign(Gtk.Align.START)
        self.add(label)
        self._pass1=self._create_password_entry()

        self._pass0.connect("changed", self._changed_cb)
        self._pass1.connect("changed", self._changed_cb)

    def _changed_cb(self, dummy):
        self.emit("data_changed")

    def _icon_pressed(self, entry, icon_pos, event, dummy):
        entry.set_visibility(True)

    def _icon_released(self, entry, icon_pos, event, dummy):
        entry.set_visibility(False)

    def _create_password_entry(self):
        pentry=Gtk.Entry()
        pentry.set_visibility(False)
        self.add(pentry)
        pix=GdkPixbuf.Pixbuf.new_from_file("eye.png")
        pentry.set_icon_from_pixbuf(Gtk.EntryIconPosition.SECONDARY, pix)
        pentry.connect("icon-press", self._icon_pressed, None)
        pentry.connect("icon-release", self._icon_released, None)
        return pentry

    def get_value(self):
        p0=self._pass0.get_text()
        p1=self._pass1.get_text()
        if p0=="":
            raise Exception("No password specified")
        cgen.validate_password(p0)
        if p0!=p1:
            raise Exception("Passwords mismatch")
        return p0

class IntEntry(Gtk.Entry):
    """Simple UI entry for integers"""
    _gsignals__ = {
        "data_changed": (GObject.SIGNAL_RUN_FIRST, None, ())
    }
    def __init__(self, spec):
        Gtk.Entry.__init__(self)
        self._spec=spec
        self.connect("changed", self._changed_cb)
        if "value" in self._spec:
            self.set_text(str(self._spec["value"]))

    def _changed_cb(self, dummy):
        self.emit("data_changed")

    def get_value(self):
        value=self.get_text()
        try:
            int(value)
            return value
        except:
            raise Exception("%s: invalid value"%self._spec["descr"])

class ComboEntry(Gtk.ComboBoxText):
    """UI entry for multiple choices"""
    __gsignals__ = {
        "data_changed": (GObject.SIGNAL_RUN_FIRST, None, ())
    }
    def __init__(self, spec):
        Gtk.ComboBoxText.__init__(self)
        self._spec=spec
        for entry in spec["choices"]:
            self.append_text(entry)
        self.connect("changed", self._changed_cb)

    def _changed_cb(self, dummy):
        self.emit("data_changed")

    def get_value(self):
        return self.get_active_text()

class EncTypeEntry(Gtk.ComboBoxText):
    """UI entry to select an encryption type"""
    __gsignals__ = {
        "data_changed": (GObject.SIGNAL_RUN_FIRST, None, ())
    }
    _mapping={
        "LUKS (Linux)": "luks",
        "VeraCrypt": "veracrypt"
    }
    def __init__(self, spec):
        Gtk.ComboBoxText.__init__(self)
        self._spec=spec
        default_value=None
        index=0
        if "default" in spec:
            default_value=spec["default"]
        for key in EncTypeEntry._mapping:
            self.append_text(key)
            if EncTypeEntry._mapping[key]==default_value:
                self.set_active(index)
            index+=1
        self.connect("changed", self._changed_cb)

    def _changed_cb(self, dummy):
        self.emit("data_changed")

    def get_value(self):
        return EncTypeEntry._mapping[self.get_active_text()]

class FilesystemEntry(Gtk.ComboBoxText):
    """UI entry to select a filesystem type"""
    __gsignals__ = {
        "data_changed": (GObject.SIGNAL_RUN_FIRST, None, ())
    }
    def __init__(self, spec):
        Gtk.ComboBoxText.__init__(self)
        self._spec=spec
        default_value=None
        index=0
        if "default" in spec:
            default_value=filesystem.fstype_from_string(spec["default"])
        for fs in filesystem.FSType:
            descr=filesystem.fstype_to_description(fs)
            self.append_text(descr)
            if fs==default_value:
                self.set_active(index)
            index+=1
        self.connect("changed", self._changed_cb)

    def _changed_cb(self, dummy):
        self.emit("data_changed")

    def get_value(self):
        text=self.get_active_text()
        for fs in filesystem.FSType:
            if filesystem.fstype_to_description(fs)==text:
                return fs.value

class TODOEntry(Gtk.Label):
    """UI entry holder for future work"""
    __gsignals__ = {
        "data_changed": (GObject.SIGNAL_RUN_FIRST, None, ())
    }
    def __init__(self, spec):
        Gtk.Label.__init__(self, label="TODO")

    def get_value(self):
        return "TODO"

def create_param_entry(pspec):
    ptype=pspec["type"]
    if ptype=="str":
        widget=StrEntry(pspec)
    if ptype=="password":
        widget=PasswordEntry(pspec)
    elif ptype=="int":
        widget=IntEntry(pspec)
    elif ptype=="timestamp":
        print("TODO (timestamp pspec): %s"%pspec)
        widget=TODOEntry(pspec)
    elif ptype=="size-mb":
        print("TODO (size-mb pspec): %s"%pspec)
        widget=TODOEntry(pspec)
    elif ptype=="filesystem":
        widget=FilesystemEntry(pspec)
    elif ptype=="file":
        print("TODO (file pspec): %s"%pspec)
        widget=TODOEntry(pspec)
    elif ptype=="combo":
        widget=ComboEntry(pspec)
    elif ptype=="encryptiontype":
        widget=EncTypeEntry(pspec)
    return widget

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

import os
import json
import Utils as util
import ValueHolder as valh

auto_variables={
    "_dev": {
        "descr": "File device to use",
        "type": "file"
    },
    "_model": {
        "descr": "Device HW model",
        "type": "str"
    },
    "_serial": {
        "descr": "Device HW serial number",
        "type": "str"
    }
}

def _validate_dict(data, keywords):
    for key in data:
        if key not in keywords:
            raise Exception("Invalid key '%s'"%key)
        (typ, can_be_none)=keywords[key]
        if data[key]==None:
            if not can_be_none:
                raise Exception("Invalid None value for key '%s'"%key)

def _validate_template(templ):
    for key in ["descr", "parameters", "dev-format"]:
        if key not in templ:
            raise Exception("Missing top level key '%s'"%key)
    if not isinstance(templ["descr"], str):
        raise Exception("Invalid description '%s'"%templ["descr"])
    if not isinstance(templ["parameters"], dict):
        raise Exception("Invalid parameters section")
    if not isinstance(templ["dev-format"], dict):
        raise Exception("Invalid dev-format section")

    # parameters
    for pname in templ["parameters"]:
        pspec=templ["parameters"][pname]
        for key in ["descr", "type"]:
            if key not in pspec:
                raise Exception("Missing key '%s' for parameter '%s'"%(key, pname))
            ptype=pspec["type"]
            if ptype not in ("int", "str", "filesystem", "timestamp", "date", "file", "password", "size-mb"):
                raise Exception("Invalid type '%s' for parameter '%s'"%(ptype, pname))

    # specifications
    specs=templ["dev-format"]
    for key in ["device", "type", "partitions", "unprotected", "protected", "decryptors", "signatures"]:
        if key not in specs:
            raise Exception("Missing key '%s' in specifications"%key)
    if not isinstance(specs["device"], str):
        raise Exception("Invalid device filename '%s'"%specs["device"])
    if specs["type"] not in ("gpt", "dos", "hybrid"):
        raise Exception("Invalid device type '%s'"%specs["type"])

    # partitions
    # the format for each value is: [type, can the value be None?]
    keywords0={
        "leave-existing": [str, False],
        "size-mb": [int, True],
    }
    keywords1={
        "iso-file": [str, False],
        "size-mb": [int, True],
    }
    keywords2={
        "id": [str, False],
        "type": [str, True],
        "label": [str, False],
        "volume-id": [str, True],
        "encryption": [str, True],
        "immutable": [bool, False],
        "filesystem": [str, True],
        "password": [str, True],
        "size-mb": [int, True],
    }
    partitions={}
    for pspec in specs["partitions"]:
        if "leave-existing" in pspec:
            _validate_dict(pspec, keywords0)
        elif "iso-file" in pspec:
            _validate_dict(pspec, keywords1)
        else:
            _validate_dict(pspec, keywords2)
            if len(pspec)!=len(keywords2):
                raise Exception("Missing some keys or too many keys in partition spec %s"%pspec)
            partitions[pspec["id"]]=pspec

    # hybrid MBR checks
    if specs["type"]=="hybrid":
        if "hybrid-partitions" not in specs:
            raise Exception("Missing 'hybrid-partitions' information")
        if len(specs["hybrid-partitions"])==0 or len(specs["hybrid-partitions"])>3:
            raise Exception("Invalid number of partitions specified in the hybrid MBR")
        for part_id in specs["hybrid-partitions"]:
            if part_id not in partitions:
                raise Exception("Unidentified partition '%s' referenced to be included in the hybrid MBR"%part_id)
    elif "hybrid-partitions" in specs:
        raise Exception("Useless 'hybrid-partitions' information")

    # unprotected part
    for key in specs["unprotected"]:
        if not isinstance(specs["unprotected"][key], str):
            raise Exception("Invalid unprotected information '%s'"%key)

    # protected part
    protection_keys=[]
    for key in specs["protected"]:
        protection_keys+=[key]
        if not isinstance(specs["protected"][key], dict):
            raise Exception("Invalid protected information '%s'"%key)
        for skey in specs["protected"][key]:
            if not isinstance(skey, str):
                raise Exception("Invalid protected item key '%s'"%skey)
            svalue=specs["protected"][key][skey]
            if not isinstance(skey, str):
                raise Exception("Invalid protected item value '%s' for key '%s'"%(svalue, skey))
            if skey[0]=="@":
                parts=skey[1:].split("/")
                if len(parts)!=2:
                    raise Exception("Invalid protected item value key '%s'"%skey)
                part_id=parts[0]
                what=parts[1]
                if part_id not in partitions:
                    raise Exception("Invalid partition reference '%s'"%part_id)
                if what!="header" and what not in partitions[part_id]:
                    raise Exception("Invalid protected reference '%s'"%svalue)
                if svalue!=None:
                    raise Exception("Invalid protected value '%s' for key '%'"%(svalue, skey))

    # make sure all the parameters referenced in the specs are actually defined as parameters
    _validate_variables(templ["dev-format"], templ["parameters"], auto_variables)

def _validate_variables(data, parameters, automatic_variables=None):
    if automatic_variables is None:
        automatic_variables={}
    if isinstance(data, str):
        variables=valh.get_variables_in_string(data)
        if len(variables)!=0:
            for var in variables:
                var=var[1:-1]
                if var not in parameters and var not in automatic_variables:
                    raise Exception("No parameter defined for variable '%s'"%var)
    elif isinstance(data, dict):
        for key in data:
            _validate_variables(data[key], parameters, automatic_variables)
    elif isinstance(data, list):
        for key in data:
            _validate_variables(key, parameters, automatic_variables)

class Builder():
    """Builds specifications from a template and user provided information"""
    def __init__(self, devfile, template):
        if not os.path.exists(template):
            raise Exception("Template '%s' does not exist"%template)
        self._tmpl=json.loads(util.load_file_contents(template))
        _validate_template(self._tmpl)
        self._params=self._tmpl["parameters"]
        self._params.update(auto_variables)
        self._specifications=self._tmpl["dev-format"]
        self._param_values={}
        self._devfile=devfile
        self._is_physical=self._devfile.startswith("/dev/")

        self.set_parameter_value("_dev", devfile)
        if self._is_physical:
            serial=util.get_device_serial(devfile)
            self.set_parameter_value("_serial", serial)
            model=util.get_device_model(devfile)
            self.set_parameter_value("_model", model)
        else:
            self.set_parameter_value("_serial", "")
            self.set_parameter_value("_model", "VM image file")
        
    def get_parameters(self):
        return self._params

    def set_parameter_value(self, name, value, rel_dir=None):
        if name in self._params:
            pspec=self._params[name]
            try:
                if pspec["type"]=="timestamp": # expected YYYY-MM-DD HH:MM:SS
                    import datetime
                    datetime.datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
                elif pspec["type"]=="date": # expected YYYY-MM-DD
                    import datetime
                    datetime.datetime.strptime(value, '%Y-%m-%d')
                elif pspec["type"]=="filesystem":
                    import Filesystem as fs
                    fs.fstype_from_string(value)
                elif pspec["type"]=="size-mb" or pspec["type"]=="int":
                    value=int(value)
                elif pspec["type"]=="file":
                    if rel_dir is not None:
                        value="%s/%s"%(rel_dir, value)
                    if not os.path.exists(value):
                        raise Exception("File does not exist")
                self._param_values[name]=value
            except Exception as e:
                raise Exception("Invalid value '%s' for parameter '%s': %s"%(value, name, str(e)))
        else:
            print("** Unknown parameter '%s'"%name)
            #raise Exception("Unknown parameter '%s'"%name)

    def get_specifications(self):
        """Get the actual specifications"""
        for avar in auto_variables:
            if avar not in self._param_values:
                raise Exception("Parameter '%s' has not been defined"%avar)
        return valh.replace_variables(self._specifications, self._param_values)

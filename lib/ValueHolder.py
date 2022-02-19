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

import re

def get_variables_in_string(string):
    """Get the list of variables in the string passed as argument"""
    if not isinstance(string, str):
        raise Exception("Expected @string to be a string, got a %s"%type(string))
    return re.findall(r'\{!?[a-zA-Z0-9_-]{1,}(?:=[^"\'=}]*)?\}', string)

def _expand_variables_in_string(string, variables, ignore_missing=False):
    """Modifies the input string to replace any reference to a variable defined in the @variables dictionary.

    A variable has the following format: "{" <var name> "}"
    NB: an exception is raised if a variable referenced in the string cannot be found
    """
    if not isinstance(variables, dict):
        raise Exception("Expected @variables to be a dictionary, got a %s"%type(variables))

    allvars=get_variables_in_string(string)
    for var in allvars:
        rvar=var[1:-1]

        if rvar[0]=="!":
            string=string.replace(var, "{%s}"%rvar[1:])
            continue # ignore this variable

        default=None
        if "=" in rvar:
            (rvar, default)=rvar.split("=")

        if rvar in variables:
            if variables[rvar]==None:
                string=string.replace(var, "")
            else:
                if isinstance(variables[rvar], int):
                    string=variables[rvar]
                else:
                    string=string.replace(var, str(variables[rvar]))
        elif default!=None:
            string=string.replace(var, default)
        else:
            if not ignore_missing:
                raise Exception("Can't expand unknown variable '%s'" % rvar)
    return string

def replace_variables(data, values, ignore_missing=False):
    """Replace any variable in @data"""
    if isinstance(data, str):
        return _expand_variables_in_string(data, values, ignore_missing)
    elif isinstance(data, dict):
        ndata={}
        for key in data:
            ndata[key]=replace_variables(data[key], values, ignore_missing)
        return ndata
    elif isinstance(data, list):
        ndata=[]
        for key in data:
            ndata+=[replace_variables(key, values, ignore_missing)]
        return ndata
    return data

#!/usr/bin/python3

# This file is part of INSECA.
#
#    Copyright (C) 2022 INSECA authors
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
import json
import Utils as util
import ValueHolder as vh

# create the /etc/docker/daemon.json file in PRIVDATA_DIR
conf=json.load(open(os.environ["CONF_DATA_FILE"], "r"))
if conf:
    key="docker-bip"
    if key in conf:
        data={
            "bip": conf[key]
        }
        destdir="%s/etc/docker"%os.environ["PRIVDATA_DIR"]
        os.makedirs(destdir, exist_ok=True)
        util.write_data_to_file(json.dumps(data), "%s/daemon.json"%destdir, perms=0o600)

# take l10n settings into account
config_timezone=os.environ["L10N_TIMEZONE"]
config_locale=os.environ["L10N_LOCALE"]
config_kb_layout=os.environ["L10N_KB_LAYOUT"]
config_kb_model=os.environ["L10N_KB_MODEL"]
config_kb_variant=os.environ["L10N_KB_VARIANT"]
config_kb_option=os.environ["L10N_KB_OPTION"]
value=f"timezone={config_timezone} lang={config_locale} locales={config_locale}"
if config_kb_layout:
    value+=f" keyboard-layouts={config_kb_layout}"
if config_kb_model:
    value+=f" keyboard-model={config_kb_model}"
if config_kb_variant:
    value+=f" keyboard-variants={config_kb_variant}"
if config_kb_option:
    value+=f" keyboard-options={config_kb_option}"
util.write_data_to_file(f"L10N: {value}\n", os.environ["BUILD_DATA_FILE"], append=True)

build_dir=os.environ["BUILD_DIR"]
config_file=f"{build_dir}/auto/config"
data=util.load_file_contents(config_file)
data=vh.replace_variables(data, {
    "l10n": value
})
util.write_data_to_file(f"auto/config: {config_file}\n", os.environ["BUILD_DATA_FILE"], append=True)
util.write_data_to_file(data, config_file)
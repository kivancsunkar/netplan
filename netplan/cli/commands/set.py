#!/usr/bin/python3
#
# Copyright (C) 2020 Canonical, Ltd.
# Author: Lukas Märdian <lukas.maerdian@canonical.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 3.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

'''netplan set command line'''

import os
import yaml
import tempfile
import re

import netplan.cli.utils as utils
from netplan.configmanager import ConfigManager


class NetplanSet(utils.NetplanCommand):

    def __init__(self):
        super().__init__(command_id='set',
                         description='Add new setting by specifying a dotted key=value pair like ethernets.eth0.dhcp4=true',
                         leaf=True)

    def run(self):
        self.parser.add_argument('key_value', type=str,
                                 help='The nested key=value pair in dotted format. Value can be NULL to delete a key.')
        self.parser.add_argument('--origin-hint', type=str,
                                 help='Can be used to help choose a name for the overwrite YAML file. \
                                       A .yaml suffix will be appended automatically.')
        self.parser.add_argument('--root-dir', default='/',
                                 help='Overwrite configuration files in this root directory instead of /')

        self.func = self.command_set

        self.parse_args()
        self.run_command()

    def command_set(self):
        split = self.key_value.split('=', 1)
        if len(split) != 2:
            raise Exception('Invalid value specified')
        key, value = split
        # The 'network.' prefix is optional for netsted keys, its always assumed to be there
        if not key.startswith('network.'):
            key = 'network.' + key

        if self.origin_hint is None:
            hint = None
            # Split at '.' but not at '\.' via negative lookbehind expression
            key_split = re.split(r'(?<!\\)\.', key)
            if len(key_split) >= 3:
                netdef_id = key_split[2].replace('\\.', '.')  # Unescape interface-ids, containing dots
                filename = utils.netplan_get_filename_by_id(netdef_id, self.root_dir)
                print(netdef_id, filename)
                if filename:
                    hint = os.path.basename(filename)[:-5]  # strip prefix and .yaml
            if hint:
                self.origin_hint = hint
            else:
                self.origin_hint = '70-netplan-set'
        elif len(self.origin_hint) == 0:
            raise Exception('Invalid/empty origin-hint')

        set_tree = self.parse_key(key, yaml.safe_load(value))
        self.write_file(set_tree, self.origin_hint + '.yaml', self.root_dir)

    def parse_key(self, key, value):
        # Split at '.' but not at '\.' via negative lookbehind expression
        split = re.split(r'(?<!\\)\.', key)
        tree = {}
        i = 1
        t = tree
        for part in split:
            part = part.replace('\\.', '.')  # Unescape interface-ids, containing dots
            val = {}
            if i == len(split):
                val = value
            t = t.setdefault(part, val)
            i += 1
        return tree

    def merge(self, a, b, path=None):
        """
        Merges tree/dict 'b' into tree/dict 'a'
        """
        if path is None:
            path = []
        for key in b:
            if key in a:
                if isinstance(a[key], dict) and isinstance(b[key], dict):
                    self.merge(a[key], b[key], path + [str(key)])
                elif b[key] is None:
                    del a[key]
                else:
                    # Overwrite existing key with new key/value from 'set' command
                    a[key] = b[key]
            else:
                a[key] = b[key]
        return a

    def write_file(self, set_tree, name, rootdir='/'):
        tmproot = tempfile.TemporaryDirectory(prefix='netplan-set_')
        path = os.path.join('etc', 'netplan')
        os.makedirs(os.path.join(tmproot.name, path))

        config = {'network': {}}
        absp = os.path.join(rootdir, path, name)
        if os.path.isfile(absp):
            with open(absp, 'r') as f:
                config = yaml.safe_load(f)

        new_tree = self.merge(config, set_tree)
        stripped = ConfigManager.strip_tree(new_tree)
        if 'network' in stripped and list(stripped['network'].keys()) == ['version']:
            # Clear file if only 'network: {version: 2}' is left
            os.remove(absp)
        elif 'network' in stripped:
            tmpp = os.path.join(tmproot.name, path, name)
            with open(tmpp, 'w+') as f:
                new_yaml = yaml.dump(stripped, indent=2, default_flow_style=False)
                f.write(new_yaml)
            # Validate the newly created file, by parsing it via libnetplan
            utils.netplan_parse(tmpp)
            # Valid, move it to final destination
            os.replace(tmpp, absp)
        elif os.path.isfile(absp):
            # Clear file if the last/only key got removed
            os.remove(absp)
        else:
            raise Exception('Invalid input: {}'.format(set_tree))

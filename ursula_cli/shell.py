#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2015, Craig Tracey <craigtracey@gmail.com>
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations

import argparse
import logging
import os
import shutil
import subprocess
import sys
import time
import yaml

LOG = logging.getLogger(__name__)
ANSIBLE_VERSION = '1.7.2-bbg'


def _initialize_logger(level=logging.DEBUG, logfile=None):
    global LOG
    LOG.setLevel(level)

    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(levelname)s: %(message)s")
    handler.setFormatter(formatter)
    LOG.addHandler(handler)


def _check_ansible_version():
    process = subprocess.Popen(
        ["ansible-playbook --version"], shell=True,
        stdout=subprocess.PIPE)
    output, _ = process.communicate()
    retcode = process.poll()
    if retcode:
        raise Exception("Error discovering ansible version")
    version_output = output.split('\n')[0]
    version = version_output.split(' ')[1]
    if not version == ANSIBLE_VERSION:
        raise Exception("You are not using ansible-playbook '%s'. "
                        "Current required version is: '%s'. You may install "
                        "the correct version with 'pip install -U -r "
                        "requirements.txt'" % (version, ANSIBLE_VERSION))


def _append_envvar(key, value):
    if key in os.environ:
        os.environ[key] = "%s %s" % (os.environ[key], value)
    else:
        _set_envvar(key, value)


def _set_envvar(key, value):
    os.environ[key] = value


def _set_default_env():
    _append_envvar('PYTHONUNBUFFERED', '1')  # needed in order to stream output
    _append_envvar('PYTHONIOENCODING', 'UTF-8')  # needed to handle stdin input
    _append_envvar('ANSIBLE_FORCE_COLOR', 'yes')
    _append_envvar('ANSIBLE_SSH_ARGS', '-o ControlMaster=auto')
    _append_envvar("ANSIBLE_SSH_ARGS",
                   "-o ControlPath=~/.ssh/controlmasters/u-%r@%h:%p")
    _append_envvar("ANSIBLE_SSH_ARGS", "-o ControlPersist=300")


def _run_ansible(inventory, playbook, user='root', module_path='./library',
                 sudo=False, extra_args=[]):
    command = [
        'ansible-playbook',
        '--inventory-file',
        inventory,
        '--user',
        user,
        '--module-path',
        module_path,
        playbook,
    ]

    if sudo:
        command.append("--sudo")
    command += extra_args

    LOG.debug("Running command: %s with environment: %s",
              " ".join(command), os.environ)
    proc = subprocess.Popen(command, env=os.environ.copy(), shell=False,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)

    for line in iter(proc.stdout.readline, b''):
        print line.rstrip()

    proc.communicate()[0]
    return proc.returncode


def _create_vagrant_ssh_config(environment, boxes):
    output = ""
    for box in boxes:
        command = [
          'vagrant',
          'ssh-config',
          box
        ]
        proc = subprocess.Popen(command, env=os.environ.copy(),
                                shell=False,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT)

        for line in iter(proc.stdout.readline, b''):
            output += "%s\n" % line.rstrip()

        if proc.returncode:
            raise Exception("Failed to create SSH config")
            return proc.returncode

    return output

def _vagrant_ssh_config(environment,boxes):
    ssh_config = _create_vagrant_ssh_config(environment, boxes)
    while ssh_config[:4] != "Host":
        time.sleep(5)
        ssh_config = _create_vagrant_ssh_config(environment, boxes)

    ssh_config_file = ".vagrant/%s.ssh" % os.path.basename(environment)
    f = open(ssh_config_file, 'w')
    f.write(ssh_config)
    f.close()
    _append_envvar("ANSIBLE_SSH_ARGS", "-F %s" % ssh_config_file)

def _run_vagrant(environment):
    vagrant_config_file = os.path.join(environment, 'vagrant.yml')

    if os.path.isfile(vagrant_config_file):
        _set_envvar("SETTINGS_FILE", vagrant_config_file)
        vagrant_config = yaml.load(open(vagrant_config_file, 'r'))
        shutil.copy(vagrant_config_file,
                    os.path.join(".vagrant/vagrant.yml"))
    else:
        vagrant_config = yaml.load(open('vagrant.yml', 'r'))

    vms = vagrant_config['vms'].keys()

    command = [
        'vagrant',
        'up',
        '--no-provision',
    ] + vagrant_config['vms'].keys()

    LOG.debug("Running command: %s\nEnvs:%s", " ".join(command), os.environ)
    proc = subprocess.Popen(command, env=os.environ.copy(),
                            shell=False,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)

    for line in iter(proc.stdout.readline, b''):
        print line.rstrip()

    if proc.returncode:
        raise Exception("Failed to run %s with environment: %s"
                        % " ".join(command), os.environ)
        return proc.returncode
    else:
        rc = _vagrant_ssh_config(environment, vms)
        if rc:
            return rc
        print "**************************************************"
        print "Ursula <3 Vagrant"
        print "To interact with your environment via Vagrant set:"
        print "$ export SETTINGS_FILE=%s" % vagrant_config_file
        print "**************************************************"

    return 0


def run(args, extra_args):
    _set_default_env()

    if not os.path.exists(args.environment):
        raise Exception("Environment '%s' does not exist", args.environment)

    _set_envvar('URSULA_ENV', os.path.abspath(args.environment))

    inventory = os.path.join(args.environment, 'hosts')
    if not os.path.exists(inventory) or not os.path.isfile(inventory):
        raise Exception("Inventory file '%s' does not exist", inventory)

    ansible_var_defaults_file = os.path.join(args.environment,
                                             '../defaults.yml')
    if os.path.isfile(ansible_var_defaults_file):
        _append_envvar("ANSIBLE_VAR_DEFAULTS_FILE", ansible_var_defaults_file)

    ansible_ssh_config_file = os.path.join(args.environment, 'ssh_config')
    if os.path.isfile(ansible_ssh_config_file):
        _append_envvar("ANSIBLE_SSH_ARGS", "-F %s" % ansible_ssh_config_file)

    if args.ursula_forward:
        _append_envvar("ANSIBLE_SSH_ARGS", "-o ForwardAgent=yes")

    if args.ursula_test:
        extra_args += ['--syntax-check', '--list-tasks']

    if args.vagrant:
        extra_args += ['-s', '-u', 'vagrant']
        rc = _run_vagrant(environment=args.environment)
        if rc:
            return rc

    rc = _run_ansible(inventory, args.playbook, extra_args=extra_args)
    return rc


def main():
    parser = argparse.ArgumentParser(description='A CLI wrapper for ansible')
    parser.add_argument('environment', help='The environment you want to use')
    parser.add_argument('playbook', help='The playbook to run')

    # any args should be namespaced --ursula-$SOMETHING so as not to conflict
    # with ansible-playbook's command line parameters
    parser.add_argument('--ursula-forward', action='store_true',
                        help='The playbook to run')
    parser.add_argument('--ursula-test', action='store_true',
                        help='Test syntax for playbook')
    parser.add_argument('--ursula-debug', action='store_true',
                        help='Run this tool in debug mode')
    parser.add_argument('--vagrant', action='store_true',
                        help='Provision environment in vagrant')

    args, extra_args = parser.parse_known_args()

    try:
        log_level = logging.INFO
        if args.ursula_debug:
            log_level = logging.DEBUG
        _initialize_logger(log_level)
        _check_ansible_version()
        rc = run(args, extra_args)
        sys.exit(rc)
    except Exception as e:
        LOG.error(e)
        sys.exit(-1)


if __name__ == '__main__':
    main()

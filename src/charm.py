#!/usr/bin/env python3

import logging

from charmhelpers.core import (
    host
)
from charmhelpers.core.templating import render
from charmhelpers.fetch import (
    apt_install, add_source, apt_update, add_source)

from ops.charm import CharmBase
from ops.main import main
from ops.framework import StoredState
from ops.model import (
    ActiveStatus,
    BlockedStatus,
    MaintenanceStatus,
)
import os
from pathlib import Path
import requests
import subprocess
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

REQUIRED_JUJU_CONFIG = ['site-name']


class DrupalCharmJujuConfigError(Exception):
    """Exception when the Juju config is bad."""


class DrupalCharm(CharmBase):

    _stored = StoredState()


    def __init__(self, *args):
        super().__init__(*args)
        self.name = self.app.name
        self.this_unit = self.model.unit
        db_data = {
            'database': None,
            'username': None,
            'password': None,
            'db_host': None
        }
        self._stored.set_default(installed=False, site_root_created=False,
                                 db_connected=False, db_data=db_data)

        self.framework.observe(self.on.install, self.on_install)
        self.framework.observe(self.on.start, self.configure_charm)
        self.framework.observe(self.on.config_changed, self.configure_charm)

        # Database relations
        self.framework.observe(self.on['shared-db'].relation_joined,
                               self.on_shared_db_relation_joined)
        self.framework.observe(self.on['shared-db'].relation_changed,
                               self.on_shared_db_relation_changed)
        self.framework.observe(self.on['shared-db'].relation_departed,
                               self.on_shared_db_relation_departed)
        self.framework.observe(self.on['shared-db'].relation_broken,
                               self.on_shared_db_relation_departed)

        # NRPE relations


    def install_packages(self):        
        logger.info("DEBUG02: Installing packages")
        self.model.unit.status = MaintenanceStatus('Installing apt packages')
        add_source('ppa:ondrej/php')
        apt_update()
        # apt_install(["apache2", "php7.2", "php7.2-cli", "php7.2-mysql", "php7.2-xml",
        #             "php7.2-gd", "php7.2-json", "php7.2-curl", "php7.2-mbstring", 
        #             "composer", "mysql-client-5.7", "wget"])
        apt_install(["apache2", "php7.4", "php7.4-cli", "php7.4-mysql", "php7.4-xml",
                    "php7.4-gd", "php7.4-json", "php7.4-curl", "php7.4-mbstring", 
                    "composer", "mysql-client-5.7", "wget"])
        self._stored.installed = True
        self.model.unit.status = MaintenanceStatus('Waiting for configuration')


    def check_juju_config(self):
        # Verify required items
        errors = []
        for required in REQUIRED_JUJU_CONFIG:
            if not self.model.config[required]:
                logger.error("Required Juju config item(s) not set : %s", required)
                errors.append(required)
        if errors:
            raise DrupalCharmJujuConfigError(
                "Required Juju config item(s) not set : {}".format(", ".join(sorted(errors)))
            )


    def get_drupal_web_root(self):
        site_name = self.model.config["site-name"]
        settings_directory = self.model.config["settings-directory"]

        result = '/srv/{}'.format(site_name)
        path_prefix = settings_directory.replace('sites/default', '')
        if path_prefix:
            path_prefix = path_prefix.strip('/')
            result = '{}/{}'.format(result, path_prefix)

        return result


    def render_apache2_config(self):
        site_name = self.model.config["site-name"]
        vhost_file = "/etc/apache2/sites-enabled/99-{}.conf".format(site_name)
        vhost_template = 'vhost.conf.j2'
        document_root = self.get_drupal_web_root()
        context = {
            'site_name': site_name,
            'document_root': document_root
        }
        render(vhost_template, vhost_file, context, perms=0o755)


    def render_drupal_settings(self):
        site_name = self.model.config["site-name"]
        settings_directory = self.model.config["settings-directory"]

        # Write default settings file, and make it writeable for installation.
        drupal_settings_file = '/srv/{}/{}/settings.php'.format(site_name, settings_directory)
        if not Path(drupal_settings_file).is_file():
            drupal_settings_template = "settings.php.j2"
            context = {}
            render(drupal_settings_template, drupal_settings_file, context,
                   owner='root', group='www-data', perms=0o660)

        # Write local settings file
        drupal_settings_local_template = 'settings.local.php.j2'
        drupal_settings_local_file = '/srv/{}/{}/settings.local.php'.format(site_name, settings_directory)
        context = {
            'database': self._stored.db_data['database'],
            'db_host': self._stored.db_data['db_host'],
            'username': self._stored.db_data['username'],
            'password': self._stored.db_data['password']
        }
        render(drupal_settings_local_template, drupal_settings_local_file, context,
               owner='root', group='www-data', perms=0o640)

        # Create files directory if not present
        drupal_files_path = '/srv/{}/{}/files'.format(site_name, settings_directory)
        if not Path(drupal_files_path).is_dir():
            host.mkdir(drupal_files_path, owner='root', group="www-data", perms=0o775)


    def build_site_root(self):
        site_name = self.model.config["site-name"]
        site_root_directory = '/srv/{}'.format(site_name)
        host.mkdir(site_root_directory, owner='root', group="www-data", perms=0o755)

        drupal_url = self.model.config["drupal-url"]
        url_path = urlparse(drupal_url)
        filename = os.path.basename(url_path.path)
        tmp_path = "/tmp/{}".format(filename)

        # TODO: add exception handling here
        file_stream = requests.get(drupal_url, stream=True)
        with open(tmp_path, 'wb') as local_file:
            for data in file_stream:
                local_file.write(data)

        # Extract file
        cmd = ['tar', '-xzvf', tmp_path, '-C', site_root_directory, '--strip-components=1']
        subprocess.check_call(cmd)

        logger.info("Site root created.")
        self._stored.site_root_created=True


    def on_install(self, event):
        self.install_packages()


    def configure_charm(self, event):
        logger.info("DEBUG01: Congratulations, configure charm had been called")

        # validate configuration
        try:
            self.check_juju_config()
        except DrupalCharmJujuConfigError as e:
            self.unit.status = BlockedStatus(str(e))
            return

        if not self._stored.installed:
            self.install_packages()

        if not self._stored.site_root_created:
            self.model.unit.status = MaintenanceStatus('Build site root')
            self.build_site_root()

        self.model.unit.status = MaintenanceStatus('Configuring apache2')
        self.render_apache2_config()
        # subprocess.check_call(['a2ensite', 'openstack_https_frontend'])
        subprocess.check_call(['a2enmod', 'rewrite'])
        host.service_reload('apache2', restart_on_failure=True)
                
        logger.info("DEBUG03: Already installed doing post-config")
        if not self._stored.db_connected:
            self.model.unit.status = BlockedStatus('Waiting for database relation')
            return

        self.render_drupal_settings()   

        self.model.unit.status = ActiveStatus('Unit is ready')


    def on_shared_db_relation_joined(self, event):
        logger.info('shared-db relation joined')
        # import pdb; pdb. set_trace()
        # db name: self.app.name
        # db user: self.app.name ?
        # hostname: self.model.get_binding('shared-db')

        self._stored.db_data['database'] = self.name
        self._stored.db_data['username'] = self.name
        
        binding = self.model.get_binding('shared-db')
        bind_address = str(binding.network.bind_address)
        u = self.this_unit

        relations = self.model.relations['shared-db']
        for relation in relations:
            rid = "{}:{}".format(relation.name, relation.id)
            logging.debug('Processing rid %s', rid)
            relation.data[u]['database'] = self._stored.db_data['database']
            relation.data[u]['username'] = self._stored.db_data['username']
            relation.data[u]['hostname'] = bind_address


    def on_shared_db_relation_changed(self, event):
        logger.info('shared-db relation changed')
        self._stored.db_connected = True
        # import pdb; pdb. set_trace()
        relations = self.model.relations['shared-db']
        data = {}
        for relation in relations:
            rid = "{}:{}".format(relation.name, relation.id)
            logging.debug('Processing rid %s', rid)
            for unit in relation.units:
                _data = {
                    'db_host': relation.data[unit].get('db_host'),
                    'password': relation.data[unit].get('password')
                }
                logging.debug('Processing rid %s unit %s', rid, unit.name)
                if all(_data.values()):
                    data = _data
        if data:
            self._stored.db_data['db_host'] = data['db_host']
            self._stored.db_data['password'] = data['password']
            logging.debug('Data had been set')
        self.configure_charm(event)



    def on_shared_db_relation_departed(self, event):
        logger.info('shared-db relation departed')
        self._stored.db_connected = False
        self._stored.db_data['database'] = None
        self._stored.db_data['username'] = None
        self._stored.db_data['password'] = None
        self._stored.db_data['db_host'] = None
        self.configure_charm(event)
   
    


if __name__ == "__main__":
    main(DrupalCharm)
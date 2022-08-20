# Implements the requires side handling of 'mysql-shared' interface

import functools
import json
import logging

from ops.framework import (
    Object,
    EventBase,
    ObjectEvents,
    EventSource,
    StoredState
)
from ops.model import ModelError, BlockedStatus, WaitingStatus
logger = logging.getLogger(__name__)

# TODO: refactor from MySharedN to SharedDbN

class MySqlSharedConnected(EventBase):
    """Event emitted by MySqlShared.on.connected.

    This event will be emitted by MySqlShared when a...
    """


class MySqlSharedAvailable(EventBase):
    """Event emitted by MySqlShared.on.available.

    This event will be emitted by MySqlShared when a...
    """


class MySqlSharedDeparted(EventBase):
    """Event emitted by MySqlShared.on.available.

    This event will be emitted by MySqlShared when a
    db-relation-broken or db-relation-departed is fired
    """ 


class MySqlSharedEvents(ObjectEvents):
    """Events emitted by the MySqlShared class."""
    connected = EventSource(MySqlSharedConnected)
    available = EventSource(MySqlSharedAvailable)
    departed = EventSource(MySqlSharedDeparted)
    # TODO: implement available_access_network
    # TODO: implement available_ssl


class MySqlShared(Object):

    on = MySqlSharedEvents()
    _stored = StoredState()

    def __init__(self, charm, relation_name):
        super().__init__(charm, relation_name)
        self.name = relation_name
        self.this_unit = self.model.unit

        self._stored.set_default(database=None, username=None, hostname=None,
                                 password=None)

        self._relation_name = self.relation_name = relation_name
        self._munged_name = self.model.unit.name.replace("/", "_")
    
        self.framework.observe(charm.on[relation_name].relation_joined,
                               self._on_relation_joined)
        self.framework.observe(charm.on[relation_name].relation_changed,
                               self._on_relation_changed)
        self.framework.observe(charm.on[relation_name].relation_departed,
                               self._on_relation_departed)
        self.framework.observe(charm.on[relation_name].relation_broken,
                               self._on_relation_departed)

    def _on_relation_joined(self, event):
        logger.info("MYSQLSHARED01: _on_relation_joined")
        self.on.connected.emit()
        # relations = self.model.relations[self.name]
        # for relation in relations:
        #     rid = "{}:{}".format(relation.name, relation.id)
        #     logging.debug('Processing rid %s', rid)
        #     relation.data[self.this_unit]['database'] = 'testdb'
        #     relation.data[self.this_unit]['username'] = 'dbuser01'
        #     relation.data[self.this_unit]['hostname'] = '172.16.99.12'

        


    def _on_relation_changed(self, event):
        logger.info("emiting relation available")
        self.on.available.emit()


    def _on_relation_departed(self, event):
        logger.info("emiting relation departed")
        self.on.departed.emit()

    def configure(self, database, username, hostname=None, prefix=None):
        # TODO: implement prefix support
        logger.info("shared db configure")
        self._stored.database = database
        self._stored.username = username
        self._stored.hostname = hostname

    def database(self, prefix=None):
        return self._stored.database

    def username(self, prefix=None):
        return self._stored.username

    def hostname(self, prefix=None):
        return self._stored.hostname

    def password(self, prefix=None):
        return self._stored.password

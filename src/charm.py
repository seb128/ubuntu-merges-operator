#!/usr/bin/env python3
# Copyright 2025 Canonical
# See LICENSE file for licensing details.

"""Charmed Operator for Merges reports."""

import logging
import shutil
import socket
from subprocess import CalledProcessError

import ops
from charmlibs.apt import PackageError, PackageNotFoundError
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer as IngressRequirer

from merges import Merges

logger = logging.getLogger(__name__)

MERGES_PORT = 8080
PATCHES_PORT = 8081


class UbuntuMergesCharm(ops.CharmBase):
    """Charmed Operator for Ubuntu Merges."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)

        self.merges_ingress = IngressRequirer(
            self, port=MERGES_PORT, strip_prefix=True, relation_name="merges-ingress"
        )
        self.patches_ingress = IngressRequirer(
            self, port=PATCHES_PORT, strip_prefix=True, relation_name="patches-ingress"
        )

        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.update_status, self._on_update_status)
        self.framework.observe(self.on.upgrade_charm, self._on_install)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.refresh_action, self._on_refresh_report)

        # Ingress URL changes require updating the configuration and also regenerating sitemaps,
        # therefore we can bind events for this relation to the config_changed event.
        framework.observe(self.merges_ingress.on.ready, self._on_config_changed)
        framework.observe(self.merges_ingress.on.revoked, self._on_config_changed)
        framework.observe(self.patches_ingress.on.ready, self._on_config_changed)
        framework.observe(self.patches_ingress.on.revoked, self._on_config_changed)

        self._merges = Merges()

    def _on_install(self, event: ops.EventBase):
        """Handle install, upgrade, config-changed, or ingress events."""
        self.unit.status = ops.MaintenanceStatus("Setting up environment")
        try:
            self._merges.install()
        except (
            CalledProcessError,
            PackageError,
            PackageNotFoundError,
            IOError,
            OSError,
            shutil.Error,
        ):
            self.unit.status = ops.BlockedStatus(
                "Failed to set up the environment. Check `juju debug-log` for details."
            )
            return
        self.unit.status = ops.ActiveStatus()

    def _on_start(self, event: ops.StartEvent):
        """Start the merges service."""
        self.unit.status = ops.MaintenanceStatus("Starting merges service")
        try:
            self._merges.start()
            self.unit.status = ops.MaintenanceStatus("Generating merges report")
        except CalledProcessError:
            self.unit.status = ops.BlockedStatus(
                "Failed to start services. Check `juju debug-log` for details."
            )
            return
        self.unit.set_ports(MERGES_PORT, PATCHES_PORT)

    def _on_update_status(self, event: ops.UpdateStatusEvent):
        """Reflecting the status of the systemd service."""
        if self._merges.updating:
            self.unit.status = ops.MaintenanceStatus("Generating merges report")
        else:
            self.unit.status = ops.ActiveStatus()

    def _on_config_changed(self, event):
        """Update configuration."""
        self.unit.status = ops.MaintenanceStatus("Updating configuration")
        try:
            self._merges.configure(
                self._get_external_url(self.merges_ingress, MERGES_PORT),
                self._get_external_url(self.patches_ingress, PATCHES_PORT),
            )
            self._merges.restart_apache()
            self.unit.set_ports(MERGES_PORT, PATCHES_PORT)
        except ValueError:
            self.unit.status = ops.BlockedStatus(
                "Invalid configuration. Check `juju debug-log` for details."
            )
            return
        self.unit.status = ops.ActiveStatus()

    def _on_refresh_report(self, event: ops.ActionEvent):
        """Refresh the report."""
        self.unit.status = ops.MaintenanceStatus("Refreshing the report")

        try:
            event.log("Refreshing the report")
            self._merges.refresh_report()
        except (CalledProcessError, IOError):
            event.log("Report refresh failed")
            self.unit.status = ops.ActiveStatus(
                "Failed to refresh the report. Check `juju debug-log` for details."
            )
            return
        self.unit.status = ops.ActiveStatus()

    def _get_external_url(self, ingress, port) -> str:
        """Report URL to access Ubuntu Merges."""
        # Default: FQDN
        external_url = f"http://{socket.getfqdn()}:{port}"
        # If can connect to juju-info, get unit IP
        if binding := self.model.get_binding("juju-info"):
            unit_ip = str(binding.network.bind_address)
            external_url = f"http://{unit_ip}:{port}"
        # If ingress is set, get ingress url
        if ingress.url:
            external_url = ingress.url
        return external_url


if __name__ == "__main__":  # pragma: nocover
    ops.main(UbuntuMergesCharm)

# Copyright 2025 Canonical
# See LICENSE file for licensing details.

"""Unit tests for the charm.

These tests only cover those methods that do not require internet access,
and do not attempt to manipulate the underlying machine.
"""

from subprocess import CalledProcessError
from unittest.mock import PropertyMock, patch

import ops
import pytest
from charmlibs.apt import PackageError, PackageNotFoundError
from ops.testing import (
    ActiveStatus,
    Address,
    BindAddress,
    BlockedStatus,
    Context,
    Network,
    Relation,
    State,
    TCPPort,
)

from charm import UbuntuMergesCharm


@pytest.fixture
def ctx():
    return Context(UbuntuMergesCharm)


@pytest.fixture
def base_state(ctx):
    return State(leader=True)


@patch("charm.Merges.install")
def test_install_success(install_mock, ctx, base_state):
    install_mock.return_value = True
    out = ctx.run(ctx.on.install(), base_state)
    assert out.unit_status == ActiveStatus()
    assert install_mock.called


@patch("charm.Merges.install")
@pytest.mark.parametrize(
    "exception",
    [
        PackageError,
        PackageNotFoundError,
        CalledProcessError(1, "foo"),
    ],
)
def test_install_failure(install_mock, exception, ctx, base_state):
    install_mock.side_effect = exception
    out = ctx.run(ctx.on.install(), base_state)
    assert out.unit_status == BlockedStatus(
        "Failed to set up the environment. Check `juju debug-log` for details."
    )


@patch("charm.Merges.install")
def test_upgrade_success(install_mock, ctx, base_state):
    install_mock.return_value = True
    out = ctx.run(ctx.on.upgrade_charm(), base_state)
    assert out.unit_status == ActiveStatus()
    assert install_mock.called


@patch("charm.Merges.install")
@pytest.mark.parametrize(
    "exception",
    [
        PackageError,
        PackageNotFoundError,
        CalledProcessError(1, "foo"),
    ],
)
def test_upgrade_failure(install_mock, exception, ctx, base_state):
    install_mock.side_effect = exception
    out = ctx.run(ctx.on.upgrade_charm(), base_state)
    assert out.unit_status == BlockedStatus(
        "Failed to set up the environment. Check `juju debug-log` for details."
    )


@patch("charm.Merges.configure")
def test_config_changed(configure_mock, ctx, base_state):
    out = ctx.run(ctx.on.config_changed(), base_state)
    assert out.unit_status == ActiveStatus()
    assert configure_mock.called


@patch("charm.Merges.configure")
def test_config_changed_failed_bad_config(configure_mock, ctx, base_state):
    configure_mock.side_effect = ValueError
    out = ctx.run(ctx.on.config_changed(), base_state)
    assert out.unit_status == BlockedStatus(
        "Invalid configuration. Check `juju debug-log` for details."
    )


@patch("charm.Merges.start")
def test_start_success(start_mock, ctx, base_state):
    out = ctx.run(ctx.on.start(), base_state)
    assert out.unit_status == ops.MaintenanceStatus("Generating merges report")
    assert start_mock.called
    assert out.opened_ports == {
        TCPPort(port=8080, protocol="tcp"),
        TCPPort(port=8081, protocol="tcp"),
    }


@patch("charm.Merges.updating", new_callable=PropertyMock)
def test_update_status_updating(updating_mock, ctx, base_state):
    """Test update_status when service is updating."""
    updating_mock.return_value = True
    out = ctx.run(ctx.on.update_status(), base_state)
    assert out.unit_status == ops.MaintenanceStatus("Generating merges report")
    assert updating_mock.called


@patch("charm.Merges.updating", new_callable=PropertyMock)
def test_update_status_active(updating_mock, ctx, base_state):
    """Test update_status when service is active (not updating)."""
    updating_mock.return_value = False
    out = ctx.run(ctx.on.update_status(), base_state)
    assert out.unit_status == ActiveStatus()
    assert updating_mock.called


@patch("charm.Merges.start")
@pytest.mark.parametrize("exception", [CalledProcessError(1, "foo")])
def test_start_failure(start_mock, exception, ctx, base_state):
    start_mock.side_effect = exception
    out = ctx.run(ctx.on.start(), base_state)
    assert out.unit_status == BlockedStatus(
        "Failed to start services. Check `juju debug-log` for details."
    )
    assert out.opened_ports == frozenset()


@patch("charm.Merges.refresh_report")
def test_merges_refresh_success(refresh_report_mock, ctx, base_state):
    out = ctx.run(ctx.on.action("refresh"), base_state)
    assert ctx.action_logs == ["Refreshing the report"]
    assert out.unit_status == ActiveStatus()
    assert refresh_report_mock.called


@patch("charm.Merges.refresh_report")
def test_merges_refresh_failure(refresh_report_mock, ctx, base_state):
    refresh_report_mock.side_effect = CalledProcessError(1, "refresh")
    out = ctx.run(ctx.on.action("refresh"), base_state)
    assert out.unit_status == ActiveStatus(
        "Failed to refresh the report. Check `juju debug-log` for details."
    )


@patch("charm.Merges.configure")
@patch("charm.socket.getfqdn")
@patch("ops.model.Model.get_binding")
def test_get_external_url_fqdn_fallback(get_binding_mock, getfqdn_mock, configure_mock, ctx):
    """Test that FQDN is used when no juju-info binding and no ingress."""
    get_binding_mock.return_value = None
    getfqdn_mock.return_value = "test-host.example.com"
    state = State(leader=True)
    out = ctx.run(ctx.on.config_changed(), state)
    assert out.unit_status == ActiveStatus()
    configure_mock.assert_called_once_with(
        "http://test-host.example.com:8080", "http://test-host.example.com:8081"
    )


@patch("charm.Merges.configure")
def test_get_external_url_juju_info_binding(configure_mock, ctx):
    """Test that unit IP is used when juju-info binding exists."""
    state = State(
        leader=True,
        networks={
            Network(
                "juju-info",
                bind_addresses=[BindAddress(addresses=[Address("192.168.1.10")])],
            ),
        },
    )
    out = ctx.run(ctx.on.config_changed(), state)
    assert out.unit_status == ActiveStatus()
    configure_mock.assert_called_once_with("http://192.168.1.10:8080", "http://192.168.1.10:8081")


@patch("charm.Merges.configure")
def test_get_external_url_ingress_url(configure_mock, ctx):
    """Test that ingress URL takes priority when available."""
    merges_relation = Relation(
        endpoint="merges-ingress",
        interface="ingress",
        remote_app_name="traefik",
        remote_app_data={"ingress": '{"url": "https://merges.example.com/"}'},
    )
    patches_relation = Relation(
        endpoint="patches-ingress",
        interface="ingress",
        remote_app_name="traefik",
        remote_app_data={"ingress": '{"url": "https://patches.example.com/"}'},
    )
    state = State(
        leader=True,
        networks={
            Network(
                "juju-info",
                bind_addresses=[BindAddress(addresses=[Address("192.168.1.10")])],
            ),
        },
        relations={merges_relation, patches_relation},
    )
    out = ctx.run(ctx.on.config_changed(), state)
    assert out.unit_status == ActiveStatus()
    configure_mock.assert_called_once_with(
        "https://merges.example.com/", "https://patches.example.com/"
    )

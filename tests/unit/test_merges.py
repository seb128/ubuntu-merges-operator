# Copyright 2025 Canonical
# See LICENSE file for licensing details.

import logging
import os
import shutil
from subprocess import CalledProcessError
from unittest.mock import MagicMock, call, patch

import pytest
from charmlibs.apt import PackageError, PackageNotFoundError

import merges


@pytest.fixture
def merges_instance():
    return merges.Merges()


@patch("charms.operator_libs_linux.v1.systemd.service_running")
def test_updating_true(mock_service_running, merges_instance):
    mock_service_running.return_value = True
    assert merges_instance.updating
    mock_service_running.assert_called_once_with("ubuntu-merges.service")


@patch("charms.operator_libs_linux.v1.systemd.service_running")
def test_updating_false(mock_service_running, merges_instance):
    mock_service_running.return_value = False
    assert not merges_instance.updating
    mock_service_running.assert_called_once_with("ubuntu-merges.service")


@patch("merges.apt")
def test_install_packages_success(mock_apt, merges_instance):
    merges_instance._install_packages()
    mock_apt.update.assert_called_once()
    assert mock_apt.add_package.call_count == len(merges.PACKAGES)
    mock_apt.add_package.assert_has_calls([call(p) for p in merges.PACKAGES])


@patch("merges.apt")
def test_install_packages_update_failure(mock_apt, merges_instance):
    mock_apt.update.side_effect = CalledProcessError(1, "apt update")
    with pytest.raises(CalledProcessError):
        merges_instance._install_packages()


@patch("merges.apt")
def test_install_packages_install_failure_package_error(mock_apt, merges_instance):
    mock_apt.add_package.side_effect = PackageError("package failure")
    with pytest.raises(PackageError):
        merges_instance._install_packages()


@patch("merges.apt")
def test_install_packages_install_failure_not_found(mock_apt, merges_instance):
    mock_apt.add_package.side_effect = PackageNotFoundError("not found")
    with pytest.raises(PackageNotFoundError):
        merges_instance._install_packages()


@patch("merges.run")
@patch("merges.shutil")
@patch("merges.Path")
def test_configure_apache_success(mock_path, mock_shutil, mock_run, merges_instance):
    mock_path_obj = MagicMock()
    mock_path.return_value = mock_path_obj

    merges_instance._configure_apache()

    # Check module enabling
    assert mock_run.call_count == 2  # headers and python

    # Check default site removal
    mock_path.assert_any_call("/etc/apache2/sites-enabled/000-default.conf")
    mock_path_obj.unlink.assert_called_once_with(missing_ok=True)

    # Check config copying
    assert mock_shutil.copy.call_count == 2
    mock_shutil.copy.assert_any_call(
        "src/apache/merges.ubuntu.com.conf", merges.APACHE_MERGES_UBUNTU_CONFIG_PATH
    )
    mock_shutil.copy.assert_any_call(
        "src/apache/patches.ubuntu.com.conf", merges.APACHE_PATCHES_UBUNTU_CONFIG_PATH
    )

    # Check ports configuration
    mock_path.assert_any_call("/etc/apache2/conf-enabled/z-merges-ports.conf")
    mock_path_obj.write_text.assert_called_once_with("Listen 8080\nListen 8081\n")


@patch("merges.run")
def test_configure_apache_module_failure(mock_run, merges_instance):
    mock_run.side_effect = CalledProcessError(1, "a2enmod")
    with pytest.raises(CalledProcessError):
        merges_instance._configure_apache()


@patch("merges.run")
@patch("merges.shutil")
@patch("merges.Path")
def test_configure_apache_copy_failure(mock_path, mock_shutil, mock_run, merges_instance):
    # mock unlink to not fail
    mock_path.return_value.unlink.return_value = None

    # Configure the mock to have the real error class so except clause works
    mock_shutil.Error = shutil.Error

    mock_shutil.copy.side_effect = OSError("copy failed")
    with pytest.raises(OSError):
        merges_instance._configure_apache()


@patch("merges.Path")
@patch("charms.operator_libs_linux.v1.systemd.service_enable")
def test_setup_systemd_units_success(mock_service_enable, mock_path, merges_instance):
    mock_unit_loc = MagicMock()
    mock_service_file = MagicMock()
    mock_timer_file = MagicMock()

    # Configure Path behavior
    def path_side_effect(arg):
        if arg == "/etc/systemd/system":
            return mock_unit_loc
        if arg == "src/systemd/ubuntu-merges.service":
            return mock_service_file
        if arg == "src/systemd/ubuntu-merges.timer":
            return mock_timer_file
        return MagicMock()

    mock_path.side_effect = path_side_effect
    mock_service_file.read_text.return_value = "Service Content"
    mock_timer_file.read_text.return_value = "Timer Content"

    merges_instance._setup_systemd_units()

    mock_unit_loc.mkdir.assert_called_once_with(parents=True, exist_ok=True)
    mock_service_enable.assert_called_once_with("--now", "ubuntu-merges.timer")


@patch("charms.operator_libs_linux.v1.systemd.service_enable")
@patch("merges.Path")
def test_setup_systemd_units_with_proxies(mock_path, mock_service_enable, merges_instance):
    # Test proxy URLs
    http_proxy_url = "http://proxy.example.com:8080"
    https_proxy_url = "https://proxy.example.com:8443"

    mock_service_file = MagicMock()
    mock_service_file.read_text.return_value = "[Service]\n"
    mock_timer_file = MagicMock()
    mock_timer_file.read_text.return_value = "Timer Content"

    # Mock destination files for write_text
    mock_dest_service = MagicMock()
    mock_dest_timer = MagicMock()

    # We need to setup proxies before calling this method
    merges_instance.proxies = {"http": http_proxy_url, "https": https_proxy_url}

    # We need to intercept the specific path calls
    def path_side_effect(arg):
        if arg == "/etc/systemd/system":
            mock_unit_loc = MagicMock()

            def truediv_side_effect(name):
                if name == "ubuntu-merges.service":
                    return mock_dest_service
                if name == "ubuntu-merges.timer":
                    return mock_dest_timer
                return MagicMock()

            mock_unit_loc.__truediv__.side_effect = truediv_side_effect
            return mock_unit_loc
        if arg == "src/systemd/ubuntu-merges.service":
            return mock_service_file
        if arg == "src/systemd/ubuntu-merges.timer":
            return mock_timer_file
        return MagicMock()

    mock_path.side_effect = path_side_effect

    merges_instance._setup_systemd_units()

    # Verify that write_text is called with content containing proxy environment variables
    mock_dest_service.write_text.assert_called_once()
    written_service_content = mock_dest_service.write_text.call_args.args[0]

    # Verify proxy environment variables are in the written content
    assert f"Environment=http_proxy={http_proxy_url}" in written_service_content
    assert f"Environment=HTTP_PROXY={http_proxy_url}" in written_service_content
    assert f"Environment=https_proxy={https_proxy_url}" in written_service_content
    assert f"Environment=HTTPS_PROXY={https_proxy_url}" in written_service_content

    # Verify the original service content is also present
    assert "[Service]" in written_service_content

    # Verify timer content is written unchanged
    mock_dest_timer.write_text.assert_called_once_with("Timer Content")


@patch("merges.Path")
def test_setup_systemd_units_enable_failure(mock_path, merges_instance):
    """Test failure when enabling the systemd timer."""
    mock_unit_loc = MagicMock()
    mock_service_file = MagicMock()
    mock_timer_file = MagicMock()

    # Configure Path behavior
    def path_side_effect(arg):
        if arg == "/etc/systemd/system":
            return mock_unit_loc
        if arg == "src/systemd/ubuntu-merges.service":
            return mock_service_file
        if arg == "src/systemd/ubuntu-merges.timer":
            return mock_timer_file
        return MagicMock()

    mock_path.side_effect = path_side_effect
    mock_service_file.read_text.return_value = "Service Content"
    mock_timer_file.read_text.return_value = "Timer Content"

    with patch("charms.operator_libs_linux.v1.systemd.service_enable") as mock_enable:
        mock_enable.side_effect = CalledProcessError(1, "systemctl enable")
        with pytest.raises(CalledProcessError):
            merges_instance._setup_systemd_units()

    mock_unit_loc.mkdir.assert_called_once_with(parents=True, exist_ok=True)
    mock_service_file.read_text.assert_called_once()
    mock_timer_file.read_text.assert_called_once()


@patch("merges.shutil")
@patch("merges.Path")
def test_setup_directories_success(mock_path, mock_shutil, merges_instance):
    mock_srv_dir = MagicMock()

    # Setup Path mocks to behave somewhat realistically
    mock_path.return_value = mock_srv_dir  # for SRVDIR usually, but we patch Path class

    # Let's mock the module level SRVDIR to simplify
    with patch("merges.SRVDIR") as mock_srv:
        mock_data = MagicMock()
        mock_comments_file = MagicMock()

        def div_side_effect(x):
            if x == "data":
                return mock_data
            if x == "comments.txt":
                return mock_comments_file
            return MagicMock()

        mock_srv.__truediv__.side_effect = div_side_effect

        merges_instance._setup_directories()

        mock_data.mkdir.assert_called_once_with(parents=True, exist_ok=True)
        mock_shutil.chown.assert_any_call(mock_srv, "ubuntu", "ubuntu")
        mock_shutil.chown.assert_any_call(mock_data, "ubuntu", "ubuntu")

        mock_comments_file.write_text.assert_called_once_with("")
        mock_comments_file.chmod.assert_called_once_with(0o664)
        mock_shutil.chown.assert_any_call(mock_comments_file, "www-data", "ubuntu")


@patch("merges.shutil")
@patch("merges.Path")
def test_setup_directories_main_failure(mock_path, mock_shutil, merges_instance):
    # Mock SRVDIR / "data" to raise OSError on mkdir
    with patch("merges.SRVDIR") as mock_srv:
        mock_data = MagicMock()
        mock_srv.__truediv__.return_value = mock_data
        mock_data.mkdir.side_effect = OSError("mkdir failed")

        with pytest.raises(OSError):
            merges_instance._setup_directories()


@patch("merges.shutil")
@patch("merges.Path")
def test_setup_directories_comments_file_error_handled(
    mock_path, mock_shutil, merges_instance, caplog
):
    """Test that failure to setup comments.txt is handled gracefully."""
    # We want the first block (mkdir) to succeed, but the second block (comments.txt) to fail
    with patch("merges.SRVDIR") as mock_srv:
        mock_data = MagicMock()
        mock_comments = MagicMock()

        def div_side_effect(arg):
            if arg == "data":
                return mock_data
            if arg == "comments.txt":
                return mock_comments
            return MagicMock()

        mock_srv.__truediv__.side_effect = div_side_effect

        # Fail on write_text of comments
        mock_comments.write_text.side_effect = OSError("write failed")

        with caplog.at_level(logging.WARNING):
            merges_instance._setup_directories()

        # Verify first block succeeded
        mock_data.mkdir.assert_called_once_with(parents=True, exist_ok=True)
        mock_shutil.chown.assert_any_call(mock_srv, "ubuntu", "ubuntu")

        # Verify second block was attempted
        mock_comments.write_text.assert_called_once_with("")

        # Verify error was handled and logged
        assert "Failed to change the comments.txt owner: write failed" in caplog.text


def test_install(merges_instance):
    # Test the orchestrator method
    merges_instance._install_packages = MagicMock()
    merges_instance._configure_apache = MagicMock()
    merges_instance._setup_systemd_units = MagicMock()
    merges_instance._setup_directories = MagicMock()
    merges_instance._install_application = MagicMock()

    merges_instance.install()

    merges_instance._install_packages.assert_called_once()
    merges_instance._configure_apache.assert_called_once()
    merges_instance._setup_systemd_units.assert_called_once()
    merges_instance._setup_directories.assert_called_once()
    merges_instance._install_application.assert_called_once()


def test_configure(merges_instance, caplog):
    merges_url = "http://merges.example.com"
    patches_url = "http://patches.example.com"
    with caplog.at_level(logging.DEBUG):
        merges_instance.configure(merges_url, patches_url)
    assert any(merges_url in rec.message for rec in caplog.records)
    assert any(patches_url in rec.message for rec in caplog.records)


@patch("merges.shutil.copytree")
def test_install_application_success(mock_copytree, merges_instance):
    with patch("merges.SRVDIR"):
        merges_instance._install_application()
        mock_copytree.assert_called_once()


@patch("merges.shutil.copytree")
def test_install_application_failure(mock_copytree, merges_instance):
    mock_copytree.side_effect = OSError("copy failed")
    with pytest.raises(OSError):
        merges_instance._install_application()


@patch("charms.operator_libs_linux.v1.systemd.service_restart")
def test_restart_apache_success(mock_restart, merges_instance):
    """Test successful Apache restart."""
    merges_instance.restart_apache()
    mock_restart.assert_called_once_with("apache2")


@patch("charms.operator_libs_linux.v1.systemd.service_restart")
def test_restart_apache_failure(mock_restart, merges_instance):
    """Test failed Apache restart."""
    mock_restart.side_effect = CalledProcessError(1, "apache2")
    with pytest.raises(CalledProcessError):
        merges_instance.restart_apache()


@patch("merges.Merges.restart_apache")
@patch("charms.operator_libs_linux.v1.systemd.service_start")
def test_start_success(mock_start, mock_restart_apache, merges_instance):
    """Test successful start."""
    merges_instance.start()
    mock_restart_apache.assert_called_once()
    mock_start.assert_called_once_with("--no-block", "ubuntu-merges")


@patch("merges.Merges.restart_apache")
def test_start_apache_failure(mock_restart_apache, merges_instance):
    """Test start failure when Apache restart fails."""
    mock_restart_apache.side_effect = CalledProcessError(1, "restart failed")
    with pytest.raises(CalledProcessError):
        merges_instance.start()


@patch("merges.Merges.restart_apache")
@patch("charms.operator_libs_linux.v1.systemd.service_start")
def test_start_systemd_failure(mock_start, mock_restart_apache, merges_instance):
    """Test start failure when systemd service start fails."""
    mock_restart_apache.return_value = None
    mock_start.side_effect = CalledProcessError(1, "start failed")
    with pytest.raises(CalledProcessError):
        merges_instance.start()
    mock_restart_apache.assert_called_once()
    mock_start.assert_called_once_with("--no-block", "ubuntu-merges")


@patch("charms.operator_libs_linux.v1.systemd.service_start")
def test_refresh_report_success(mock_start, merges_instance):
    merges_instance.refresh_report()
    mock_start.assert_called_once_with("ubuntu-merges.service")


@patch("charms.operator_libs_linux.v1.systemd.service_start")
def test_refresh_report_failure(mock_start, merges_instance):
    mock_start.side_effect = CalledProcessError(1, "start failed")
    with pytest.raises(CalledProcessError):
        merges_instance.refresh_report()


def test_proxies_init():
    with patch.dict(
        os.environ,
        {
            "JUJU_CHARM_HTTP_PROXY": "http://proxy.example.com",
            "JUJU_CHARM_HTTPS_PROXY": "https://proxy.example.com",
        },
    ):
        m = merges.Merges()
        assert m.env["HTTP_PROXY"] == "http://proxy.example.com"
        assert m.env["HTTPS_PROXY"] == "https://proxy.example.com"
        assert m.proxies["http"] == "http://proxy.example.com"
        assert m.proxies["https"] == "https://proxy.example.com"

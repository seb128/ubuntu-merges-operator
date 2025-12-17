# Copyright 2025 Canonical
# See LICENSE file for licensing details.

"""Representation of the merges service."""

import logging
import os
import shutil
from pathlib import Path
from subprocess import PIPE, STDOUT, CalledProcessError, run

import charms.operator_libs_linux.v1.systemd as systemd
from charmlibs import apt
from charmlibs.apt import PackageError, PackageNotFoundError

logger = logging.getLogger(__name__)

# Packages installed as part of the update process.
PACKAGES = [
    "apache2",
    "apt-utils",
    "dpkg-dev",
    "gettext",
    "ghostscript",
    "git",
    "libapache2-mod-python",
    "python3-debian",
    # TOFIX: to remove once the python2 instance is deprecated
    "python-is-python3",
    "python3-matplotlib",
    "xz-utils",
]

SRVDIR = Path("/srv/merges")

APACHE_MERGES_UBUNTU_CONFIG_PATH = Path("/etc/apache2/sites-enabled/merges.ubuntu.com.conf")
APACHE_PATCHES_UBUNTU_CONFIG_PATH = Path("/etc/apache2/sites-enabled/patches.ubuntu.com.conf")


class Merges:
    """Represent a merges instance in the workload."""

    def __init__(self):
        logger.debug("Merges class init")
        self.env = os.environ.copy()
        self.proxies = {}
        juju_http_proxy = self.env.get("JUJU_CHARM_HTTP_PROXY")
        juju_https_proxy = self.env.get("JUJU_CHARM_HTTPS_PROXY")
        if juju_http_proxy:
            logger.debug("Setting HTTP_PROXY env to %s", juju_http_proxy)
            self.env["HTTP_PROXY"] = juju_http_proxy
            self.proxies["http"] = juju_http_proxy
        if juju_https_proxy:
            logger.debug("Setting HTTPS_PROXY env to %s", juju_https_proxy)
            self.env["HTTPS_PROXY"] = juju_https_proxy
            self.proxies["https"] = juju_https_proxy

    def _install_packages(self):
        """Install the Debian packages needed."""
        try:
            apt.update()
            logger.debug("Apt index refreshed.")
        except CalledProcessError as e:
            logger.error("Failed to update package cache: %s", e)
            raise

        for p in PACKAGES:
            try:
                apt.add_package(p)
                logger.debug("Package %s installed", p)
            except PackageNotFoundError:
                logger.error("Failed to find package %s in package cache", p)
                raise
            except PackageError as e:
                logger.error("Failed to install %s: %s", p, e)
                raise

    def _configure_apache(self):
        # Enable required Apache modules
        modules = ["headers", "python"]
        for module in modules:
            try:
                run(
                    ["a2enmod", module],
                    check=True,
                    stdout=PIPE,
                    stderr=STDOUT,
                    text=True,
                    timeout=60,
                )
                logger.debug("Apache module %s enabled", module)
            except CalledProcessError as e:
                logger.warning("Failed to enable Apache module %s: %s", module, e.stdout)
                raise

        # Disable default site by removing symlink
        Path("/etc/apache2/sites-enabled/000-default.conf").unlink(missing_ok=True)
        logger.debug("Default Apache site disabled")

        try:
            shutil.copy("src/apache/merges.ubuntu.com.conf", APACHE_MERGES_UBUNTU_CONFIG_PATH)
            shutil.copy("src/apache/patches.ubuntu.com.conf", APACHE_PATCHES_UBUNTU_CONFIG_PATH)
            logger.debug("Apache configs copied")
        except (OSError, shutil.Error) as e:
            logger.warning("Error copying config: %s", str(e))
            raise

    def _setup_systemd_units(self):
        """Set up the systemd service and timer."""
        systemd_unit_location = Path("/etc/systemd/system")
        systemd_unit_location.mkdir(parents=True, exist_ok=True)

        systemd_service = Path("src/systemd/ubuntu-merges.service")
        service_txt = systemd_service.read_text()

        systemd_timer = Path("src/systemd/ubuntu-merges.timer")
        timer_txt = systemd_timer.read_text()

        systemd_proxy = ""
        if "http" in self.proxies:
            systemd_proxy += "\nEnvironment=http_proxy=" + self.proxies["http"]
            systemd_proxy += "\nEnvironment=HTTP_PROXY=" + self.proxies["http"]
        if "https" in self.proxies:
            systemd_proxy += "\nEnvironment=https_proxy=" + self.proxies["https"]
            systemd_proxy += "\nEnvironment=HTTPS_PROXY=" + self.proxies["https"]

        service_txt += systemd_proxy
        (systemd_unit_location / "ubuntu-merges.service").write_text(service_txt)
        (systemd_unit_location / "ubuntu-merges.timer").write_text(timer_txt)
        logger.debug("Systemd units created")

        try:
            systemd.service_enable("--now", "ubuntu-merges.timer")
        except CalledProcessError as e:
            logger.error("Failed to enable the ubuntu-merges timer: %s", e)
            raise

    def _setup_directories(self):
        """Create needed directories and files and set owner."""
        datadir = SRVDIR / "data"

        try:
            os.makedirs(datadir, exist_ok=True)
            shutil.chown(SRVDIR, "ubuntu", "ubuntu")
            shutil.chown(datadir, "ubuntu", "ubuntu")
            logger.debug("Directory %s created", datadir)
        except OSError as e:
            logger.warning("Setting up directories and files failed: %s", e)
            raise

        try:
            comments = SRVDIR / "comments.txt"
            comments.write_text("")
            comments.chmod(0o664)
            shutil.chown(comments, "www-data", "ubuntu")
        except OSError as e:
            logger.warning("Failed to change the comments.txt owner: %s", e)

    def _install_application(self):
        """Install the merge-o-matic application."""
        try:
            shutil.copytree("app/", SRVDIR / "code", dirs_exist_ok=True)
        except OSError as e:
            logger.warning("Installing merge-o-matic: %s", e)
            raise

    def install(self):
        """Install the merges environment."""
        # Install the deb packages needed for the service
        self._install_packages()
        self._configure_apache()
        self._setup_systemd_units()
        self._setup_directories()
        self._install_application()

    def start(self):
        """Restart the transition services."""
        try:
            systemd.service_restart("apache2")
            systemd.service_start("ubuntu-merges")
            logger.debug("Apache2 service restarted")
        except CalledProcessError as e:
            logger.error("Failed to start systemd service: %s", e)
            raise

    def configure(self, url: str):
        """Configure the charm."""
        logger.debug("The url in use is %s", url)

    def refresh_report(self):
        """Refresh the merges report."""
        try:
            systemd.service_start("ubuntu-merges.service")
        except CalledProcessError as e:
            logger.debug("Refreshing of the merges report failed: %s", e.stdout)
            raise

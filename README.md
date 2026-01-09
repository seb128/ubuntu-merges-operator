# Ubuntu Merges Operator


**Ubuntu Merges Operator** is a [charm](https://juju.is/charms-architecture) for building merges reports for Ubuntu.

This repository contains the code for the charm, the application logic is located in the `app/` directory.

## Basic usage

Assuming you have access to a bootstrapped [Juju](https://juju.is) controller, you can deploy the charm with:

```bash
❯ juju deploy ubuntu-merges
```

Once the charm is deployed, you can check the status with Juju status:

```bash
❯ juju status
Model        Controller  Cloud/Region         Version  SLA          Timestamp
merges       lxd         localhost/localhost  3.6.7    unsupported  13:29:50+02:00

App            Version  Status  Scale  Charm          Channel  Rev  Exposed  Message
ubuntu-merges           active      1  ubuntu-merges             0  no

Unit              Workload  Agent  Machine  Public address  Ports      Message
ubuntu-merges/0*  active    idle    1       10.142.46.109   8080/tcp, 8081/tcp
```

On first start up, the charm will install the application and install a systemd timer unit to trigger merges updates on a regular basis.

To refresh the report, you can use the provided Juju [Action](https://documentation.ubuntu.com/juju/3.6/howto/manage-actions/):

```bash
❯ juju run ubuntu-merges/unit/0 refresh
```

## Integrating with an ingress / proxy

The charm supports integrations with ingress/proxy services (like Traefik) using two separate relations:
- `ingress-merges`: For the merges report (service on port 8080).
- `ingress-patches`: For the patches report (service on port 8081).

To test these integrations (e.g., using `haproxy` as an ingress provider):

```bash
# Deploy the charms
❯ juju deploy ubuntu-merges
❯ juju deploy haproxy --channel 2.8/edge --config external-hostname=merges.internal
❯ juju deploy self-signed-certificates --channel 1/edge

# Create integrations
❯ juju integrate ubuntu-merges:ingress-merges haproxy
❯ juju integrate ubuntu-merges:ingress-patches haproxy
❯ juju integrate haproxy:certificates self-signed-certificates:certificates

# Test the proxy integration
❯ curl -k -H "Host: merges.internal" https://<haproxy-ip>/<model-name>-ubuntu-merges-merges
❯ curl -k -H "Host: patches.internal" https://<haproxy-ip>/<model-name>-ubuntu-merges-patches
```

## Testing

There are unit tests which can be run directly without influence to
the system and dependencies handled by uv.

```bash
❯ make unit
```

## Contribute to Ubuntu Merges Operator

Ubuntu Merges Operator is open source and part of the Canonical family. We would love your help.

If you're interested, start with the [contribution guide](CONTRIBUTING.md).

## License and copyright

Ubuntu Merges Operator is released under the [GPL-3.0 license](LICENSE).

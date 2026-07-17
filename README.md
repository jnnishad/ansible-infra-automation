# ansible-infra-automation

Ansible roles, playbooks, and a custom Python module for baseline server
hardening, Docker installation, monitoring-agent rollout, patch
management, and cloud VM provisioning — the configuration-management
half of the stack that Terraform/Pulumi provisions.

## Why

Infrastructure-as-code covers *creating* servers; this repo covers what
happens to them after: hardening, patching, getting them reporting into
the same Mimir/Loki stack as everything else, and cleaning up the AWS
resources they leave behind. Extracted from hardening/patch-management
work at Dolat Capital Market and cloud automation at Atom Technologies.

## Structure

```
roles/
  linux-hardening/     SSH lockdown, fail2ban, unattended upgrades, sysctl hardening, NTP
  docker-install/       Docker CE + sane daemon.json (log rotation, overlay2)
  monitoring-agent/     Installs Grafana Alloy as a systemd service, ships to central Mimir/Loki
playbooks/
  site.yml               Applies the full baseline to every host in inventory
  patch-management.yml   Rolling, serial OS patch + reboot with post-patch health checks
  provision-cloud-vm.yml Launches EC2 instances then immediately configures them
library/
  cloud_resource_cleanup.py   Custom Ansible module: finds/removes orphaned EBS volumes & EIPs
inventory/
  hosts.example.ini       Copy to hosts.ini and fill in real addresses
```

## Usage

```bash
cp inventory/hosts.example.ini inventory/hosts.ini   # edit with real hosts
ansible-playbook playbooks/site.yml --check           # dry run first
ansible-playbook playbooks/site.yml
```

Rolling patch run (one host at a time, aborts on any failure):

```bash
ansible-playbook playbooks/patch-management.yml
```

## The custom module

`library/cloud_resource_cleanup.py` is a real Ansible module (not just a
shell wrapper) — it uses `AnsibleModule`, supports `--check` mode, and
only deletes resources when both check mode is off *and* `confirm: true`
is explicitly set:

```yaml
- name: Report orphaned EBS volumes and EIPs (safe — no deletion)
  cloud_resource_cleanup:
    region: eu-central-1

- name: Actually delete volumes orphaned for 3+ days
  cloud_resource_cleanup:
    region: eu-central-1
    resource_types: [ebs_volumes]
    min_age_hours: 72
    confirm: true
```

## Related repos

- [`terraform-multicloud-infra`](https://github.com/jnnishad/terraform-multicloud-infra) — provisions the servers this repo configures
- [`python-devops-toolkit`](https://github.com/jnnishad/python-devops-toolkit) — standalone CLI versions of similar cleanup/health-check logic

## License

MIT — see [LICENSE](LICENSE).

<!-- JN -->

<!-- JN -->

<!-- JN -->

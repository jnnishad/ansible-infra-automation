"""Unit tests for the pure-logic parts of cloud_resource_cleanup.py.

find_orphaned_ebs_volumes and find_orphaned_elastic_ips never touch
Ansible directly, but importing the module does trigger `from
ansible.module_utils.basic import AnsibleModule` at load time -- so
this suite needs ansible installed, the same requirement CI's
ansible-lint job already has. Run via:

    pip install ansible-core boto3 pytest
    pytest tests/
"""
import datetime
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "library"))

from cloud_resource_cleanup import (  # noqa: E402
    find_orphaned_ebs_volumes,
    find_orphaned_elastic_ips,
)


def _volume(volume_id, size_gb, hours_old, az="eu-central-1a"):
    created = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours_old)
    return {
        "VolumeId": volume_id,
        "Size": size_gb,
        "CreateTime": created,
        "AvailabilityZone": az,
    }


def _fake_ec2_client(pages):
    """A minimal stand-in for boto3's EC2 client covering just the two
    calls find_orphaned_ebs_volumes makes: get_paginator("describe_volumes")
    and paginator.paginate(...). No real boto3/AWS credentials needed.
    """
    client = MagicMock()
    paginator = MagicMock()
    paginator.paginate.return_value = pages
    client.get_paginator.return_value = paginator
    return client


def test_find_orphaned_ebs_volumes_filters_by_age():
    old_volume = _volume("vol-old", size_gb=100, hours_old=48)
    recent_volume = _volume("vol-recent", size_gb=50, hours_old=1)
    client = _fake_ec2_client([{"Volumes": [old_volume, recent_volume]}])

    result = find_orphaned_ebs_volumes(client, min_age_hours=24)

    assert len(result) == 1
    assert result[0]["id"] == "vol-old"
    assert result[0]["size_gb"] == 100


def test_find_orphaned_ebs_volumes_empty_when_all_too_recent():
    recent_volume = _volume("vol-recent", size_gb=50, hours_old=1)
    client = _fake_ec2_client([{"Volumes": [recent_volume]}])

    assert find_orphaned_ebs_volumes(client, min_age_hours=24) == []


def test_find_orphaned_ebs_volumes_across_multiple_pages():
    # describe_volumes is paginated in the real API -- confirm the
    # function actually walks every page instead of just the first.
    page1 = {"Volumes": [_volume("vol-a", size_gb=10, hours_old=100)]}
    page2 = {"Volumes": [_volume("vol-b", size_gb=20, hours_old=100)]}
    client = _fake_ec2_client([page1, page2])

    result = find_orphaned_ebs_volumes(client, min_age_hours=24)

    assert {v["id"] for v in result} == {"vol-a", "vol-b"}


def test_find_orphaned_ebs_volumes_boundary_at_exact_cutoff():
    # CreateTime exactly at the cutoff should count as orphaned (<=),
    # matching the module's own comparison.
    exactly_at_cutoff = _volume("vol-boundary", size_gb=30, hours_old=24)
    client = _fake_ec2_client([{"Volumes": [exactly_at_cutoff]}])

    result = find_orphaned_ebs_volumes(client, min_age_hours=24)

    assert len(result) == 1
    assert result[0]["id"] == "vol-boundary"


def test_find_orphaned_elastic_ips_finds_unassociated():
    client = MagicMock()
    client.describe_addresses.return_value = {
        "Addresses": [
            {"PublicIp": "1.2.3.4", "AllocationId": "eipalloc-1"},
            {
                "PublicIp": "5.6.7.8",
                "AllocationId": "eipalloc-2",
                "AssociationId": "eipassoc-1",
                "InstanceId": "i-0123456789",
            },
        ]
    }

    result = find_orphaned_elastic_ips(client)

    assert len(result) == 1
    assert result[0]["public_ip"] == "1.2.3.4"
    assert result[0]["allocation_id"] == "eipalloc-1"


def test_find_orphaned_elastic_ips_empty_when_all_associated():
    client = MagicMock()
    client.describe_addresses.return_value = {
        "Addresses": [
            {
                "PublicIp": "5.6.7.8",
                "AllocationId": "eipalloc-2",
                "AssociationId": "eipassoc-1",
                "InstanceId": "i-0123456789",
            },
        ]
    }

    assert find_orphaned_elastic_ips(client) == []


def test_find_orphaned_elastic_ips_no_addresses():
    client = MagicMock()
    client.describe_addresses.return_value = {"Addresses": []}

    assert find_orphaned_elastic_ips(client) == []

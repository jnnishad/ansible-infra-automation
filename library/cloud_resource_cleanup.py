#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Custom Ansible module for cleaning up orphaned AWS resources.

Built out of the "Automated operational workflows using Python scripting
for cloud resource cleanup" work at Adform, and the earlier "Python Code
using Ansible Python API" custom modules at Atom Technologies. Finds
unattached EBS volumes and unassociated Elastic IPs, reports them, and
deletes them only when check_mode is off and confirm=true — cleanup
tooling that defaults to safe/dry-run is the whole point.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: cloud_resource_cleanup
short_description: Find and optionally remove orphaned AWS resources
description:
  - Scans a region for unattached EBS volumes and unassociated Elastic IPs.
  - In check mode (or with confirm=false), only reports what it found.
  - With confirm=true and check mode off, deletes the orphaned resources.
options:
  region:
    description: AWS region to scan.
    type: str
    required: true
  resource_types:
    description: Which resource types to scan for.
    type: list
    elements: str
    default: [ebs_volumes, elastic_ips]
    choices: [ebs_volumes, elastic_ips]
  min_age_hours:
    description: Only consider resources orphaned for at least this many hours.
    type: int
    default: 24
  confirm:
    description: Actually delete matched resources instead of just reporting them.
    type: bool
    default: false
author:
  - Jaihind Nishad (@jnnishad)
"""

EXAMPLES = r"""
- name: Report orphaned resources (safe, no deletion)
  cloud_resource_cleanup:
    region: eu-central-1

- name: Delete EBS volumes orphaned for more than 3 days
  cloud_resource_cleanup:
    region: eu-central-1
    resource_types: [ebs_volumes]
    min_age_hours: 72
    confirm: true
"""

RETURN = r"""
orphaned_ebs_volumes:
  description: Unattached EBS volumes found (or deleted).
  type: list
  returned: always
orphaned_elastic_ips:
  description: Unassociated Elastic IPs found (or released).
  type: list
  returned: always
deleted:
  description: Whether resources were actually deleted this run.
  type: bool
  returned: always
"""

import datetime

from ansible.module_utils.basic import AnsibleModule

try:
    import boto3
    from botocore.exceptions import ClientError

    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False


def find_orphaned_ebs_volumes(ec2_client, min_age_hours):
    orphaned = []
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=min_age_hours)
    paginator = ec2_client.get_paginator("describe_volumes")
    for page in paginator.paginate(Filters=[{"Name": "status", "Values": ["available"]}]):
        for volume in page["Volumes"]:
            if volume["CreateTime"] <= cutoff:
                orphaned.append(
                    {
                        "id": volume["VolumeId"],
                        "size_gb": volume["Size"],
                        "created": volume["CreateTime"].isoformat(),
                        "availability_zone": volume["AvailabilityZone"],
                    }
                )
    return orphaned


def find_orphaned_elastic_ips(ec2_client):
    orphaned = []
    response = ec2_client.describe_addresses()
    for address in response["Addresses"]:
        if "AssociationId" not in address and "InstanceId" not in address:
            orphaned.append(
                {
                    "public_ip": address.get("PublicIp"),
                    "allocation_id": address.get("AllocationId"),
                }
            )
    return orphaned


def delete_ebs_volumes(ec2_client, volumes):
    deleted = []
    for volume in volumes:
        ec2_client.delete_volume(VolumeId=volume["id"])
        deleted.append(volume["id"])
    return deleted


def release_elastic_ips(ec2_client, addresses):
    released = []
    for address in addresses:
        ec2_client.release_address(AllocationId=address["allocation_id"])
        released.append(address["public_ip"])
    return released


def main():
    module = AnsibleModule(
        argument_spec=dict(
            region=dict(type="str", required=True),
            resource_types=dict(
                type="list",
                elements="str",
                default=["ebs_volumes", "elastic_ips"],
                choices=["ebs_volumes", "elastic_ips"],
            ),
            min_age_hours=dict(type="int", default=24),
            confirm=dict(type="bool", default=False),
        ),
        supports_check_mode=True,
    )

    if not HAS_BOTO3:
        module.fail_json(msg="boto3 and botocore are required for this module")

    region = module.params["region"]
    resource_types = module.params["resource_types"]
    min_age_hours = module.params["min_age_hours"]
    confirm = module.params["confirm"]

    ec2_client = boto3.client("ec2", region_name=region)

    result = {
        "changed": False,
        "orphaned_ebs_volumes": [],
        "orphaned_elastic_ips": [],
        "deleted": False,
    }

    try:
        if "ebs_volumes" in resource_types:
            result["orphaned_ebs_volumes"] = find_orphaned_ebs_volumes(ec2_client, min_age_hours)

        if "elastic_ips" in resource_types:
            result["orphaned_elastic_ips"] = find_orphaned_elastic_ips(ec2_client)

        should_delete = confirm and not module.check_mode
        found_anything = bool(result["orphaned_ebs_volumes"] or result["orphaned_elastic_ips"])

        if should_delete and found_anything:
            if result["orphaned_ebs_volumes"]:
                delete_ebs_volumes(ec2_client, result["orphaned_ebs_volumes"])
            if result["orphaned_elastic_ips"]:
                release_elastic_ips(ec2_client, result["orphaned_elastic_ips"])
            result["deleted"] = True
            result["changed"] = True
        elif found_anything:
            # Found things but didn't delete (dry run / check mode / confirm=false)
            result["changed"] = False

    except ClientError as err:
        module.fail_json(msg="AWS API error: {0}".format(err), **result)

    module.exit_json(**result)


if __name__ == "__main__":
    main()

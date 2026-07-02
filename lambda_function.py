"""
Finds EBS snapshots that aren't being used anymore and deletes them.

A snapshot gets deleted if it's older than MIN_AGE_DAYS, isn't backing
an AMI, and its volume is either gone or not attached to anything.

"""

import os
import boto3
from datetime import datetime, timezone

ec2 = boto3.client("ec2")


def get_all_snapshots():
    """Return every EBS snapshot we own."""
    response = ec2.describe_snapshots(OwnerIds=["self"])
    return response["Snapshots"]


def get_volume_info():
    """
    Return two sets built from a single describe_volumes() call:
      - every volume ID that currently exists
      - every volume ID that's currently attached to something
    """
    response = ec2.describe_volumes()
    existing_ids = set()
    attached_ids = set()

    for volume in response["Volumes"]:
        existing_ids.add(volume["VolumeId"])
        if volume["Attachments"]:
            attached_ids.add(volume["VolumeId"])

    return existing_ids, attached_ids


def get_ami_backed_snapshot_ids():
    """
    Return a set of snapshot IDs used by one of our AMIs.
    Never delete these, it would break the AMI.
    """
    response = ec2.describe_images(Owners=["self"])
    backed_snapshot_ids = set()

    for image in response["Images"]:
        for mapping in image.get("BlockDeviceMappings", []):
            ebs_info = mapping.get("Ebs")
            if ebs_info and "SnapshotId" in ebs_info:
                backed_snapshot_ids.add(ebs_info["SnapshotId"])

    return backed_snapshot_ids


def snapshot_is_old_enough(snapshot, min_age_days):
    age = datetime.now(timezone.utc) - snapshot["StartTime"]
    return age.days >= min_age_days


def lambda_handler(event, context):
    dry_run = os.environ.get("DRY_RUN", "true").lower() == "true"
    min_age_days = int(os.environ.get("MIN_AGE_DAYS", "30"))

    try:
        all_snapshots = get_all_snapshots()
        existing_volume_ids, attached_volume_ids = get_volume_info()
        ami_backed_snapshot_ids = get_ami_backed_snapshot_ids()
    except ec2.exceptions.ClientError as err:
        print(f"Failed to fetch data from EC2: {err}")
        raise

    deleted = []
    skipped = []
    failed = []

    for snapshot in all_snapshots:
        snapshot_id = snapshot["SnapshotId"]
        volume_id = snapshot.get("VolumeId")

        if snapshot_id in ami_backed_snapshot_ids:
            skipped.append(snapshot_id)
            continue

        if not snapshot_is_old_enough(snapshot, min_age_days):
            skipped.append(snapshot_id)
            continue

        volume_is_gone = (not volume_id) or (volume_id not in existing_volume_ids)
        volume_is_unattached = (
            volume_id in existing_volume_ids and volume_id not in attached_volume_ids
        )

        if not (volume_is_gone or volume_is_unattached):
            skipped.append(snapshot_id)
            continue

        if dry_run:
            print(f"[DRY RUN] Would delete snapshot {snapshot_id}")
            deleted.append(snapshot_id)
            continue

        try:
            ec2.delete_snapshot(SnapshotId=snapshot_id)
            print(f"Deleted snapshot {snapshot_id}")
            deleted.append(snapshot_id)
        except ec2.exceptions.ClientError as err:
            print(f"Failed to delete snapshot {snapshot_id}: {err}")
            failed.append(snapshot_id)

    print(f"Done. dry_run={dry_run}, deleted={len(deleted)}, skipped={len(skipped)}, failed={len(failed)}")
    return {"dry_run": dry_run, "deleted": deleted, "skipped_count": len(skipped), "failed": failed}

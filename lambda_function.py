"""
EBS Snapshot Cleanup - Lambda function

What this does, in plain English:
1. Get a list of all EBS snapshots we own.
2. Get a list of all EBS volumes we own, and note which ones are
   actually attached to something.
3. Get a list of snapshots that are being used as the backing image
   for an AMI (so we know not to touch those).
4. For each snapshot: if it's old enough, AND it's not protecting an
   AMI, AND its volume is either gone or not attached to anything --
   it's "stale," so we delete it (or just log it, if DRY_RUN is on).

Environment variables (set these in the Lambda console or in your
deployment config):
  DRY_RUN       "true" or "false". If "true" (default), nothing gets
                deleted -- we only print what we WOULD delete. Always
                start with this on.
  MIN_AGE_DAYS  How many days old a snapshot must be before we're
                willing to delete it. Default is 30. This protects
                against deleting something that was just created a
                few minutes ago (e.g. mid-migration).
"""

import os
import boto3
from datetime import datetime, timezone

# The main AWS client we use to talk to EC2/EBS.
ec2 = boto3.client("ec2")


def get_all_snapshots():
    """Return every EBS snapshot we own."""
    response = ec2.describe_snapshots(OwnerIds=["self"])
    return response["Snapshots"]


def get_attached_volume_ids():
    """
    Return a set of volume IDs that are currently attached to
    something (an EC2 instance). If a volume isn't in this set,
    it's just sitting there unattached.
    """
    response = ec2.describe_volumes()
    attached_ids = set()

    for volume in response["Volumes"]:
        if volume["Attachments"]:  # non-empty list means it's attached
            attached_ids.add(volume["VolumeId"])

    return attached_ids


def get_existing_volume_ids():
    """Return a set of every volume ID that currently exists at all."""
    response = ec2.describe_volumes()
    return {volume["VolumeId"] for volume in response["Volumes"]}


def get_ami_backed_snapshot_ids():
    """
    Return a set of snapshot IDs that are used by one of our AMIs.
    We should never delete these, even if they'd otherwise look
    "stale," because doing so would break the AMI.
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
    """Check if a snapshot's age (in days) meets our minimum."""
    age = datetime.now(timezone.utc) - snapshot["StartTime"]
    return age.days >= min_age_days


def lambda_handler(event, context):
    # Read our settings from environment variables.
    dry_run = os.environ.get("DRY_RUN", "true").lower() == "true"
    min_age_days = int(os.environ.get("MIN_AGE_DAYS", "30"))

    # Gather everything we need up front, once, instead of making
    # repeated API calls inside a loop.
    all_snapshots = get_all_snapshots()
    existing_volume_ids = get_existing_volume_ids()
    attached_volume_ids = get_attached_volume_ids()
    ami_backed_snapshot_ids = get_ami_backed_snapshot_ids()

    deleted = []
    skipped = []

    for snapshot in all_snapshots:
        snapshot_id = snapshot["SnapshotId"]
        volume_id = snapshot.get("VolumeId")

        # Rule 1: never touch a snapshot that backs an AMI.
        if snapshot_id in ami_backed_snapshot_ids:
            skipped.append(snapshot_id)
            continue

        # Rule 2: never touch a snapshot that's too new.
        if not snapshot_is_old_enough(snapshot, min_age_days):
            skipped.append(snapshot_id)
            continue

        # Rule 3: decide if the snapshot's volume makes it "stale."
        volume_is_gone = (not volume_id) or (volume_id not in existing_volume_ids)
        volume_is_unattached = (
            volume_id in existing_volume_ids and volume_id not in attached_volume_ids
        )

        if volume_is_gone or volume_is_unattached:
            if dry_run:
                print(f"[DRY RUN] Would delete snapshot {snapshot_id}")
            else:
                ec2.delete_snapshot(SnapshotId=snapshot_id)
                print(f"Deleted snapshot {snapshot_id}")
            deleted.append(snapshot_id)
        else:
            skipped.append(snapshot_id)

    print(f"Done. dry_run={dry_run}, deleted={len(deleted)}, skipped={len(skipped)}")
    return {"dry_run": dry_run, "deleted": deleted, "skipped_count": len(skipped)}

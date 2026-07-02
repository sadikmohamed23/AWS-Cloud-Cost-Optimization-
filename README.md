# Stale EBS Snapshot Cleanup

This is a Lambda function that cleans up old, unused EBS snapshots in an AWS account.

AWS lets you take snapshots (backups) of storage volumes, but it doesn't delete them on its own once they're no longer needed. Over time, an account ends up with snapshots left behind by deleted volumes, terminated instances, or one-off backups nobody cleaned up, and each one quietly adds to the storage bill.

The goal of this project is to find those unused snapshots and remove them automatically, while making sure nothing still in use gets touched. A snapshot is only treated as stale if it's older than 30 days, isn't backing an AMI, and its source volume is either gone or no longer attached to anything. It also runs in a dry-run mode by default, so it can be reviewed before it's allowed to actually delete anything.

## Files

- `lambda_function.py` - the function itself.
- `iam-policy.json` - the permissions the function's role needs.

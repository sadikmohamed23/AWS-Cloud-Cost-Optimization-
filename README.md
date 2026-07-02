# EBS Snapshot Cleanup

A Lambda function that finds EBS snapshots that aren't being used
anymore and deletes them, to save on storage cost.

## The problem this solves

EBS snapshots are cheap one at a time, but they pile up over time --
leftover from instances that got terminated, volumes that got deleted,
manual backups nobody cleaned up. This script finds the ones that are
safe to delete and removes them.

## How it decides what's "safe to delete"

A snapshot is deleted only if **all** of these are true:

1. It's older than `MIN_AGE_DAYS` (default: 30 days). This avoids
   deleting something that was created moments ago.
2. It is **not** currently backing an AMI (checked via
   `describe_images`). Deleting a snapshot an AMI depends on would
   break that AMI, so these are always skipped.
3. Its source volume either no longer exists, or exists but isn't
   attached to anything.

If `DRY_RUN` is set to `"true"` (the default), the function only
prints what it *would* delete -- nothing is actually removed. You
switch it to `"false"` once you've checked the output and are
confident it's correct.

## Files

- `lambda_function.py` -- the whole function. One file, no
  dependencies beyond `boto3`, which is already available in the AWS
  Lambda Python runtime.
- `iam-policy.json` -- the permissions the function's execution role
  needs.

## How to deploy it (AWS Console, no extra tools required)

1. **Create the IAM role**
   - Go to IAM -> Roles -> Create role.
   - Choose "Lambda" as the trusted entity.
   - Attach a policy: create a new one and paste in the contents of
     `iam-policy.json`.
   - Name the role something like `ebs-snapshot-cleanup-role`.

2. **Create the Lambda function**
   - Go to Lambda -> Create function.
   - Choose "Author from scratch."
   - Runtime: Python 3.12.
   - Execution role: use the role you just created.
   - Once created, paste the contents of `lambda_function.py` into the
     inline code editor (replacing the default code), and click
     "Deploy."

3. **Set the environment variables**
   - In the function's Configuration tab -> Environment variables, add:
     - `DRY_RUN` = `true`
     - `MIN_AGE_DAYS` = `30`

4. **Test it**
   - Click "Test," create a new test event (the input doesn't matter,
     the function ignores it), and run it.
   - Check the execution results and the CloudWatch Logs to see what
     it found and what it would have deleted.

5. **(Optional) Schedule it to run automatically**
   - Go to Amazon EventBridge -> Rules -> Create rule.
   - Choose "Schedule," e.g. `rate(7 days)`.
   - Set the target to your Lambda function.

6. **Go live**
   - Once the dry-run output looks correct, change `DRY_RUN` to
     `false` in the function's environment variables.

## Limitations (things I'm aware of, on purpose)

- This calls `describe_snapshots()` and `describe_volumes()` without
  pagination, so on an account with more than ~1000 snapshots or
  volumes, it would only see the first page of results. Fixing that
  means using a boto3 paginator instead of calling the method once --
  I kept it simple here since most personal/small-team accounts won't
  hit that limit.
- It only checks snapshots and AMIs owned by the account running it
  (`OwnerIds=['self']`), not snapshots shared from other accounts.
- It doesn't send a notification (like email or Slack) when it runs --
  you have to check CloudWatch Logs or the Lambda console manually.

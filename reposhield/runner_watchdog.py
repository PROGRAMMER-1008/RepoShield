"""Independent expiry cleanup; never retries an action or assigns an outcome."""
import argparse
import json
import re
import time

from .restricted_runner import RestrictedRunner


def reap_expired(runner):
    ids = runner.command(["ps", "-aq", "--filter", "label=reposhield.restricted=true"]).decode().split()
    removed = []
    for container_id in ids:
        if not re.fullmatch(r"[0-9a-f]{12,64}", container_id):
            continue
        records = json.loads(runner.command(["inspect", container_id]))
        item = records[0]
        labels = item.get("Config", {}).get("Labels", {}) or {}
        if not re.fullmatch(r"/reposhield-job-[0-9a-f]{32}", item.get("Name", "")):
            continue
        deadline = labels.get("reposhield.deadline", "")
        if labels.get("reposhield.restricted") != "true" or not deadline.isdecimal():
            continue
        if int(deadline) <= time.time():
            runner.command(["rm", "-f", container_id])
            removed.append(container_id)
    return removed


def main(argv=None):
    parser = argparse.ArgumentParser(description="Independent RepoShield expired-container cleanup")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    runner = RestrictedRunner()
    while True:
        try:
            removed = reap_expired(runner)
            if removed: print(json.dumps({"removed": removed}), flush=True)
        except Exception as error:
            print(json.dumps({"error": type(error).__name__}), flush=True)
            if args.once: raise
        if args.once: return
        time.sleep(1)


if __name__ == "__main__":
    main()

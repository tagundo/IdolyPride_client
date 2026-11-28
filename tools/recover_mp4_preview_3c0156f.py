#!/usr/bin/env python3
"""One-time draft-only delivery of the unchanged, successful 3c0156f APK/IPA.

The application source and delivery source have separate clean checkouts and
separate receipts. This does not rebuild, relabel, publish or replace packages.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys

DELIVERY_ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    sys.path.insert(0, str(DELIVERY_ROOT))
from tools import stage_mp4_preview as delivery

WORKFLOW = ".github/workflows/recover-mp4-preview-3c0156f.yml"
APP_SOURCE = "3c0156f3cbc21b74890c2685e06bc96d587ba8e4"
PRODUCER_RUN = 44788068029
PRODUCER_ATTEMPT = 1
CODEC_RUN = 44788068056
ARTIFACTS = (
    ("android", 14655217638, "d4b5e11de888f7d58c5588326e87b37b981c0c041b82ecf21f2e98077ac46a39"),
    ("ios", 14657335556, "1621c3bb515009928a05a2c959e5935e7d82192e91c8bf3de8fd24ffe59a2fe7"),
)


def context():
    source = delivery.source_sha(os.environ.get("GITHUB_SHA"))
    delivery.need(os.environ.get("GITHUB_ACTIONS") == "true"
        and os.environ.get("GITHUB_REPOSITORY") == delivery.REPO
        and os.environ.get("GITHUB_REF") == delivery.BRANCH
        and os.environ.get("GITHUB_WORKFLOW_REF") == delivery.REPO + "/" + WORKFLOW + "@" + delivery.BRANCH
        and os.environ.get("GITHUB_EVENT_NAME") in ("push", "workflow_dispatch"), "exact_recovery_actions_context_required")
    for name in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"):
        delivery.need(re.fullmatch(r"[1-9][0-9]*", os.environ.get(name, "")), "recovery_run_identifier_required")
    return source, int(os.environ["GITHUB_RUN_ID"]), int(os.environ["GITHUB_RUN_ATTEMPT"])


def checkout_gate(path, source):
    delivery.need(path.is_absolute() and path.is_dir() and not path.is_symlink(), "real_absolute_checkout_required")
    def git(*args):
        value = subprocess.run(["git", "-C", str(path), *args], check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30).stdout
        delivery.need(len(value) <= 1024 * 1024, "checkout_metadata_bound")
        return value.decode().strip()
    delivery.need(Path(git("rev-parse", "--show-toplevel")).resolve() == path.resolve()
        and git("rev-parse", "HEAD") == source and git("status", "--porcelain", "--untracked-files=all") == "",
        "clean_exact_checkout_required")
    return path.resolve()


def recovery_gate(delivery_source, run_id, attempt):
    """Require this recovery workflow plus the exact original successful jobs."""
    current = delivery.api("actions/runs/" + str(run_id))
    delivery.need(current.get("id") == run_id and current.get("run_attempt") == attempt
        and current.get("head_sha") == delivery_source and current.get("path") == WORKFLOW
        and current.get("head_branch") == delivery.BRANCH.removeprefix("refs/heads/")
        and current.get("head_repository", {}).get("full_name") == delivery.REPO
        and current.get("event") in ("push", "workflow_dispatch"), "recovery_run_identity_differs")
    producer = delivery.api("actions/runs/" + str(PRODUCER_RUN))
    delivery.need(producer.get("status") == "completed" and producer.get("run_attempt") == PRODUCER_ATTEMPT,
        "pinned_producer_not_completed")
    # The original run failed only in delivery; both producer jobs must still
    # be successful. Never convert its overall failed conclusion into success.
    jobs = delivery.api("actions/runs/" + str(PRODUCER_RUN) + "/jobs?per_page=100").get("jobs", [])
    delivery.need(type(jobs) is list and len(jobs) <= 100, "producer_job_catalog_bound")
    for kind, identifier, digest in ARTIFACTS:
        delivery.producer_gate(producer, jobs, delivery.api("actions/artifacts/" + str(identifier)),
            kind=kind, source=APP_SOURCE, run_id=PRODUCER_RUN, attempt=PRODUCER_ATTEMPT,
            artifact_id=identifier, digest=digest)
    codec = delivery.api("actions/runs/" + str(CODEC_RUN))
    delivery.need(codec.get("run_attempt") == 1, "pinned_codec_attempt_differs")
    delivery.pinned_codec_proof(APP_SOURCE, CODEC_RUN)
    return delivery.ProducerContext(PRODUCER_RUN, PRODUCER_ATTEMPT, ARTIFACTS,
        codec_run_id=CODEC_RUN, delivery_source_commit=delivery_source,
        delivery_run_id=run_id, delivery_workflow=WORKFLOW)


def recover(app_checkout, work):
    delivery_source, run_id, attempt = context()
    delivery_checkout = checkout_gate(DELIVERY_ROOT, delivery_source)
    app_checkout = checkout_gate(app_checkout, APP_SOURCE)
    delivery.need(not app_checkout.is_relative_to(delivery_checkout)
        and not delivery_checkout.is_relative_to(app_checkout), "separate_source_checkouts_required")
    delivery.need(Path(delivery.__file__).resolve() == delivery_checkout / "tools/stage_mp4_preview.py",
        "delivery_helper_checkout_differs")
    producer = recovery_gate(delivery_source, run_id, attempt)
    # Every existing source closure is compared against the original app
    # checkout. The patched transport remains in the delivery checkout.
    delivery.ROOT = app_checkout
    result = delivery.stage_from_producer(APP_SOURCE, work, producer=producer)
    checkout_gate(delivery_checkout, delivery_source)
    checkout_gate(app_checkout, APP_SOURCE)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-checkout", required=True, type=Path)
    parser.add_argument("--work", required=True, type=Path)
    args = parser.parse_args()
    recover(args.app_checkout, args.work)


if __name__ == "__main__":
    main()

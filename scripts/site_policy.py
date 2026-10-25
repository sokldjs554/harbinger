#!/usr/bin/env python3
"""Offline, administrator-only validation selection and CAS activation/rollback."""

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from harbinger.models.registry import load_bundle
from harbinger.models.site_policy import activate, bundle_hash, rollback, select_policy, sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("select", "activate", "rollback"):
        command = commands.add_parser(name)
        command.add_argument("--model-dir", type=Path, required=True)
        if name == "select":
            command.add_argument("--data-dir", type=Path, required=True)
            command.add_argument("--validation-start", required=True)
            command.add_argument("--validation-end", required=True)
            command.add_argument("--test-start", required=True)
            command.add_argument("--outcomes-complete", action="store_true")
            command.add_argument("--min-rows", type=int, default=50)
            command.add_argument("--min-class", type=int, default=3)
            command.add_argument("--min-improvement", type=float, default=0.001)
            command.add_argument("--output", type=Path, required=True)
        else:
            command.add_argument(
                "--expected-revision", required=True, help="literal none for first activation"
            )
            command.add_argument("--proposal" if name == "activate" else "--to-revision", required=True)
    args = parser.parse_args()
    # Inspect bounded manifest paths before the trusted, local registry deserializes weights.
    version = json.loads((args.model_dir / "manifest.json").read_text())["latest"]
    digest = bundle_hash(args.model_dir, {"version": version})
    bundle = load_bundle(args.model_dir)
    bundle["_policy_bundle_hash"] = digest
    if args.command == "select":
        metadata = json.loads((args.data_dir / "features_meta.json").read_text())
        provenance = metadata.get("provenance", {})
        if provenance.get("boundary_version") != 2 or not provenance.get("observation_end"):
            raise ValueError("missing observation metadata")
        sources = provenance.get("source_sha256", {})
        if not {"assets.parquet", "inspections.parquet", "workorders.parquet"} <= sources.keys():
            raise ValueError("missing source hash metadata")
        for name, expected in sources.items():
            if Path(name).name != name or not name.endswith(".parquet"):
                raise ValueError("unsafe source path")
            if sha256(args.data_dir / name) != expected:
                raise ValueError("stale source metadata")
        sources = {
            **sources,
            "features.parquet": sha256(args.data_dir / "features.parquet"),
            "features_meta.json": sha256(args.data_dir / "features_meta.json"),
        }
        data_hash = hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest()
        frame = pd.read_parquet(args.data_dir / "features.parquet")
        proposal = select_policy(
            args.model_dir,
            bundle,
            frame,
            validation_start=args.validation_start,
            validation_end=args.validation_end,
            test_start=args.test_start,
            observation_end=provenance["observation_end"],
            outcomes_complete=args.outcomes_complete,
            data_hash=data_hash,
            min_rows=args.min_rows,
            min_class=args.min_class,
            min_improvement=args.min_improvement,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(proposal, indent=2) + "\n")
        result = {
            "proposal": str(args.output),
            "sites": proposal["sites"],
            "effective_from": proposal["effective_from"],
            "data_sources": sources,
        }
    else:
        expected = None if args.expected_revision == "none" else args.expected_revision
        if args.command == "activate":
            proposal = json.loads(Path(args.proposal).read_text())
            revision = activate(args.model_dir, bundle, proposal, expected_revision=expected)
        else:
            revision = rollback(
                args.model_dir,
                bundle,
                None if args.to_revision == "none" else args.to_revision,
                expected_revision=expected,
            )
        result = {"revision": revision, "operation": args.command}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

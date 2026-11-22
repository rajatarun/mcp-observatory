#!/usr/bin/env python3
"""Resolve every live coordinate the platform E2E suite needs, from stack outputs.

One place, for all seven stacks. Nothing here is hardcoded except the stack
*names* (overridable by environment variable), because a stack name is the one
thing you must know before you can ask CloudFormation anything.

This is the payoff of the outputs work: each service publishes its API base
URL, its tables and its index names, so a harness can find them without a
console, a wiki page, or a copied ARN. Where a service does not publish
something, that is a gap in the service, not something to paper over here --
`missing()` reports it rather than guessing a name.

Usage
-----
    python e2e/platform_env.py              # JSON of everything resolvable
    python e2e/platform_env.py --check      # what is reachable, what is not
    eval "$(python e2e/platform_env.py --format sh)"

Credentials are never resolved. Secret ARNs are reported; their contents are
not read, so no password reaches a shell environment, a process list or a log.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from dataclasses import dataclass, field

# Stack name -> env var that overrides it. Defaults are the names the deploy
# workflows use, read out of them rather than invented.
STACKS = {
    "shared":       os.environ.get("WEAVE_STACK_SHARED", "tarun-teamweave-shared"),
    "contextweave": os.environ.get("WEAVE_STACK_CONTEXTWEAVE", "contextweave-rag-prod"),
    "teamweave":    os.environ.get("WEAVE_STACK_TEAMWEAVE", "tarun-content-team"),
    "aco":          os.environ.get("WEAVE_STACK_ACO", "tarun-admin-content"),
    "deviceweave":  os.environ.get("WEAVE_STACK_DEVICEWEAVE", "deviceweave-prod"),
    "toolweave":    os.environ.get("WEAVE_STACK_TOOLWEAVE", "toolweave"),
    "screenweave":  os.environ.get("WEAVE_STACK_SCREENWEAVE", "screenweave"),
}

# service -> {friendly key: stack Output key}. Only outputs that actually exist;
# see docs/stack-outputs-audit.md for what each was added for.
WANTED = {
    "contextweave": {
        "api_base": "APIEndpoint",
        "pg_host": "PostgresEndpoint",
        "pg_port": "PostgresPort",
        "pg_database": "PostgresDbName",
        "pg_secret_arn": "PostgresSecretArn",
        "pg_instance_id": "PostgresInstanceIdentifier",
        "artifacts_bucket": "ArtifactsBucketName",
    },
    "teamweave": {
        "api_base": "HttpApiUrl",
        "runs_table": "DdbTable",
        "observatory_table": "ObservatoryMetricsTable",
        "span_timeline_index": "ObservatoryMetricsSpanTimelineIndex",
        "agent_index": "ObservatoryMetricsAgentIdTimestampIndex",
        "config_bucket": "ConfigBucket",
        "artifact_bucket": "ArtifactBucket",
        "state_machine_arn": "StateMachineArn",
        "contextweave_url": "ContextWeaveUrl",
    },
    "aco": {
        "api_base": "ApiBaseUrl",
        "content_table": "ContentTableName",
        "status_updated_index": "ContentTableStatusUpdatedIndex",
        "status_published_index": "ContentTableStatusPublishedIndex",
        "articles_bucket": "ArticlesBucketName",
        "articles_prefix": "ArticlesPrefix",
        "gemini_model": "GeminiModelId",
    },
    "deviceweave": {
        "api_base": "ApiBaseUrl",
        "registry_table": "DeviceRegistryTableName",
        "registry_provider_status_index": "DeviceRegistryProviderStatusIndex",
        "policy_table": "PolicyTableName",
        "policy_device_type_index": "PolicyTableDeviceTypeCreatedIndex",
        "presence_table": "PresenceTableName",
    },
    "toolweave": {
        "api_base": "ToolWeaveApiEndpoint",
        "catalog_table": "ApiCatalogTableName",
        "meta_table": "ApiMetaTableName",
        "proposals_table": "ProposalsTableName",
    },
    "screenweave": {
        "mcp_endpoint": "McpEndpoint",
        "visual_qa_endpoint": "VisualQAEndpoint",
        "sessions_table": "SessionsTableName",
        "cache_table": "ScreenweaveCacheTableName",
    },
    "shared": {
        "observatory_table": "ObservatoryMetricsTableName",
    },
}


@dataclass
class PlatformEnv:
    """What the live platform exposes, as CloudFormation reports it."""
    services: dict = field(default_factory=dict)   # service -> {key: value}
    errors: dict = field(default_factory=dict)     # service -> why it is absent

    def get(self, service: str, key: str, default=None):
        return self.services.get(service, {}).get(key, default)

    def has(self, service: str, *keys: str) -> bool:
        """True only when the service resolved AND every key named is present."""
        svc = self.services.get(service)
        return bool(svc) and all(svc.get(k) for k in keys)

    def why_missing(self, service: str, *keys: str) -> str:
        if service in self.errors:
            return f"{service} stack ({STACKS[service]}) not readable: {self.errors[service]}"
        svc = self.services.get(service) or {}
        absent = [k for k in keys if not svc.get(k)]
        return (f"{service} stack publishes no value for {absent} "
                f"(wanted outputs {[WANTED[service][k] for k in absent]})")

    def as_env(self) -> dict:
        out = {}
        for service, values in sorted(self.services.items()):
            for key, value in sorted(values.items()):
                out[f"WEAVE_{service.upper()}_{key.upper()}"] = value
        return out


def _fetch(stack: str, region: str | None) -> dict:
    """{OutputKey: OutputValue} for one stack. Raises on any failure."""
    import boto3  # noqa: PLC0415 -- only needed when actually talking to AWS
    cfn = boto3.client("cloudformation", region_name=region) if region else boto3.client("cloudformation")
    stacks = cfn.describe_stacks(StackName=stack)["Stacks"]
    return {o["OutputKey"]: o.get("OutputValue", "") for o in stacks[0].get("Outputs", [])}


def _from_file(path: str) -> PlatformEnv:
    """Load coordinates from JSON instead of CloudFormation.

    For a deployment CloudFormation cannot describe -- a local stand-in, a
    staging environment behind different credentials, or the suite's own
    selftest. The file is {"services": {service: {key: value}}}; keys are the
    friendly names in WANTED, not Output names, because at this point the
    outputs have already been mapped.
    """
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    services = raw.get("services", raw)
    unknown = sorted(set(services) - set(WANTED))
    if unknown:
        raise ValueError(f"{path} names services that do not exist: {unknown}; "
                         f"known: {sorted(WANTED)}")
    return PlatformEnv(services={s: dict(v) for s, v in services.items()},
                       errors=dict(raw.get("errors", {})))


def resolve(region: str | None = None, only: list[str] | None = None) -> PlatformEnv:
    """Read every stack. A stack that is absent is recorded, not raised.

    A partially-deployed platform is the normal case -- the suite skips the
    tests it cannot run and says why, rather than failing them, because a
    skipped integration test and a broken integration are different facts.

    WEAVE_E2E_ENV_FILE short-circuits AWS entirely and reads the coordinates
    from JSON; see _from_file.
    """
    env_file = os.environ.get("WEAVE_E2E_ENV_FILE")
    if env_file:
        return _from_file(env_file)

    env = PlatformEnv()
    for service, stack in STACKS.items():
        if only and service not in only:
            continue
        try:
            outputs = _fetch(stack, region)
        except Exception as exc:  # noqa: BLE001 -- any failure means "cannot use this service"
            env.errors[service] = f"{type(exc).__name__}: {exc}"
            continue
        wanted = WANTED.get(service, {})
        env.services[service] = {k: outputs[o] for k, o in wanted.items()
                                 if o in outputs and outputs[o] != ""}
        absent = [o for o in wanted.values() if not outputs.get(o)]
        if absent:
            env.errors.setdefault(service + ":outputs", f"missing outputs: {sorted(absent)}")
    return env


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    ap.add_argument("--format", choices=("json", "sh"), default="json")
    ap.add_argument("--check", action="store_true",
                    help="Report what resolved and what did not, and exit 1 if nothing did")
    args = ap.parse_args(argv)

    env = resolve(args.region)

    if args.check:
        print(f"region: {args.region}\n")
        for service, stack in STACKS.items():
            values = env.services.get(service) or {}
            if values:
                print(f"  OK       {service:14s} {stack:28s} {len(values)} coordinates")
            else:
                print(f"  MISSING  {service:14s} {stack:28s} {env.errors.get(service, 'no outputs')}")
        gaps = {k: v for k, v in env.errors.items() if k.endswith(":outputs")}
        if gaps:
            print("\n  partial (stack exists, some outputs absent):")
            for k, v in sorted(gaps.items()):
                print(f"    {k[:-8]:14s} {v}")
        return 0 if env.services else 1

    if args.format == "json":
        print(json.dumps({"services": env.services, "errors": env.errors}, indent=2, sort_keys=True))
    else:
        for var, value in sorted(env.as_env().items()):
            print(f"export {var}={shlex.quote(value)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

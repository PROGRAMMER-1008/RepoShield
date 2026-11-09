"""Local trusted administration; never exposed as an agent API."""
import argparse
import os
from pathlib import Path

from alembic import command
from alembic.config import Config

from ..gitutil import resolve
from .durable import DurableStore


def migration_config(url):
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    cfg.attributes["database_url"] = url
    return cfg


def main(argv=None):
    parser = argparse.ArgumentParser(description="Trusted local RepoShield database administration")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate")
    register = sub.add_parser("register")
    for name in ("id", "tenant", "name", "path"):
        register.add_argument("--" + name, required=True)
    register.add_argument("--base", default="main", help="trusted base ref, resolved and pinned at registration")
    activate = sub.add_parser("activate-base", help="trusted administrator explicitly approves a new policy base")
    activate.add_argument("--id", required=True)
    activate.add_argument("--base", required=True)
    args = parser.parse_args(argv)
    url = os.environ.get("REPOSHIELD_DATABASE_URL", "")
    store = DurableStore(url)
    try:
        if args.command == "migrate":
            command.upgrade(migration_config(url), "head")
            print("Database schema upgraded to 0005")
        elif args.command == "activate-base":
            import sqlalchemy as sa
            from .schema_v1 import repositories
            store.check_schema()
            repo = store.repository(args.id)
            if repo is None: raise ValueError("repository not registered")
            sha = resolve(repo["path"], args.base)
            with store.engine.begin() as c:
                c.execute(repositories.update().where(repositories.c.id == args.id).values(
                    base_sha=sha, policy_epoch=repositories.c.policy_epoch + 1))
                store._event(c, "TRUSTED_BASE_ACTIVATED", "administrator-cli", {"repository_id": args.id, "base_sha": sha})
            print(f"Activated trusted base {sha} and advanced policy epoch for {args.id}")
        else:
            store.check_schema()
            path = os.path.realpath(args.path)
            sha = resolve(path, args.base)
            store.register_repository(repository_id=args.id, tenant_id=args.tenant,
                                      name=args.name, path=path, base_sha=sha)
            print(f"Registered {args.id} with trusted base {sha}")
    finally:
        store.engine.dispose()


if __name__ == "__main__":
    main()

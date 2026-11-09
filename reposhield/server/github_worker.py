"""Separate trusted network worker; never runs repository code."""
import argparse
import time
from .config import ServerConfig
from .durable import DurableStore
from .github_service import GitHubService


def main(argv=None):
    parser = argparse.ArgumentParser(description="RepoShield GitHub App worker")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--onboard", action="store_true", help="explicit trusted installation/repository activation")
    parser.add_argument("--retry-failed", action="store_true", help="explicitly reset failed intake/publication after fixing the cause")
    args = parser.parse_args(argv)
    cfg = ServerConfig()
    store = DurableStore(cfg.database_url)
    try:
        store.check_schema()
        service = GitHubService(store, cfg)
        if args.onboard:
            print(service.onboard())
            return
        if args.retry_failed:
            import sqlalchemy as sa
            from .schema_v5 import deliveries, checks
            with store.engine.begin() as c:
                if not service.binding(c, lock=True)["enabled"]:
                    raise ValueError("verify and onboard the installation before retrying")
                for table in (deliveries, checks):
                    c.execute(table.update().where(table.c.repository_id == service.config.repository_id,
                        table.c.state == "failed").values(state="pending", tries=0, error=None, available_at=sa.func.now()))
            print("Failed GitHub jobs reset; previously published checks unchanged")
            return
        while True:
            worked = service.run_once()
            worked = service.run_once(publishing=True) or worked
            if args.once: return
            if not worked: time.sleep(1)
    finally:
        store.engine.dispose()


if __name__ == "__main__": main()

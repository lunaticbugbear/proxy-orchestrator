"""
Proxy Orchestrator - Analytics & Reporting
Prints stats, generates reports, exports data.
"""

import json
from datetime import datetime


class Analytics:
    """
    Analytics and reporting for the proxy orchestrator.

    Usage:
        analytics = Analytics(orchestrator)
        analytics.print_summary()
        analytics.export_json("report.json")
    """

    def __init__(self, orchestrator):
        self.orch = orchestrator

    def runtime_stats(self) -> list[dict]:
        """Get in-memory runtime stats from the orchestrator."""
        return self.orch.stats()

    def db_stats(self, hours: int = 24) -> list[dict]:
        """Get historical stats from the database."""
        return self.orch.db.get_all_stats(hours)

    def print_summary(self, hours: int = 24):
        """Print a formatted summary to console."""
        runtime = self.runtime_stats()
        db_stats = self.db_stats(hours)

        print("\n" + "=" * 80)
        print(f"  PROXY ORCHESTRATOR - ANALYTICS REPORT ({hours}h window)")
        print("=" * 80)

        # Runtime stats
        print(f"\n  Runtime Stats ({len(runtime)} proxies registered):")
        print(f"  {'Host':<30} {'Region':<8} {'Active':<8} {'Weight':<8} "
              f"{'Success':<10} {'Fail':<8} {'Rate':<8} {'Avg Lat':<10}")
        print("  " + "-" * 96)

        active_count = 0
        total_success = 0
        total_fail = 0

        for p in runtime:
            active = "YES" if p["active"] else "NO"
            if p["active"]:
                active_count += 1
            total_success += p["success_count"]
            total_fail += p["fail_count"]

            print(f"  {p['host'] + ':' + str(p['port']):<30} {p['region']:<8} {active:<8} "
                  f"{p['weight']:<8.3f} {p['success_count']:<10} {p['fail_count']:<8} "
                  f"{p['success_rate']:<8.1f}% {p['avg_latency_ms']:<10.1f}")

        print("  " + "-" * 96)
        total_reqs = total_success + total_fail
        overall_rate = (total_success / total_reqs * 100) if total_reqs > 0 else 0
        print(f"  {'TOTAL':<30} {'':8} {active_count:<8} "
              f"{'':8} {total_success:<10} {total_fail:<8} {overall_rate:<8.1f}%")

        # Pool health
        print(f"\n  Pool Health: {active_count}/{len(runtime)} active")

        if active_count == 0:
            print("  ⚠️  CRITICAL: No active proxies!")
        elif active_count < len(runtime) * 0.5:
            print("  ⚠️  WARNING: Less than 50% proxies active")

        # DB historical stats
        print(f"\n  Historical Stats (last {hours}h from DB):")
        print(f"  {'Host':<30} {'Region':<8} {'Total':<8} {'Rate':<8} "
              f"{'Avg Lat':<10} {'Health':<8}")
        print("  " + "-" * 72)

        for p in db_stats:
            host_port = f"{p['host']}:{p['port']}"
            print(f"  {host_port:<30} {p['region']:<8} {p['total']:<8} "
                  f"{p['success_rate']:<8.1f}% {p['avg_latency']:<10.1f} {p['last_health']:<8}")

        print("\n" + "=" * 80 + "\n")

    def export_json(self, filepath: str, hours: int = 24):
        """Export full report as JSON."""
        report = {
            "generated_at": datetime.now().isoformat(),
            "window_hours": hours,
            "runtime_stats": self.runtime_stats(),
            "db_stats": self.db_stats(hours),
        }
        with open(filepath, "w") as f:
            json.dump(report, f, indent=2)
        print(f"Report exported to {filepath}")

    def top_proxies(self, limit: int = 5) -> list[dict]:
        """Return top N proxies by success rate (min 10 requests)."""
        stats = self.db_stats(24)
        qualified = [s for s in stats if s["total"] >= 10]
        qualified.sort(key=lambda x: (x["success_rate"], -x["avg_latency"]), reverse=True)
        return qualified[:limit]

    def worst_proxies(self, limit: int = 5) -> list[dict]:
        """Return worst N proxies by success rate."""
        stats = self.db_stats(24)
        qualified = [s for s in stats if s["total"] >= 1]
        qualified.sort(key=lambda x: x["success_rate"])
        return qualified[:limit]

"""
RingAround CLI

Commands:
  run      — dial contractors and collect quotes
  summary  — show intel store market summary for a category + zip
  lookup   — show quote history for a specific contractor phone number

Examples:
  ringaround run --category bathroom_remodel --zip 98101 \
                 --description "80 sq ft full bath remodel" --limit 10
  ringaround summary --category bathroom_remodel --zip 98101
  ringaround lookup --phone +12065550101
"""
from __future__ import annotations
import argparse
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


# ------------------------------------------------------------------ helpers

def _fmt_money(v: int | None) -> str:
    return f"${v:,}" if v is not None else "—"


def _fmt_state(state_value: str) -> str:
    return {
        "completed":          "✓ quoted",
        "refused":            "✗ refused",
        "no_answer":          "✗ no answer",
        "callback_scheduled": "⟳ callback",
        "out_of_area":        "✗ out of area",
        "unavailable":        "✗ unavailable",
        "failed":             "! failed",
    }.get(state_value, state_value)


def _print_table(rows: list[tuple], headers: tuple) -> None:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print(fmt.format(*[str(c) for c in row]))


# ------------------------------------------------------------------ run command

async def cmd_run(args) -> int:
    from ringaround.models import ProjectRequest, Job
    from ringaround.factory import build_call_flow, build_directory
    from ringaround.jobs.runner import run_job, summarize_job
    from ringaround.intel.store import IntelStore

    project = ProjectRequest(
        description=args.description,
        zip_code=args.zip,
        category=args.category,
    )

    print(f"\nRingAround — {args.category.replace('_', ' ')} in {args.zip}")
    print(f"Project: {args.description}\n")

    # 1. Find contractors
    directory = build_directory()
    print("Finding contractors...")
    contractors = await directory.find_contractors(project, limit=args.limit)
    if not contractors:
        print("No contractors found. Check DIRECTORY_PROVIDER and API keys.")
        return 1
    print(f"Found {len(contractors)} contractor(s).\n")

    # 2. Maybe start Telnyx server
    server_task = None
    if os.getenv("TELEPHONY_PROVIDER", "mock").lower() == "telnyx":
        server_task = await _start_telnyx_server()

    # 3. Run job
    job = Job(project=project, contractors=contractors)
    flow = build_call_flow()

    print(f"Dialing {len(contractors)} contractor(s)...\n")
    job = await run_job(job, flow)

    if server_task:
        server_task.cancel()

    # 4. Print results table
    rows = []
    for r in job.results:
        if r.got_quote and r.quote:
            price = f"{_fmt_money(r.quote.price_low)} – {_fmt_money(r.quote.price_high)}"
            avail = r.quote.availability
            weeks = f"{r.quote.timeline_weeks}w" if r.quote.timeline_weeks else "—"
        else:
            price = avail = weeks = "—"
        rows.append((
            r.contractor.name[:35],
            _fmt_state(r.final_state.value),
            price,
            avail,
            weeks,
        ))
    _print_table(rows, ("Contractor", "Result", "Price range", "Avail", "Start"))

    # 5. Summary line
    summary = summarize_job(job)
    print(f"\nQuotes: {summary['quotes_received']}/{summary['total_calls']}  "
          f"| Refused: {summary['refused']}  "
          f"| No answer: {summary['no_answer']}  "
          f"| Unavailable: {summary['unavailable']}")

    if summary.get("market_low"):
        print(f"Market range: {_fmt_money(summary['market_low'])} – "
              f"{_fmt_money(summary['market_high'])}  "
              f"| Median: {_fmt_money(summary['market_median'])}")

    # 6. Write to intel store
    intel_path = Path(args.intel_db)
    store = IntelStore(db_path=intel_path)
    await store.init()
    written = await store.record_job(job.id, project.zip_code, job.results)
    if written:
        print(f"\nIntel store: {written} quote(s) written to {intel_path}")

    print()
    return 0


async def _start_telnyx_server() -> asyncio.Task:
    """Start the Telnyx webhook+WS server as a background task."""
    port = int(os.getenv("TELNYX_APP_PORT", "8080"))
    public_url = os.getenv("TELNYX_PUBLIC_URL", f"wss://localhost:{port}")

    from ringaround.telephony.server import create_app
    import uvicorn

    app = create_app(stream_ws_base=public_url)
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning")
    server = uvicorn.Server(config)

    task = asyncio.create_task(server.serve())
    # Give it a moment to bind
    await asyncio.sleep(0.5)
    return task


# ------------------------------------------------------------------ summary command

async def cmd_summary(args) -> int:
    from ringaround.intel.store import IntelStore

    store = IntelStore(db_path=args.intel_db)
    await store.init()

    summary = await store.market_summary(args.category, args.zip, days=args.days)
    activity = await store.zip_activity(args.zip, days=args.days)

    print(f"\nMarket Summary — {args.category.replace('_', ' ')} in {args.zip} "
          f"(last {args.days} days)\n")

    if summary.observation_count == 0:
        print("No observations yet. Run 'ringaround run' to collect data.")
        return 0

    print(f"  Observations : {summary.observation_count}")
    print(f"  Contractors  : {summary.contractor_count} unique")
    print(f"  Price (low)  : p25={_fmt_money(summary.price_low_p25)}  "
          f"median={_fmt_money(summary.price_low_median)}  "
          f"p75={_fmt_money(summary.price_low_p75)}")
    print(f"  Price (high) : median={_fmt_money(summary.price_high_median)}")
    print(f"  Available    : {summary.availability_rate:.0%}")
    if summary.avg_timeline_weeks:
        print(f"  Avg start    : {summary.avg_timeline_weeks} weeks")

    if len(activity) > 1:
        print(f"\nAll categories in {args.zip}:")
        for cat, cnt in activity.items():
            marker = " ◀" if cat == args.category else ""
            print(f"  {cat:<30} {cnt} obs{marker}")

    print()
    return 0


# ------------------------------------------------------------------ lookup command

async def cmd_lookup(args) -> int:
    from ringaround.intel.store import IntelStore

    store = IntelStore(db_path=args.intel_db)
    await store.init()

    history = await store.contractor_history(
        phone=args.phone,
        category=args.category or None,
        days=365,
    )

    if not history:
        print(f"\nNo history found for {args.phone}.")
        return 0

    first = history[-1]
    print(f"\nContractor: {first.contractor_name} ({args.phone})")
    print(f"Observations: {len(history)}\n")

    rows = [
        (
            obs.observed_at.strftime("%Y-%m-%d"),
            obs.category,
            obs.project_zip,
            f"{_fmt_money(obs.price_low)} – {_fmt_money(obs.price_high)}",
            obs.availability,
        )
        for obs in history
    ]
    _print_table(rows, ("Date", "Category", "Zip", "Price range", "Avail"))
    print()
    return 0


# ------------------------------------------------------------------ main

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ringaround",
        description="Outbound voice agent — collect contractor quotes at scale",
    )
    sub = p.add_subparsers(dest="command")

    # run
    run_p = sub.add_parser("run", help="Dial contractors and collect quotes")
    run_p.add_argument("--category", required=True,
                       help="e.g. bathroom_remodel, roofing, hvac")
    run_p.add_argument("--zip", required=True, help="Project zip code")
    run_p.add_argument("--description", required=True,
                       help="Plain-language project description")
    run_p.add_argument("--limit", type=int, default=20,
                       help="Max contractors to dial (default: 20)")
    run_p.add_argument("--intel-db", default="intel.db", metavar="PATH",
                       help="SQLite intel store path (default: intel.db)")

    # summary
    sum_p = sub.add_parser("summary", help="Show market summary from intel store")
    sum_p.add_argument("--category", required=True)
    sum_p.add_argument("--zip", required=True)
    sum_p.add_argument("--days", type=int, default=90,
                       help="Lookback window in days (default: 90)")
    sum_p.add_argument("--intel-db", default="intel.db", metavar="PATH")

    # lookup
    look_p = sub.add_parser("lookup", help="Show a contractor's quote history")
    look_p.add_argument("--phone", required=True, help="E.164 phone number")
    look_p.add_argument("--category", default=None,
                        help="Filter to one category (optional)")
    look_p.add_argument("--intel-db", default="intel.db", metavar="PATH")

    return p


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    handlers = {"run": cmd_run, "summary": cmd_summary, "lookup": cmd_lookup}
    rc = asyncio.run(handlers[args.command](args))
    sys.exit(rc)


if __name__ == "__main__":
    main()

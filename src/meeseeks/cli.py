#!/usr/bin/env python3
"""meeseeks CLI — /cost, /status, basic summon for testing."""
import argparse
from meeseeks.budget import today_total, cost_breakdown


def cmd_cost(args):
    total = today_total()
    breakdown = cost_breakdown(days=1)
    print(f"\nToday: ${total:.4f}")
    if breakdown:
        print("  By meeseeks type:")
        for name, stats in breakdown.items():
            print(f"    {name}: ${stats['llm_cost'] + stats['tool_cost']:.4f} ({stats['spawns']} spawns, {stats['tokens']} tokens)")
    else:
        print("  No runs today.")


def main():
    parser = argparse.ArgumentParser(prog="meeseeks", description="Meeseeks-Core CLI")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("cost", help="Show cost breakdown")

    args = parser.parse_args()
    if args.cmd == "cost":
        cmd_cost(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

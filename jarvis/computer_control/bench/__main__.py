"""``python -m jarvis.computer_control.bench <baseline|suite> [--json FILE]``."""
from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m jarvis.computer_control.bench")
    parser.add_argument("what", choices=["baseline", "suite"], help="which measurement to run")
    parser.add_argument("--json", help="also write the raw numbers to this file")
    parser.add_argument("--pid", type=int, help="sample a running JARVIS process instead")
    parser.add_argument("--seconds", type=float, default=30.0)
    args = parser.parse_args(argv)
    from jarvis.computer_control.bench import baseline
    if args.what == "suite":
        from jarvis.computer_control.bench import suite
        result = suite.run_suite()
        print(suite.to_markdown(result))
        if args.json:
            with open(args.json, "w", encoding="utf-8") as fh:
                json.dump(result.as_dict(), fh, indent=2)
        return 0 if all(x.passed for x in result.scenarios) else 1
    if args.pid:
        report = baseline.sample_process(args.pid, args.seconds)
        print(json.dumps(report, indent=2))
        if args.json:
            with open(args.json, "w", encoding="utf-8") as fh:
                json.dump(report, fh, indent=2)
        return 0
    report = baseline.collect()
    print(baseline.to_markdown(report))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())

import argparse
from pathlib import Path

from .core import RunConfig
from .engine import TestEngine
from .mock import FAULTS, Faults, mock_devices
from .reports import export
from .storage import Store


def main():
    parser = argparse.ArgumentParser(description="GNSS 灵敏度测试")
    parser.add_argument("--mock", action="store_true", help="运行合成设备的命令行闭环")
    parser.add_argument("--output", type=Path, default=Path("results/mock"))
    parser.add_argument("--min-power", type=int, default=-122)
    parser.add_argument("--max-levels", type=int, default=3)
    parser.add_argument("--fault", action="append", choices=FAULTS, default=[])
    args = parser.parse_args()
    if not args.mock:
        from .app import launch
        return launch()
    config = RunConfig(args.min_power, args.max_levels)
    with Store(args.output / "run.sqlite") as store:
        run = store.create_run(config)
        result = TestEngine(store, run, *mock_devices(config, Faults(args.fault))).execute()
        report = export(store, run)
        print(f"MOCK {result['status']} {result['reason']} | {report}")
        return int(result["status"] != "FINISHED")


if __name__ == "__main__":
    raise SystemExit(main())

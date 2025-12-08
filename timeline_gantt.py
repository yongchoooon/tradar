#!/usr/bin/env python3
"""Visualize simulation timelines as a Gantt chart."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib import font_manager

ROLE_COLORS = {
    "특허청 심사관": "#1f77b4",
    "출원인 대리인": "#ff7f0e",
    "심사관": "#2ca02c",
    "리포터": "#d62728",
    "채점자": "#9467bd",
    "최종 리포터": "#111111",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="simulation_timeline 폴더의 JSON을 기반으로 간트차트를 생성합니다.",
    )
    parser.add_argument(
        "run_dir",
        nargs="?",
        default=None,
        help="시각화할 실행 폴더 경로 혹은 run tag (예: 20251208-110657-175678)",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="출력 PNG 경로 (기본: <run_dir>/timeline_gantt.png)",
    )
    return parser.parse_args()


def resolve_run_directory(arg: str | None) -> Path:
    base = Path("logs") / "simulation_timeline"
    if not base.exists():
        raise SystemExit("logs/simulation_timeline 폴더를 찾을 수 없습니다.")
    if not arg:
        dirs = sorted((p for p in base.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime)
        if not dirs:
            raise SystemExit("simulation_timeline 폴더에 실행 기록이 없습니다.")
        return dirs[-1]
    candidate = Path(arg)
    if candidate.is_dir():
        return candidate
    tagged = base / arg
    if tagged.is_dir():
        return tagged
    raise SystemExit(f"실행 폴더를 찾을 수 없습니다: {arg}")


def parse_event_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def load_timelines(run_dir: Path):
    worker_events: Dict[int, List[dict]] = {}
    final_events: List[dict] = []
    for file in sorted(run_dir.glob("*_timeline.json")):
        data = json.loads(file.read_text(encoding="utf-8"))
        app_no = data.get("application_number") or file.stem
        events = data.get("events") or []
        if not isinstance(events, list):
            continue
        for event in events:
            start = event.get("start_time")
            end = event.get("end_time")
            if not start or not end:
                continue
            entry = {
                "app_no": app_no,
                "role": event.get("role"),
                "worker_id": event.get("worker_id"),
                "start": parse_event_time(start),
                "end": parse_event_time(end),
                "model": event.get("model"),
                "input_tokens": event.get("input_tokens"),
                "output_tokens": event.get("output_tokens"),
            }
            if app_no.lower() == "overall" or entry["role"] == "최종 리포터":
                final_events.append(entry)
                continue
            wid = entry["worker_id"]
            if isinstance(wid, int) and wid > 0:
                worker_events.setdefault(wid, []).append(entry)
    for entries in worker_events.values():
        entries.sort(key=lambda item: item["start"])
    final_events.sort(key=lambda item: item["start"])
    return worker_events, final_events


def build_gantt(run_dir: Path, output_path: Path) -> None:
    for font_name in ('NanumGothic', 'NanumSquare', 'NanumSquareRound'):
        matches = [path for path in font_manager.findSystemFonts() if font_name in path]
        if matches:
            prop = font_manager.FontProperties(fname=matches[0])
            plt.rcParams['font.family'] = prop.get_name()
            break
    plt.rcParams['axes.unicode_minus'] = False
    worker_events, final_events = load_timelines(run_dir)
    worker_ids = sorted(worker_events)
    if not worker_ids and not final_events:
        raise SystemExit("시각화할 타임라인 이벤트가 없습니다.")

    total_rows = len(worker_ids) + (1 if final_events else 0)
    fig, ax = plt.subplots(figsize=(14, max(2.5, 1.2 * total_rows)))

    y_labels = []
    for idx, worker_id in enumerate(worker_ids):
        y_labels.append((idx, f"워커 {worker_id}"))
        for event in worker_events[worker_id]:
            start_num = mdates.date2num(event["start"])
            end_num = mdates.date2num(event["end"])
            width = end_num - start_num
            role = event.get("role", "")
            color = ROLE_COLORS.get(role, "#888888")
            label = f"{event['app_no']} / {role}"
            ax.barh(idx, width, left=start_num, height=0.6, color=color, edgecolor='#333333')
            ax.text(start_num + width / 2, idx, label, ha='center', va='center', color='white', fontsize=8)

    if final_events:
        final_row = len(worker_ids)
        y_labels.append((final_row, "최종 리포터"))
        for event in final_events:
            start_num = mdates.date2num(event["start"])
            end_num = mdates.date2num(event["end"])
            width = end_num - start_num
            role = event.get("role") or "최종 리포터"
            color = ROLE_COLORS.get(role, '#555555')
            label = role
            ax.barh(final_row, width, left=start_num, height=0.6, color=color, edgecolor='#333333')
            ax.text(start_num + width / 2, final_row, label, ha='center', va='center', color='white', fontsize=8)

    ax.set_xlabel('시간')
    ax.set_yticks([pos for pos, _ in y_labels])
    ax.set_yticklabels([label for _, label in y_labels])
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
    all_events = [e for events in worker_events.values() for e in events] + final_events
    if all_events:
        start_min = min(event['start'] for event in all_events)
        end_max = max(event['end'] for event in all_events)
        margin = (end_max - start_min) * 0.03
        ax.set_xlim(mdates.date2num(start_min - margin), mdates.date2num(end_max + margin))
    ax.grid(axis='x', linestyle='--', alpha=0.4)
    plt.tight_layout()
    fig.savefig(output_path, dpi=200)
    print(f"간트차트를 생성했습니다: {output_path}")


def main():
    args = parse_args()
    run_dir = resolve_run_directory(args.run_dir)
    output = Path(args.output) if args.output else run_dir / 'timeline_gantt.png'
    build_gantt(run_dir, output)


if __name__ == '__main__':
    main()

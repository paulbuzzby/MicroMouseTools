#!/usr/bin/env python3
"""Telemetry plotting UI for Micromouse logs.

Single-file PySide6 application that:
- accepts drag/drop of one or more telemetry files (.txt / .bin text logs)
- merges runs in filename order (RunXXXX ascending where available)
- computes derived telemetry columns
- renders notebook-equivalent plots in tabs
- supports PNG plot export and optional CSV export
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Iterable, List, Sequence

import numpy as np
import pandas as pd
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


DATA_COLUMNS = [
    "Front Left",
    "Left Angle",
    "Right Angle",
    "Front Right",
    "Distance Count",
    "Maze Location",
    "Forward Speed count",
    "Rotation Speed count",
    "Left Motor Volts Scaled",
    "Right Motor Volts Scaled",
    "Cross Track Error",
    "Steering Correction",
    "loopTick",
]

SENSOR_PATTERN = re.compile(r"Robot Data:\s*\[([^\]]+)\]")
RUN_NUMBER_PATTERN = re.compile(r"run(\d+)", flags=re.IGNORECASE)

MM_PER_COUNT = 0.177836584164
DEG_PER_COUNT = 0.135857142857
MOTOR_SCALE = 0.036

# Plot constants from notebook
START_X = 188
SPACING = 180
RIGHT_THRESHOLD = 50
LEFT_THRESHOLD = 40
FRONT_THRESHOLD = 40


def add_rolling_drop_triggers(
    df: pd.DataFrame,
    cols: Sequence[str] = ("Left Angle", "Right Angle"),
    window: int = 20,
    drop_ratio: float = 0.5,
    min_peak: int = 50,
    refractory: int = 8,
) -> pd.DataFrame:
    out = df.copy()

    for col in cols:
        s = pd.to_numeric(out[col], errors="coerce").fillna(0)
        roll_max = s.rolling(window=window, min_periods=1).max().shift(1)

        raw_trigger = (s < drop_ratio * roll_max) & (roll_max >= min_peak)
        raw_trigger = raw_trigger.fillna(False)

        trig = pd.Series(False, index=out.index)
        last_idx = -10**9
        for i in out.index[raw_trigger]:
            if (i - last_idx) > refractory:
                trig.loc[i] = True
                last_idx = i

        out[f"{col} RollingMax_{window}"] = roll_max
        out[f"{col} DropTriggerRaw"] = raw_trigger
        out[f"{col} TriggerPoint"] = trig

    return out


def _extract_run_number(path: Path) -> int | None:
    m = RUN_NUMBER_PATTERN.search(path.stem)
    if m:
        return int(m.group(1))
    return None


def sort_telemetry_paths(paths: Iterable[Path]) -> List[Path]:
    def key(p: Path):
        n = _extract_run_number(p)
        return (0 if n is not None else 1, n if n is not None else 0, p.name.lower())

    return sorted((Path(p) for p in paths), key=key)


def parse_telemetry_file(path: Path) -> pd.DataFrame:
    rows = []
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            match = SENSOR_PATTERN.search(line)
            if not match:
                continue
            values = [int(x.strip()) for x in match.group(1).split(",")]
            if len(values) == len(DATA_COLUMNS):
                rows.append(values)
    return pd.DataFrame(rows, columns=DATA_COLUMNS)


def derive_columns(df: pd.DataFrame, looptick_scale: float = 100.0) -> pd.DataFrame:
    out = df.copy()

    out["Front sum"] = out["Front Left"] + out["Front Right"]
    out["Front diff"] = out["Front Left"] - out["Front Right"]

    out["Distance Count"] = pd.to_numeric(out["Distance Count"], errors="coerce").fillna(0)
    out["Distance Count Travelled"] = out["Distance Count"].cumsum()
    out["Distance MM"] = out["Distance Count Travelled"] * MM_PER_COUNT

    out["Profile Forward Speed mm"] = out["Forward Speed count"] * MM_PER_COUNT
    out["Profile Rotation Speed deg"] = out["Rotation Speed count"] * DEG_PER_COUNT

    out["LeftVolts"] = out["Left Motor Volts Scaled"] * MOTOR_SCALE
    out["RightVolts"] = out["Right Motor Volts Scaled"] * MOTOR_SCALE

    out["Maze X"] = out["Maze Location"] // 16
    out["Maze Y"] = out["Maze Location"] % 16

    # Treat loopTick as continuous over merged dataframe.
    tick_diff_u16 = (
        out["loopTick"].astype("uint16").diff().fillna(0).astype("uint16")
    )
    out["time_s"] = tick_diff_u16.astype("uint32").cumsum() / float(looptick_scale)

    dt = out["time_s"].diff()
    dd = out["Distance MM"].diff()
    out["Speed_mm_s"] = dd / dt
    bad = (dt <= 0) | dt.isna()
    out.loc[bad, "Speed_mm_s"] = 0

    return out


def combine_runs(paths: Sequence[Path], looptick_scale: float = 100.0) -> pd.DataFrame:
    ordered = sort_telemetry_paths(paths)
    frames = []
    for p in ordered:
        frame = parse_telemetry_file(p)
        if not frame.empty:
            frames.append(frame)

    if not frames:
        return pd.DataFrame(columns=DATA_COLUMNS)

    merged = pd.concat(frames, ignore_index=True)
    return derive_columns(merged, looptick_scale=looptick_scale)


class DropFileList(QListWidget):
    files_dropped = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setSelectionMode(QListWidget.ExtendedSelection)

    def dragEnterEvent(self, event):  # type: ignore[override]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):  # type: ignore[override]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):  # type: ignore[override]
        paths: List[Path] = []
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            p = Path(url.toLocalFile())
            if p.is_file() and p.suffix.lower() in {".txt", ".bin"}:
                paths.append(p)
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            event.ignore()


class PlotTab(QWidget):
    def __init__(self, title: str):
        super().__init__()
        self.title = title
        self.figure = Figure(figsize=(8, 5), tight_layout=True)
        self.canvas = FigureCanvasQTAgg(self.figure)

        layout = QVBoxLayout(self)
        layout.addWidget(self.canvas)

    def draw(self):
        self.canvas.draw_idle()


class TelemetryWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Telemetry UI")
        self.resize(1400, 900)

        self.paths: List[Path] = []
        self.df: pd.DataFrame | None = None

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)

        top = QGridLayout()
        outer.addLayout(top)

        file_box = QGroupBox("Telemetry Inputs (.txt / .bin text logs)")
        file_layout = QVBoxLayout(file_box)

        self.file_list = DropFileList()
        self.file_list.files_dropped.connect(self.add_files)
        file_layout.addWidget(self.file_list)

        file_btns = QHBoxLayout()
        self.btn_add = QPushButton("Add Files…")
        self.btn_clear = QPushButton("Clear")
        file_btns.addWidget(self.btn_add)
        file_btns.addWidget(self.btn_clear)
        file_layout.addLayout(file_btns)

        top.addWidget(file_box, 0, 0, 2, 1)

        cfg_box = QGroupBox("Processing")
        cfg_layout = QVBoxLayout(cfg_box)

        tick_row = QHBoxLayout()
        tick_row.addWidget(QLabel("loopTick scale divisor:"))
        self.loop_tick_scale = QLineEdit("100")
        self.loop_tick_scale.setMaximumWidth(100)
        tick_row.addWidget(self.loop_tick_scale)
        tick_row.addStretch(1)
        cfg_layout.addLayout(tick_row)

        self.chk_export_csv = QCheckBox("Export processed CSV (default off)")
        self.chk_export_csv.setChecked(False)
        cfg_layout.addWidget(self.chk_export_csv)

        self.btn_process = QPushButton("Process + Plot")
        cfg_layout.addWidget(self.btn_process)

        export_row = QHBoxLayout()
        self.btn_save_current = QPushButton("Save Current Plot PNG…")
        self.btn_save_all = QPushButton("Save All Plots PNG…")
        export_row.addWidget(self.btn_save_current)
        export_row.addWidget(self.btn_save_all)
        cfg_layout.addLayout(export_row)

        self.status = QLabel("Drop files or click Add Files…")
        cfg_layout.addWidget(self.status)

        top.addWidget(cfg_box, 0, 1, 1, 1)

        self.tabs = QTabWidget()
        self.tab_sensor_profile = PlotTab("sensorvsprofile")
        self.tab_profile_volts = PlotTab("profilevsvolts")
        self.tab_ema_4row = PlotTab("sensor_ema_4row")
        self.tab_ema_2x2 = PlotTab("sensor_ema_2x2")

        self.tabs.addTab(self.tab_sensor_profile, "Sensor vs Profile")
        self.tabs.addTab(self.tab_profile_volts, "Profile vs Volts")
        self.tabs.addTab(self.tab_ema_4row, "Sensor EMA (4-row)")
        self.tabs.addTab(self.tab_ema_2x2, "Sensor EMA (2x2)")

        outer.addWidget(self.tabs, 1)

        self.btn_add.clicked.connect(self.pick_files)
        self.btn_clear.clicked.connect(self.clear_files)
        self.btn_process.clicked.connect(self.process_and_plot)
        self.btn_save_current.clicked.connect(self.save_current_plot)
        self.btn_save_all.clicked.connect(self.save_all_plots)

    def add_files(self, paths: Sequence[Path]) -> None:
        new_paths = [Path(p) for p in paths]
        combined = {p.resolve(): p for p in self.paths}
        for p in new_paths:
            combined[p.resolve()] = p
        self.paths = sort_telemetry_paths(combined.values())
        self._refresh_file_list()

    def _refresh_file_list(self) -> None:
        self.file_list.clear()
        for p in self.paths:
            item = QListWidgetItem(str(p))
            self.file_list.addItem(item)
        self.status.setText(f"Loaded files: {len(self.paths)}")

    def pick_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select telemetry files",
            "",
            "Telemetry files (*.txt *.bin);;All files (*.*)",
        )
        if files:
            self.add_files([Path(f) for f in files])

    def clear_files(self) -> None:
        self.paths = []
        self.df = None
        self.file_list.clear()
        self.status.setText("Cleared")

    def _get_looptick_scale(self) -> float:
        try:
            scale = float(self.loop_tick_scale.text().strip())
            if scale <= 0:
                raise ValueError
            return scale
        except ValueError:
            raise ValueError("loopTick scale divisor must be a positive number")

    def process_and_plot(self) -> None:
        if not self.paths:
            QMessageBox.warning(self, "No files", "Please add telemetry files first.")
            return

        try:
            scale = self._get_looptick_scale()
        except ValueError as e:
            QMessageBox.warning(self, "Invalid config", str(e))
            return

        self.status.setText("Processing…")
        QApplication.processEvents()

        df = combine_runs(self.paths, looptick_scale=scale)
        if df.empty:
            QMessageBox.warning(self, "No parsed data", "No valid telemetry rows were parsed.")
            self.status.setText("No valid rows parsed")
            return

        self.df = df
        self._plot_sensor_vs_profile(df)
        self._plot_profile_vs_volts(df)
        self._plot_ema_4row(df)
        self._plot_ema_2x2(df)

        if self.chk_export_csv.isChecked():
            default_name = f"{self.paths[0].stem}_combined_data.csv"
            out, _ = QFileDialog.getSaveFileName(
                self,
                "Save processed CSV",
                str(self.paths[0].with_name(default_name)),
                "CSV files (*.csv)",
            )
            if out:
                df.to_csv(out, index=False)

        self.status.setText(f"Processed {len(self.paths)} file(s), {len(df)} rows")

    def _change_x(self, df: pd.DataFrame) -> pd.Series:
        change_x = df.loc[df["Maze Location"].ne(df["Maze Location"].shift()), "Distance MM"]
        return change_x.iloc[1:]

    def _plot_sensor_vs_profile(self, df: pd.DataFrame) -> None:
        fig = self.tab_sensor_profile.figure
        fig.clear()

        _ = add_rolling_drop_triggers(
            df,
            cols=("Left Angle", "Right Angle"),
            window=8,
            drop_ratio=0.5,
            min_peak=50,
            refractory=8,
        )

        x = df["Distance MM"]
        change_x = self._change_x(df)
        rot = df["Profile Rotation Speed deg"]
        rot_left = rot.where(rot >= 0)
        rot_right = (-rot.where(rot <= 0))

        ax_left = fig.add_subplot(2, 1, 1)
        ax_right = fig.add_subplot(2, 1, 2)

        ax_left.axhline(y=LEFT_THRESHOLD, color="black", linestyle="--", linewidth=1, alpha=0.5)
        ax_right.axhline(y=RIGHT_THRESHOLD, color="black", linestyle="--", linewidth=1, alpha=0.5)

        ax_left.plot(x, df["Left Angle"], label="Left Angle", lw=1)
        ax_left.scatter(x, df["Left Angle"], label="Left Angle Raw", s=1)

        ax_right.plot(x, df["Right Angle"], label="Right Angle", lw=1)
        ax_right.scatter(x, df["Right Angle"], label="Right Angle Raw", s=1)

        x_limit_low = 0
        x_limit_high = float(x.max()) if len(x) else 0

        for ax in (ax_left, ax_right):
            ax.set_xlim(left=x_limit_low, right=x_limit_high)
            ax.set_xticks(np.arange(x_limit_low, x_limit_high + 1, 180))
            for xv in change_x:
                ax.axvline(x=xv, color="green", linestyle="--", linewidth=0.8, alpha=0.4)
            ax.axhline(y=0, color="black", linestyle="--", linewidth=1, alpha=0.5)

        ax_speed_left = ax_left.twinx()
        ax_speed_left.plot(x, df["Profile Forward Speed mm"].abs(), color="purple", linewidth=0.5, alpha=0.5, label="Profile Forward Speed mm")
        ax_speed_left.plot(x, rot_left, color="red", linewidth=0.5, alpha=0.5, label="Profile Rotation Speed deg")
        ax_speed_left.plot(x, df["Speed_mm_s"].abs(), color="orange", linewidth=0.5, alpha=0.5, label="Speed mm/s")

        ax_speed_right = ax_right.twinx()
        ax_speed_right.plot(x, df["Profile Forward Speed mm"].abs(), color="purple", linewidth=0.5, alpha=0.5, label="Profile Forward Speed mm")
        ax_speed_right.plot(x, rot_right, color="red", linewidth=0.5, alpha=0.5, label="Profile Rotation Speed deg")
        ax_speed_right.plot(x, df["Speed_mm_s"].abs(), color="orange", linewidth=0.5, alpha=0.5, label="Speed mm/s")
        ax_speed_right.invert_yaxis()

        h1, l1 = ax_left.get_legend_handles_labels()
        h2, l2 = ax_speed_left.get_legend_handles_labels()
        ax_left.legend(h1 + h2, l1 + l2, loc="upper right", fontsize=8)

        ax_right.invert_yaxis()
        ax_left.set_ylabel("Sensor")
        ax_right.set_ylabel("Sensor Reading")
        ax_right.set_xlabel("Distance MM")
        fig.suptitle("Left and Right Angle Sensors + Profile Forward Speed")

        self.tab_sensor_profile.draw()

    def _plot_profile_vs_volts(self, df: pd.DataFrame) -> None:
        fig = self.tab_profile_volts.figure
        fig.clear()

        x = df["Distance MM"]
        change_x = self._change_x(df)
        rot = df["Profile Rotation Speed deg"]
        rot_left = rot.where(rot >= 0)
        rot_right = (-rot.where(rot <= 0))

        ax_left = fig.add_subplot(2, 1, 1)
        ax_right = fig.add_subplot(2, 1, 2)

        x_limit_low = 0
        x_limit_high = float(x.max()) if len(x) else 0

        for ax in (ax_left, ax_right):
            ax.set_xlim(left=x_limit_low, right=x_limit_high)
            ax.set_xticks(np.arange(x_limit_low, x_limit_high + 1, 180))
            for xv in change_x:
                ax.axvline(x=xv, color="green", linestyle="--", linewidth=0.8, alpha=0.4)
            ax.axhline(y=0, color="black", linestyle="--", linewidth=1, alpha=0.5)
            ax.plot(x, df["Profile Forward Speed mm"].abs(), color="purple", linewidth=0.5, alpha=0.5, label="Profile Forward Speed mm")
            ax.plot(x, df["Speed_mm_s"].abs(), color="orange", linewidth=0.5, alpha=0.5, label="Speed mm/s")

        ax_left.plot(x, rot_left, color="red", linewidth=0.8, alpha=0.8, label="Rotation")
        ax_right.plot(x, rot_right, color="red", linewidth=0.8, alpha=0.8, label="Rotation")

        ax_volts_left = ax_left.twinx()
        ax_volts_left.spines["right"].set_position(("outward", 60))
        ax_volts_left.plot(x, df["LeftVolts"], color="tab:blue", linewidth=0.5, alpha=0.5, label="Left Volts")
        ax_volts_left.set_ylabel("Volts", color="tab:blue")
        ax_volts_left.tick_params(axis="y", labelcolor="tab:blue")

        ax_volts_right = ax_right.twinx()
        ax_volts_right.spines["right"].set_position(("outward", 60))
        ax_volts_right.plot(x, df["RightVolts"], color="tab:blue", linewidth=0.5, alpha=0.5, label="Right Volts")
        ax_volts_right.set_ylabel("Volts", color="tab:blue")
        ax_volts_right.tick_params(axis="y", labelcolor="tab:blue")
        ax_volts_right.invert_yaxis()

        ax_left.legend(loc="lower right", fontsize=8)
        ax_right.legend(loc="lower right", fontsize=8)
        ax_left.set_ylabel("Speed mm/s and deg/s")
        ax_left.set_xlabel("Distance MM")
        ax_right.invert_yaxis()
        ax_right.set_ylabel("Speed mm/s and deg/s")
        ax_right.set_xlabel("Distance MM")
        fig.suptitle("Profile and Volts")

        self.tab_profile_volts.draw()

    def _plot_ema_4row(self, df: pd.DataFrame) -> None:
        fig = self.tab_ema_4row.figure
        fig.clear()

        x = df["Distance MM"]
        x_max = float(x.max()) if len(x) else 0
        x_lines = np.arange(START_X, x_max + SPACING, SPACING)

        ax1 = fig.add_subplot(4, 1, 1)
        ax2 = fig.add_subplot(4, 1, 2)
        ax3 = fig.add_subplot(4, 1, 3)
        ax4 = fig.add_subplot(4, 1, 4)

        sensor_cols = ["Front sum", "Left Angle", "Right Angle"]
        w_fast = 0.2
        w_slow = 0.0625

        for ax, col in zip((ax1, ax2, ax3), sensor_cols):
            fast_ema = df[col].ewm(alpha=w_fast, adjust=False).mean()
            slow_ema = df[col].ewm(alpha=w_slow, adjust=False).mean()
            ax.scatter(x, df[col], s=1, alpha=0.35, label="Raw")
            ax.plot(x, fast_ema, lw=1, label=f"Fast EMA (w={w_fast})", alpha=0.5)
            ax.plot(x, (fast_ema - slow_ema).abs(), lw=1, label="|Fast EMA - Slow EMA|", alpha=0.2)
            for xv in x_lines:
                ax.axvline(x=xv, color="black", linestyle="--", linewidth=0.8, alpha=0.4)
            ax.set_title(col)
            ax.set_ylim(top=500, bottom=0)
            ax.legend(loc="upper left", fontsize=8, frameon=True)

        ax1.axhline(y=FRONT_THRESHOLD, color="black", linestyle="--", linewidth=1)
        ax2.axhline(y=LEFT_THRESHOLD, color="black", linestyle="--", linewidth=1)
        ax3.axhline(y=RIGHT_THRESHOLD, color="black", linestyle="--", linewidth=1)
        ax3.invert_yaxis()

        ax4.plot(x, df["Left Angle"], label="Left Angle", lw=1)
        ax4.plot(x, df["Front Left"], label="Front Left", lw=1)
        ax4.plot(x, -df["Right Angle"], label="Right Angle", lw=1)
        ax4.plot(x, -df["Front Right"], label="Front Right", lw=1)
        ax4.plot(x, np.zeros(len(df)), color="k", lw=0.5, ls="--")
        for xv in x_lines:
            ax4.axvline(x=xv, color="black", linestyle="--", linewidth=0.8, alpha=0.4)
        ax4.legend(loc="best", fontsize=8)

        fig.suptitle("Sensor Channels: Value + Fast/Slow Exponential Averages")
        self.tab_ema_4row.draw()

    def _plot_ema_2x2(self, df: pd.DataFrame) -> None:
        fig = self.tab_ema_2x2.figure
        fig.clear()

        ax1 = fig.add_subplot(2, 2, 1)
        ax2 = fig.add_subplot(2, 2, 2)
        ax3 = fig.add_subplot(2, 2, 3)
        ax4 = fig.add_subplot(2, 2, 4)

        sensor_cols = ["Front sum", "Left Angle", "Right Angle", "Front diff"]
        w_fast = 0.2
        w_slow = 0.0625
        x = df["Distance MM"]

        for ax, col in zip((ax1, ax2, ax3, ax4), sensor_cols):
            fast_ema = df[col].ewm(alpha=w_fast, adjust=False).mean()
            slow_ema = df[col].ewm(alpha=w_slow, adjust=False).mean()
            ax.scatter(x, df[col], s=1, alpha=0.35, label="Raw")
            ax.plot(x, fast_ema, lw=1, label=f"Fast EMA (w={w_fast})")
            ax.plot(x, slow_ema, lw=1, label=f"Slow EMA (w={w_slow})")
            ax.plot(x, (fast_ema - slow_ema).abs(), lw=1, label="|Fast EMA - Slow EMA|")
            ax.set_title(col)
            ax.legend(loc="best", fontsize=8)

        fig.suptitle("Sensor Channels: Value + Fast/Slow Exponential Averages")
        self.tab_ema_2x2.draw()

    def _default_png_name(self) -> str:
        names = [p.stem for p in self.paths]
        stem = names[0] if len(names) == 1 else f"{names[0]}_combined"
        return f"{stem}.png"

    def save_current_plot(self) -> None:
        current = self.tabs.currentWidget()
        if not isinstance(current, PlotTab):
            return
        if self.df is None:
            QMessageBox.information(self, "No plot", "Process telemetry data first.")
            return

        default = self._default_png_name().replace(".png", f"_{current.title}.png")
        out, _ = QFileDialog.getSaveFileName(self, "Save current plot", default, "PNG files (*.png)")
        if out:
            current.figure.savefig(out, dpi=300, bbox_inches="tight")
            self.status.setText(f"Saved: {out}")

    def save_all_plots(self) -> None:
        if self.df is None:
            QMessageBox.information(self, "No plot", "Process telemetry data first.")
            return

        out_dir = QFileDialog.getExistingDirectory(self, "Select output folder")
        if not out_dir:
            return

        tabs = [
            self.tab_sensor_profile,
            self.tab_profile_volts,
            self.tab_ema_4row,
            self.tab_ema_2x2,
        ]
        base = self._default_png_name().replace(".png", "")
        for tab in tabs:
            out = Path(out_dir) / f"{base}_{tab.title}.png"
            tab.figure.savefig(out, dpi=300, bbox_inches="tight")

        self.status.setText(f"Saved all plots to: {out_dir}")


def main() -> int:
    app = QApplication(sys.argv)
    window = TelemetryWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

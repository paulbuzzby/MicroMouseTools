from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
from io import StringIO

from pathlib import Path
from datetime import datetime
import re


MM_per_Count = 0.177836584164
DEG_per_Count = 0.135857142857


def next_dated_csv_path(data_dir: Path, when: datetime | None = None) -> Path:
    when = when or datetime.now()
    date_prefix = when.strftime("%Y%m%d")
    pattern = re.compile(rf"^{date_prefix}_(\d+)\.csv$")

    max_n = 0
    for path in data_dir.glob(f"{date_prefix}_*.csv"):
        match = pattern.match(path.name)
        if match:
            max_n = max(max_n, int(match.group(1)))

    return data_dir / f"{date_prefix}_{max_n + 1}.csv"


def latest_dated_csv_path(data_dir: Path) -> Path:
    pattern = re.compile(r"^(\d{8})_(\d+)\.csv$")
    matches = []

    for path in data_dir.glob("*.csv"):
        match = pattern.match(path.name)
        if match:
            date_part = match.group(1)
            run_part = int(match.group(2))
            matches.append((date_part, run_part, path))

    if not matches:
        raise FileNotFoundError(f"No dated CSV files found in {data_dir.resolve()}")

    matches.sort(key=lambda item: (item[0], item[1]))
    return matches[-1][2]


# Same columns as your existing notebook
data_columns = [
    'Front Left',
    'Left Angle',
    'Right Angle',
    'Front Right',
    'Distance Count',
    'Maze Location',
    'Forward Speed count',
    'Rotation Speed count',
    'Left Motor Volts Scaled',
    'Right Motor Volts Scaled',
    'Cross Track Error',
    'Steering Correction',
    'loopTick',
]

sensor_pattern = re.compile(r"Robot Data:\s*\[([^\]]+)\]")



def dataframe_from_pasted_log(log_text: str) -> pd.DataFrame:
    rows = []

    for line in StringIO(log_text):
        match = sensor_pattern.search(line)
        if not match:
            continue

        values = [int(x.strip()) for x in match.group(1).split(",")]
        if len(values) == len(data_columns):
            rows.append(values)

    if not rows:
        raise ValueError("No valid 'Robot Data: [...]' rows found in pasted text.")

    sensor_df = pd.DataFrame(rows, columns=data_columns)

    sensor_df['Front sum'] = sensor_df['Front Left'] + sensor_df['Front Right']
    sensor_df['Front diff'] = sensor_df['Front Left'] - sensor_df['Front Right']

    sensor_df['Distance Count'] = pd.to_numeric(sensor_df['Distance Count'], errors='coerce').fillna(0)
    sensor_df['Distance Count Travelled'] = sensor_df['Distance Count'].cumsum()
    sensor_df['Distance MM'] = sensor_df['Distance Count Travelled'] * MM_per_Count

    sensor_df['Profile Forward Speed mm'] = sensor_df['Forward Speed count'] * MM_per_Count
    sensor_df['Profile Rotation Speed deg'] = sensor_df['Rotation Speed count'] * DEG_per_Count

    sensor_df['LeftVolts'] = sensor_df['Left Motor Volts Scaled'] * 0.036
    sensor_df['RightVolts'] = sensor_df['Right Motor Volts Scaled'] * 0.036

    sensor_df['Maze X'] = sensor_df['Maze Location'] // 16
    sensor_df['Maze Y'] = sensor_df['Maze Location'] % 16

    sensor_df["time_s"] = (
        sensor_df["loopTick"]
        .astype("uint16")
        .diff()
        .fillna(0)
        .astype("uint16")
        .astype("uint32")
        .cumsum()
        / 100
    )

    dt = sensor_df["time_s"].diff()
    dd = sensor_df["Distance MM"].diff()
    sensor_df["Speed_mm_s"] = dd / dt

    bad = (dt <= 0) | dt.isna()
    sensor_df.loc[bad, "Speed_mm_s"] = 0

    return sensor_df



def plot_sensor_vs_profile(
    df,
    *,
    left_threshold: float,
    right_threshold: float,
    title_label: str = "",
    tick_spacing_mm: float = 180.0,
    save_path: Path | None = None,
):
    x_axis = df["Distance MM"]
    rot = df["Profile Rotation Speed deg"]

    rot_left = rot.where(rot >= 0)
    rot_right = -rot.where(rot <= 0)

    change_x = df.loc[df["Maze Location"].ne(df["Maze Location"].shift()), "Distance MM"].iloc[1:]

    fig = plt.figure(figsize=(16, 8))
    ax_left = plt.subplot2grid((2, 1), (0, 0))
    ax_right = plt.subplot2grid((2, 1), (1, 0))

    ax_left.axhline(y=left_threshold, color="black", linestyle="--", linewidth=1, alpha=0.5)
    ax_right.axhline(y=right_threshold, color="black", linestyle="--", linewidth=1, alpha=0.5)

    ax_left.plot(x_axis, df["Left Angle"], label="Left Angle", lw=1)
    ax_left.scatter(x_axis, df["Left Angle"], label="Left Angle", s=1)
    ax_right.plot(x_axis, df["Right Angle"], label="Right Angle", lw=1)
    ax_right.scatter(x_axis, df["Right Angle"], label="Right Angle", s=1)

    for ax in (ax_left, ax_right):
        x1 = float(x_axis.max())
        ax.set_xticks(np.arange(0, x1 + tick_spacing_mm, tick_spacing_mm))
        for x in change_x:
            ax.axvline(x=x, color="green", linestyle="--", linewidth=0.8, alpha=0.4)
        ax.axhline(y=0, color="black", linestyle="--", linewidth=1, alpha=0.5)

    ax_speed_left = ax_left.twinx()
    ax_speed_left.plot(x_axis, df["Profile Forward Speed mm"].abs(), color="purple", linewidth=0.5, label="Profile Forward Speed mm", alpha=0.5)
    ax_speed_left.plot(x_axis, rot_left, color="red", linewidth=0.5, label="Profile Rotation Speed deg", alpha=0.5)
    ax_speed_left.plot(x_axis, df["Speed_mm_s"].abs(), color="orange", linewidth=0.5, label="Speed mm/s", alpha=0.5)

    ax_speed_right = ax_right.twinx()
    ax_speed_right.plot(x_axis, df["Profile Forward Speed mm"].abs(), color="purple", linewidth=0.5, alpha=0.5)
    ax_speed_right.plot(x_axis, rot_right, color="red", linewidth=0.5, alpha=0.5)
    ax_speed_right.plot(x_axis, df["Speed_mm_s"].abs(), color="orange", linewidth=0.5, alpha=0.5)
    ax_speed_right.invert_yaxis()

    h1, l1 = ax_left.get_legend_handles_labels()
    h2, l2 = ax_speed_left.get_legend_handles_labels()
    ax_left.legend(h1 + h2, l1 + l2, loc="upper right")

    ax_left.set_ylabel("Sensor")
    ax_right.invert_yaxis()
    ax_right.set_ylabel("Sensor Reading")
    ax_right.set_xlabel("Distance MM")

    fig.suptitle(f"Left and Right Angle Sensors + Profile Forward Speed ({title_label})", fontsize=16)
    plt.tight_layout(rect=[0, 0, 1, 0.97])

    if save_path is not None:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save_path, dpi=300, bbox_inches="tight")

    return fig, (ax_left, ax_right)




def plot_profile_vs_volts(
    df,
    *,
    title_label: str = "",
    tick_spacing_mm: float = 180.0,
    save_path: Path | None = None,
):
    change_x = df.loc[df["Maze Location"].ne(df["Maze Location"].shift()), "Distance MM"].iloc[1:]

    x_axis = df["Distance MM"]
    x_limit_low = 0.0
    x_limit_high = float(x_axis.max())

    rot = df["Profile Rotation Speed deg"]
    rot_left = rot.where(rot >= 0)
    rot_right = -rot.where(rot <= 0)

    fig = plt.figure(figsize=(16, 8))
    ax_left = plt.subplot2grid((2, 1), (0, 0))
    ax_right = plt.subplot2grid((2, 1), (1, 0))

    for ax in (ax_left, ax_right):
        ax.set_xlim(left=x_limit_low, right=x_limit_high)
        ax.set_xticks(np.arange(x_limit_low, x_limit_high + tick_spacing_mm, tick_spacing_mm))
        for x in change_x:
            ax.axvline(x=x, color="green", linestyle="--", linewidth=0.8, alpha=0.4)
        ax.axhline(y=0, color="black", linestyle="--", linewidth=1, alpha=0.5)
        ax.plot(x_axis, df["Profile Forward Speed mm"].abs(), color="purple", linewidth=0.5, label="Profile Forward Speed mm", alpha=0.5)
        ax.plot(x_axis, df["Speed_mm_s"].abs(), color="orange", linewidth=0.5, label="Speed mm/s", alpha=0.5)

    ax_left.plot(x_axis, rot_left, color="red", linewidth=0.8, alpha=0.8, label="Rotation")
    ax_right.plot(x_axis, rot_right, color="red", linewidth=0.8, alpha=0.8, label="Rotation")

    ax_volts_left = ax_left.twinx()
    ax_volts_left.spines["right"].set_position(("outward", 60))
    ax_volts_left.plot(x_axis, df["LeftVolts"], color="tab:blue", linewidth=0.5, label="Left Volts", alpha=0.5)
    ax_volts_left.set_ylabel("Volts", color="tab:blue")
    ax_volts_left.tick_params(axis="y", labelcolor="tab:blue")

    ax_volts_right = ax_right.twinx()
    ax_volts_right.spines["right"].set_position(("outward", 60))
    ax_volts_right.plot(x_axis, df["RightVolts"], color="tab:blue", linewidth=0.5, label="Right Volts", alpha=0.5)
    ax_volts_right.set_ylabel("Volts", color="tab:blue")
    ax_volts_right.tick_params(axis="y", labelcolor="tab:blue")
    ax_volts_right.invert_yaxis()

    ax_left.legend(loc="lower right")
    ax_left.set_ylabel("Speed mm/s and deg/s")
    ax_left.set_xlabel("Distance MM")

    ax_right.invert_yaxis()
    ax_right.legend(loc="lower right")
    ax_right.set_ylabel("Speed mm/s and deg/s")
    ax_right.set_xlabel("Distance MM")

    fig.suptitle(f"Profile and Volts ({title_label})", fontsize=16)
    plt.tight_layout(rect=[0, 0, 1, 0.97])

    if save_path is not None:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save_path, dpi=300, bbox_inches="tight")

    return fig, (ax_left, ax_right)

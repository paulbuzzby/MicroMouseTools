# F001 Telemetry UI

## 1. Summary
Build a Python desktop telemetry plotting tool that replaces repetitive notebook steps with a drag-and-drop workflow.

Primary goals:
- Load one or many telemetry files from Windows/Linux file explorer drag-and-drop.
- Accept telemetry files that may be named `.bin` but are text-content logs.
- If multiple files are provided, combine them into one ordered dataset before plotting.
- Reproduce all current notebook plots in a tabbed GUI.
- Allow saving rendered plots to local filesystem (PNG).
- Keep implementation in a single Python file for portability.
- CSV export should be optional and default to off.

## 2. Current repository findings
Repository inspection confirms the telemetry workflow currently lives in one notebook:

- `Reporting/RobotDataBuffer.ipynb`
  - **Cell tagged `converttxt`**:
    - Scans `data_dir.glob('*.txt')`.
    - Parses lines with regex `Robot Data:\s*\[([^\]]+)\]`.
    - Current expected telemetry row columns:
      - `Front Left`, `Left Angle`, `Right Angle`, `Front Right`,
      - `Distance Count`, `Maze Location`,
      - `Forward Speed count`, `Rotation Speed count`,
      - `Left Motor Volts Scaled`, `Right Motor Volts Scaled`,
      - `Cross Track Error`, `Steering Correction`, `loopTick`.
    - Computes derived fields:
      - `Front sum`, `Front diff`,
      - cumulative `Distance Count Travelled`, `Distance MM`,
      - `Profile Forward Speed mm`, `Profile Rotation Speed deg`,
      - `LeftVolts`, `RightVolts`,
      - `Maze X`, `Maze Y`,
      - `time_s` (currently computed from `loopTick` delta/cumsum divided by 100),
      - `Speed_mm_s` from distance/time deltas with bad-interval cleanup.
    - Writes `<stem>_data.csv` per input file.
  - **Helper function `align_yaxis(ax1, v1, ax2, v2)`** in a later cell.
  - **Helper function `add_rolling_drop_triggers(...)`** used in plotting analysis.
  - **Cell tagged `sensorvsprofile`**:
    - Loads one CSV (`log_path`), computes trigger dataset via `add_rolling_drop_triggers`.
    - Plots angle sensors + profile speed/rotation and includes `Speed_mm_s` overlay on speed axes.
    - Uses dual-axis plotting and threshold lines.
  - **Cell tagged `profilevsvolts`**:
    - Plots forward/rotation profile plus `Speed_mm_s`, and left/right volts on twin axes.
    - Inverts right-side orientation for mirrored visual comparison.
    - Saves plot image under `data/plots/`.
  - Additional untagged plotting cells generate multi-panel sensor/EMA visualizations.

Other findings:
- No existing standalone GUI app module/script in repo.
- No current binary parser implementation is visible; current parsing path is text-log regex.
- Notebook convention is `data_dir = Path("data")` (relative path), with data currently under `Reporting/data/` in this repository.

## 3. Proposed change
Create a new standalone GUI script (single Python file) that performs:

1. **File intake**
- Drag-and-drop area for telemetry files.
- Fallback file picker button (multi-select).
- Accept text telemetry files, including `.txt` and `.bin` extension variants where content is text log lines.

2. **Multi-file ordering and merge**
- When multiple files are dropped, sort by run number extracted from filename pattern like `RunXXXX.bin` (smallest to largest).
- If no run number is found, fallback to stable filename sort.
- Parse each file and concatenate records into one dataframe.
- Recompute cumulative fields (`Distance Count Travelled`, `Distance MM`) after merge so distance is continuous.
- Treat `loopTick` as continuous across files and recompute `time_s` and `Speed_mm_s` on the combined frame.

3. **Processing parity with notebook**
- Reuse current parse and derived-column logic from `converttxt` cell.
- Reuse trigger logic from `add_rolling_drop_triggers(...)` where needed.
- Preserve current schema checks (`len(values) == len(data_columns)`) behavior unless explicitly changed.

4. **Tabbed plotting UI**
- One tab per current notebook plot group, including tagged and untagged plot cells:
  - `sensorvsprofile`
  - `profilevsvolts`
  - current multi-panel EMA/sensor plots
- Include a refresh/reload action for new files.

5. **Export actions**
- Save current plot (PNG) and/or save all tabs (PNG).
- Optional “Export processed CSV” action (default off).

### GUI framework recommendation
Use **PySide6 (Qt)**.

Rationale:
- accepted dependency,
- native cross-platform DnD support,
- straightforward tab containers (`QTabWidget`),
- robust Matplotlib embedding,
- good Windows/Linux behavior.

## 4. Implementation plan
1. **Define single-file app skeleton**
- One script containing:
  - parser functions,
  - dataframe transform functions,
  - plot builder functions,
  - GUI class.

2. **Extract notebook pipeline into pure functions (inside same file)**
- `parse_telemetry_file(path) -> DataFrame`
- `derive_columns(df) -> DataFrame`
- `compute_time_and_speed(df, looptick_scale=100.0) -> DataFrame`
- `combine_runs(paths) -> DataFrame`
- `add_rolling_drop_triggers(...)` (ported from notebook)

3. **Implement filename run-order sorter**
- Regex extraction for `Run(\d+)` or similar numeric token.
- Sort ascending by extracted number, then by name.

4. **Implement GUI interactions**
- Drag-and-drop handler.
- File picker button.
- Current input list display.
- “Process + Plot” action.
- Config control for loopTick-to-time scale (default 100, configurable).

5. **Implement tabbed plot rendering**
- Build plot tabs matching notebook visual intent.
- Keep axis behavior parity (left/right inversion, twin axes, thresholds, marker lines, and `Speed_mm_s` overlays where used).

6. **Implement save/export actions**
- Save active plot image as PNG.
- Save all plots as PNG to selected directory.
- Optional processed CSV export (disabled by default).

7. **Validation pass**
- Test with single input file.
- Test with multiple files requiring numeric ordering.
- Test merged `loopTick/time_s/Speed_mm_s` continuity.
- Test on Windows and Linux path/drag workflows.

## 5. Risks and constraints
- **Schema drift risk**: telemetry row width changed in notebook already (now includes `Cross Track Error`, `Steering Correction`, `loopTick`), so future format changes are likely.
- **Text-vs-extension ambiguity**: `.bin` extension does not imply binary content here; parser must be content-driven or extension-flexible.
- **Single-file constraint**: maintainability is harder than multi-module design; function boundaries must remain clear.
- **Plot parity risk**: notebook visuals use ad hoc cell state and constants (`start_x`, thresholds); exact matching requires explicit parameter defaults.
- **Cross-platform DnD differences**: Windows/Linux drag payloads may differ and require normalization.
- **Performance**: very large combined runs may need careful redraw strategy in Matplotlib.

## 6. Open questions
1. What exact target path/name should be used for the single-file GUI script in this repository?

## 7. Approval boundary
This spec is planning-only. No source implementation is approved yet.

Before coding, explicit approval is required for:
- final target script path/name,
- any deviation from “all current plots” scope,
- any change to loopTick continuity assumption,
- any change to CSV export default-off behavior.

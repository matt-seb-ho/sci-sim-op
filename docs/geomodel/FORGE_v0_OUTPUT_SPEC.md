# FORGE-v0 output specification (frozen 2026-09-30)

Write every file below into **`/work/`**. Files that are missing, unreadable or in
the wrong format are scored as *missing*. Extra files are ignored.

## Coordinates and conventions (all files)

| thing | convention |
|---|---|
| horizontal | **UTM zone 12N, NAD83**, metres (`x` = easting, `y` = northing) |
| vertical | **elevation**, metres above sea level (NAVD88); up is positive |
| depth (only where named `depth`) | metres **below the local ground surface**, positive down |
| stress | **total** stress, **compression positive**, MPa |
| pore pressure | MPa (gauge or absolute; the 0.1 MPa difference does not matter) |
| temperature | °C |
| azimuth | degrees clockwise from north, in [0, 180) |
| CSV | comma-separated, one header row exactly as given, no comment lines, `.` decimal point |

The model grid is given in `/site/grid/`:
- `cells.csv`: `cell_id,x,y,z`: the **centres** of 137,500 cells (50 m cubes);
- `nodes.csv`: `node_id,x,y,z`: the 145,656 cell **corners** (nodes).

## Required files

### 1. `lithology.csv`: rock unit of every cell

```
cell_id,unit
0,granitoid
1,basin_fill
```
- One row per `cell_id` in `cells.csv` (all 137,500).
- `unit` is exactly `granitoid` (the crystalline basement) or `basin_fill` (everything
  above the basement).

### 2. `granitoid_top.csv`: elevation of the top of the granitoid (the basement contact)

```
x,y,z_top
332000,4260000,<z_top>
```
- A regular 50 m grid covering at least **x 332,000 → 338,000 and y 4,260,000 →
  4,266,000** (121 × 121 = 14,641 points), with `x`, `y` on multiples of 50.
- `z_top` = elevation (m) of the basin-fill → granitoid contact. Where granitoid
  crops out, use the ground elevation.

### 3. `initial_state.csv`: state before any injection, at every node

```
node_id,T_C,P_MPa,Sv_MPa,SHmax_MPa,Shmin_MPa
0,<T>,<P>,<Sv>,<SHmax>,<Shmin>
```
- One row per `node_id` in `nodes.csv` (all 145,656).
- `Sv`, `SHmax`, `Shmin`: total vertical, maximum horizontal and minimum horizontal
  stress magnitudes; `P`: pore pressure; `T`: temperature.

### 4. `state.json`: summary of the stress and thermal state

```json
{
  "SHmax_azimuth_deg": 0.0,
  "stress_regime": "normal",
  "gradients_per_km": {"T_C": 0.0, "P_MPa": 0.0, "Sv_MPa": 0.0, "SHmax_MPa": 0.0, "Shmin_MPa": 0.0}
}
```
- `stress_regime` ∈ `normal` (Sv ≥ SHmax ≥ Shmin), `strike-slip` (SHmax ≥ Sv ≥ Shmin),
  `reverse` (SHmax ≥ Shmin ≥ Sv).
- `gradients_per_km`: the average change per km of **depth** over the model volume.

### 5. `properties.json`: rock properties per unit

```json
{
  "granitoid":  {"permeability_m2": {"value": 0.0, "low": 0.0, "high": 0.0},
                 "porosity": {...}, "youngs_modulus_GPa": {...}, "poissons_ratio": {...},
                 "density_kg_m3": {...}, "thermal_conductivity_W_mK": {...}},
  "basin_fill": {same six keys}
}
```
- Each property: `value` (your best estimate), `low` and `high` (a plausible range).
- `porosity` is a fraction (0–1), not a percentage. Permeability is the bulk (matrix
  plus natural fractures) value at reservoir scale.

### 6. `MODEL_REPORT.md`: how you built it

For every number or surface above: the source file(s) in `/site/` and the reasoning.
Then the key assumptions, and the uncertainties you would reduce first with new data.

## Optional

`fractures.json`: natural fracture sets (orientation, intensity, size). Not scored in v0.

## How it is scored (for your information)

Your model is compared against held-out information about the site: the rock unit of
each cell, the contact surface, the state at each node, the state summary and the
properties. Error is measured in the units above (for permeability, in orders of
magnitude). A field with fewer than 99% of its rows present and numeric is not
scored.

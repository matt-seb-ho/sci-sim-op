It is August 2019. You are the modeler on the Utah FORGE team. Here is every public
dataset about the site published so far. Build the earth model of the reservoir volume
that the team will simulate: which rock is where, the temperature, pressure and stress
before anything is injected, and the rock properties. Document where every number came
from.

The team already has an earth model: the **Phase 2B model of December 2018**, in
`/site/gdr_1107/` (surfaces exported from Leapfrog) and `/site/gdr_1108/` (maps). Since
then, new data have arrived; `/site/NEW_DATA.txt` lists those submissions. Your job is to
**update** the earth model with the new data and deliver it on the grid below.

## What you have

- `/site/` (read-only): the public Utah FORGE datasets published before September 2019,
  one folder per data submission (`gdr_<id>/`). Each folder has an `ABOUT.txt` (title,
  date, authors, description) and the files as published. Archives are still packed;
  unpack them into `/work/` or `/tmp/` if you need them. Some submissions list only
  external links; those are not available.
- `/site/grid/`: the model grid you must fill, `cells.csv` (cell centres) and
  `nodes.csv` (cell corners).
- `/task/FORGE_v0_OUTPUT_SPEC.md`: **the exact files, columns, units and coordinate
  conventions to write. Read it first.**
- `/work/` (writable): your working directory. Your final files go here.

## Tools and limits

- A Linux shell with Python 3 (numpy, scipy, pandas, openpyxl, xlrd, lasio, dlisio,
  shapely, pyproj, matplotlib, pyvista, pdfplumber), `pdftotext` and `unzip`.
- **There is no internet access** and nothing can be installed. Everything you can use
  is in `/site/`.
- You have about **3 hours**. There are roughly 10 GB of data; you will not be able to
  read all of it. Decide what matters, and get a complete first version of every
  required file written early, then improve it.

## Done means

All six required files from the output spec exist in `/work/` and parse, and
`MODEL_REPORT.md` traces every value to the files in `/site/` it came from, and says
what changed from the December 2018 model and why.

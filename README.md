# Outcomes Dashboard

A Streamlit prototype for exploring outcomes coded from partner programs' logic models.

## Views

1. **System-Level Policy Mapping**: treemap or sunburst of domains and subcategories sized by outcome count, plus outcomes per domain stacked by target population.
2. **Program Alignment & Partnership Discovery**: pick an organization to rank peers by shared subcategories (peer matrix and heatmap), or pick a subcategory to see every organization working toward it.
3. **Data Governance & Validation**: a paginated, searchable table of coded outcomes, filtered to low and no-confidence rows by default.

Every chart shows sample outcome statements on hover, and each chart has a drill-down list with a CSV download underneath.

## Run it

```bash
pip install -r requirements.txt
streamlit run app.py
```

Put the export in `data/verified_coded_outcomes(5).csv`. The app also checks next to `app.py` and the current directory. CSV files are git-ignored, so partner data never gets committed. Point it elsewhere with `OUTCOMES_CSV=/path/to/export.csv`. If no file is found, the app offers an upload box.

## Data clean-up

- Missing organization and program names are filled in from the logic model's file name (`<id> - <Organization> - <Program> - Logic Model.pdf`).
- Known spelling variants are merged (see `ORG_ALIASES` in `app.py`).
- Missing categories are labelled `Uncoded`, `Unassigned subcategory` or `unspecified` so they stay visible.
- The sidebar can group organizations by the name in the logic model, or by the grantee named in the file name.

## Reusing the filters

The data functions in `app.py` (`clean_outcomes`, `filter_outcomes`, `compute_peer_overlap`, and so on) make no Streamlit calls, so another script can import them. A future map export, for example, could call `filter_outcomes()` and join the result to organization coordinates.

## Tests

```bash
pip install pytest
python -m pytest
```

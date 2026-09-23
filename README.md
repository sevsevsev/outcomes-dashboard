# Outcomes Explorer

A Streamlit dashboard for exploring outcomes coded from partner programs' logic models by the Qualitative Outcomes Coder.

## Pages

- **System map**: shows where the portfolio concentrates its effort. It has a treemap or sunburst of domains and subcategories, sized by organizations or by outcome statements and shaded by how many organizations work on each goal. It opens on the domains; click one to expand its subcategories, and click back up to return. Labels stay at a readable size, and blocks too small for one show it on hover. Below that are the most and least covered goals, including codebook subcategories that no program targets yet, and a chart of who the outcomes are for.
- **Find peers**: pick an organization to rank its peers by shared goals, then select a peer to compare their outcomes side by side. You can also pick a goal to see every organization working on it.
- **Review coding**: a paginated, searchable table that opens on low and no-confidence rows for a human check.

Hovering over any chart shows sample outcome statements. Every drill-down list has a CSV download.

## Outcome text

The coder splits compound statements into atomic outcomes and codes each one separately. The dashboard shows the atomic outcome as the main text. When a statement was split, the original appears in a "From the full statement" column for context.

## Run it locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

Put the export in `data/verified_coded_outcomes(5).csv`, or point to it with `OUTCOMES_CSV=/path/to/export.csv`. Without a file, the app opens on an upload screen. CSV files are git-ignored, so partner data never gets committed.

## Deploy

Deploy on [Streamlit Community Cloud](https://share.streamlit.io) from this repo, with `main` as the branch and `app.py` as the main file. Vercel and other serverless hosts can't run Streamlit.

The deployed app asks each visitor to upload the CSV. The file lives only in that browser session. The look is set in `.streamlit/config.toml`.

## Code layout

| File | What it holds |
|---|---|
| `app.py` | Page layout, navigation, sidebar filters |
| `charts.py` | Plotly figures and the shared chart theme and palette |
| `outcomes_data.py` | Loading, cleaning, filtering, aggregation. It makes no Streamlit calls, so other tools can import it. |
| `reference/codebook_subcategories.csv` | Every subcategory in the codebook (v1.1.1), used to find goals no program targets. Regenerate it from the coder's `codebooks/original.ts` when the codebook changes. |

### Data clean-up on load

- Missing organization and program names are filled in from the logic model's file name.
- Known spelling variants are merged (see `ORG_ALIASES` in `outcomes_data.py`).
- Missing categories are labelled `Uncoded`, `Unassigned subcategory` or `unspecified`, so they stay visible.

### Reusing the filters

A future map export, for example, could call `outcomes_data.filter_outcomes()` and join the result to organization coordinates.

## Tests

```bash
pip install pytest
python -m pytest
```

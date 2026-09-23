# Outcomes Explorer

A Streamlit dashboard for exploring outcomes coded from partner programs' logic models by the Qualitative Outcomes Coder.

## Pages

Each page opens with a few sentences that state what the data shows, worked out from the loaded file. Charts come next, and clicking a bar or dot narrows the charts and table below it. A **Clear selection** button undoes the clicks.

- **System map**: domains ranked by how many organizations (or outcome statements) they hold. Click a domain to rank its goals and see who those outcomes are for; click a goal or an audience to narrow further. The outcomes table under the charts follows every click. A view switch swaps the ranked bars for a treemap or sunburst. The last section lists the goals with the thinnest coverage, including codebook goals no program targets yet.
- **Find peers**: pick an organization to rank its peers by shared goals, then select a peer to read both organizations' outcomes goal by goal. You can also pick a goal and click an organization to read its outcomes, or compare up to six programs in a dot grid of programs by domain (or by the goals in one domain). Click a dot to list those outcomes.
- **Review coding**: a searchable table that opens on low and no-confidence rows for a human check.

The filter bar at the top of every page holds **Filters** (domain, audience, organization, confidence) and **Data** (the loaded file, a replacement upload, how organizations are grouped, and notes on the measures). The line beside it says how many outcome statements the page is showing. Hovering over any chart shows sample outcome statements, and every list has a CSV download.

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

The deployed app asks each visitor to upload the CSV. The file lives only in that browser session. The look is set in `.streamlit/config.toml` and the CSS at the top of `app.py`: one sans font, a white page, cool greys, and one blue that marks what is selected.

## Code layout

| File | What it holds |
|---|---|
| `app.py` | Page layout, navigation, the filter bar, and the chart clicks that filter tables |
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

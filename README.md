# Outcomes Explorer

A Streamlit dashboard for exploring outcomes coded from partner programs' logic models by the Qualitative Outcomes Coder.

## Pages

A line under the filter bar says what every page shows: outcomes that programs intend, taken from their logic models, not measured results. Each page opens with a few sentences that state what the data shows, worked out from the loaded file. Charts come next, and clicking a bar or dot narrows the charts and table below it. A **Clear selection** button undoes the clicks.

- **What programs aim for**: plain-language priorities (Attendance, Literacy, Social-emotional skills and so on) ranked by how many organizations (or outcome statements) they hold. **Group by** switches to the codebook's own domains. The priorities are defined in `PRIORITIES` in `outcomes_data.py`, and each coded goal belongs to exactly one. Click a priority or domain to rank its goals and see who those outcomes are for; click a goal or an audience to narrow further. The outcomes table under the charts follows every click. The page opens on the **Wheel**: every codebook goal gets an equal slice around its domain, and the length of its bar shows how many programs (or outcome statements, or organizations) name it, so thin goals stay readable and a goal nobody names shows as a short dashed stub. It behaves like the sunburst below: point at a bar to read it, click a domain to open its goals, click a goal to narrow the table. A view switch swaps the wheel for ranked bars, a sunburst or a treemap. The sunburst follows the codebook explorer's design and behaves like it: domains on the inner ring and their goals on the outer ring, one quiet hue per domain, and the total in the middle. Pointing at a slice lifts it out, fades the other domains, and shows its name, its counts and a few sample outcomes beside the chart. It counts programs, outcome statements or organizations. Clicking a domain opens its goals and narrows the outcomes table; clicking a goal narrows it further, and clicking the center goes back. The last section lists the goals with the thinnest coverage, including codebook goals no program targets yet.
- **Find peers**: pick an organization to rank its peers by shared goals, then select a peer to read both organizations' outcomes goal by goal. You can also pick a goal and click an organization to read its outcomes, or compare up to six programs in a dot grid of programs by domain. Click a domain name to see the same grid by that domain's goals (**‹ All domains** goes back), or click a dot to list those outcomes.
- **Partners at a school**: pick a school to see every partner program there, from the district's program-to-school table. The page says how many of the school's partners have coded outcomes, then shows the coded ones in a dot grid of partners by domain (click a domain to see its goals, or a dot to list its outcomes). Partners without coded outcomes stay on the grid as grey "Not yet coded" rows, and the list at the bottom names every partner with its programs. Coded outcomes join to the table on district partner and program IDs, never on names: from `partner_id` and `program_id` columns, a `program_key` such as `54_32`, or the `54_32` in the logic model's file name. Coded programs without IDs can't be placed at a school; the page's **School tables** menu says how many matched.
- **Review coding**: a searchable table that opens on low and no-confidence rows for a human check.

The filter bar at the top of every page holds **Filters** (domain, audience, organization, confidence, and where programs run: zip code, City Council district, learning network and school) and **Data** (the loaded file, a replacement upload, how organizations are grouped, and notes on the measures). The line beside it says how many outcome statements the page is showing. The bar stays under the top bar while the page scrolls (except on phones), with a **Clear** link whenever a filter is on. A filter a page doesn't use (organization on Find peers and the school page, confidence on Review coding, places on the school page) is kept for the other pages, and the line says so. The place filters need the two school tables (loaded from the Filters menu, the school page or `data/`): they keep the outcomes of programs that run at the matching schools, joined on district partner and program IDs, so programs without IDs drop out while a place is picked. Hovering over any chart shows sample outcome statements, and every list has a CSV download.

## Outcome text

The coder splits compound statements into atomic outcomes and codes each one separately. The dashboard shows the atomic outcome as the main text. When a statement was split, the original appears in a "From the full statement" column for context.

## Run it locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

Put the export in `data/verified_coded_outcomes(5).csv`, or point to it with `OUTCOMES_CSV=/path/to/export.csv`. Without a file, the app opens on an upload screen. CSV files are git-ignored, so partner data never gets committed.

The school page also needs two district files: the program-to-school export (columns `PARTNER ID`, `PROGRAM ID`, `EOS CODE`) and the schools table (`ULCS`, `Publication Name`; `Schools.xlsx` keeps it on its "schools" sheet). Put them in `data/` as `.xlsx` or `.csv` and the app finds them by their columns. On the deployed app, drop both on the school page; like the outcomes CSV they stay in the browser session. Everything in `data/` is git-ignored.

## Deploy

Deploy on [Streamlit Community Cloud](https://share.streamlit.io) from this repo, with `main` as the branch and `app.py` as the main file. Vercel and other serverless hosts can't run Streamlit.

The deployed app asks each visitor to upload the CSV. The file lives only in that browser session. The look follows the codebook explorer site and is set in `.streamlit/config.toml` and the CSS at the top of `app.py`: Inter, a white page, slate greys, and one blue that marks what is selected.

## Code layout

| File | What it holds |
|---|---|
| `app.py` | Page layout, navigation, the filter bar, and the chart clicks that filter tables |
| `charts.py` | Plotly figures, the shared chart theme and palette, and the sunburst's data |
| `sunburst_component.py`, `components/codebook_sunburst.*` | The sunburst, drawn as SVG in the browser (a `st.components.v2` component), so hovering and zooming need no rerun. Only a click's result comes back to Python. |
| `schools.py` | The school page's data: reading the district tables, joining coded outcomes on partner and program IDs, a school's partner portfolio and findings. No Streamlit calls. |
| `outcomes_data.py` | Loading, cleaning, filtering, aggregation. It makes no Streamlit calls, so other tools can import it. |
| `reference/codebook_subcategories.csv` | Every subcategory in the codebook (v1.1.1), used to find goals no program targets. Regenerate it from the coder's `codebooks/original.ts` when the codebook changes. |
| `reference/codebook_subcategories_v3.csv` | The same list for codebook 3.x (98 codes such as `Y4.2`), from the coder's `codebooks/youthOutcomesV3.data.ts`. The app compares a file against whichever codebook its codes come from. |

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

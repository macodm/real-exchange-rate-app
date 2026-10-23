# real-exchange-rate-app
Real Exchange Rate App
A clean Streamlit app for comparing two economies using actual monthly IMF price indexes and exchange rates. Built for Python 3.12. Defaults: United States versus Mexico, January 2000 through the current month. You can select months back to January 1976.
Run locally
Put app.py, requirements.txt, and this README.md in the same folder.
python -m venv .venv
Activate the environment on Windows PowerShell:
.venv\Scripts\Activate.ps1
Or on macOS/Linux:
source .venv/bin/activate
Install dependencies and start the app:
python -m pip install -r requirements.txt
streamlit run app.py
If the streamlit command is not found, use python -m streamlit run app.py.
Open the local URL printed in your terminal. Internet access to api.imf.org is required. The first run downloads IMF metadata and observations; later requests are cached. No external data file is needed.
Upload to GitHub
1. Sign in to GitHub and create a repository named real-exchange-rate-app.
2. Set its visibility to Public. You may initialize it with a README.
3. Use Add file → Upload files to upload these three files to the repository root. Replace an automatically generated README with this one.
4. Commit the files. Do not upload your .venv folder, API credentials, or local secret files.
Optional Streamlit Community Cloud deployment
1. Sign in at Streamlit Community Cloud with access to your GitHub repository.
2. Create an app, choose real-exchange-rate-app, select the branch containing these files, and set the entry point to app.py.
3. Select Python 3.12 in the deployment settings and deploy.
4. If your IMF gateway requires an API key, store IMF_API_KEY = "your-key" in Streamlit's app Secrets settings. Never commit the real key to GitHub.
Local optional credentials can be supplied through an IMF_API_KEY environment variable or .streamlit/secrets.toml. Live requests during development worked without a subscription key, but gateway policies can change. A 404 can mean a missing series, a changed endpoint, or an access restriction; the app reports it rather than inventing data.
How to use it
Choose two countries/economies, start and end months, and Real, Nominal, or Both. Country names come from IMF country codelists, filtered to ISO countries/territories plus Kosovo and IMF's G163 Euro area. Being listed does not guarantee monthly coverage. Same-country comparisons are allowed and give a real index of 100 wherever inputs are valid.

Both mode has separate axes: the Real Index on the left and the nominal rate in actual currency units on the right. The dashed line at 100 is the Real Index reference. Missing months break the lines. The CSV includes every selected calendar month, including gaps. Refresh IMF data clears both request caches.
Economics in simple language
- E1(t) and E2(t) are monthly period-average exchange rates, in each currency's units per US dollar.
- S(t) = E2(t) / E1(t) is Country 2 currency units per one Country 1 currency unit.
- P1(t) and P2(t) are the two monthly consumer price indexes.
- RER(t) = S(t) × P1(t) / P2(t).
- RER* is the arithmetic mean of valid RER observations within the selected months.
- Real Index(t) = 100 × RER(t) / RER*.
Example: Country 1 is the US, with E1 = 1; Country 2 is Mexico, with E2 = 20. Then S = 20 Mexican pesos per US dollar. Reversing countries gives 1/20 US dollars per Mexican peso. US dollars per US dollar are always 1; the app uses that currency identity directly.

Above 100 means Country 1 is relatively more expensive than its own selected-period average compared with Country 2. Below 100 means relatively cheaper. This historical comparison does not establish overvaluation, undervaluation, fair value, purchasing-power parity, or an investment recommendation. CPI indexes have arbitrary base years and are not comparable absolute price levels; constant CPI rebasing factors cancel when the RER is divided by its own mean.

Changing the selected dates recomputes the mean and all Real Index values. The mean is calculated after calendar alignment and positive-input validation. It is never calculated over the entire history and then reused for a shorter sample. Nominal rates are never normalized.
IMF API implementation and verification
Official sources:
- IMF API overview and developer portal link
- IMF developer portal / API explorer (sign-in may be required)
- IMF Consumer Price Index dataset
- IMF Exchange Rates dataset
- SDMX REST specification
Base URL: https://api.imf.org/external/sdmx/3.0.

The implementation was checked against live IMF structure and data responses on October 22, 2026 (America/Chicago). The API explorer requires sign-in, so its private Swagger content could not be inspected. Public IMF documentation, the SDMX REST specification, and successful live requests established the request and response schemas used here.

The app dynamically resolves the latest flow version on startup, validates the expected dimension order and required indicator/transformation codes, and stops with a clear error if the schema changes. Verified flows at development time:
Flow	Agency	Version	Key dimensions, in order
CPI	IMF.STA	5.0.0	COUNTRY, INDEX_TYPE, COICOP_1999, TYPE_OF_TRANSFORMATION, FREQUENCY
ER	IMF.STA	4.0.1	COUNTRY, INDICATOR, TYPE_OF_TRANSFORMATION, FREQUENCY


Structure requests use:
/structure/dataflow/IMF.STA/CPI/latest?references=all
/structure/dataflow/IMF.STA/ER/latest?references=all
Accept: application/vnd.sdmx.structure+json;version=2.0.0
Data requests use the SDMX 3.0 path, not a partial key appended directly to the base URL:
/data/dataflow/IMF.STA/CPI/5.0.0/USA.CPI._T.IX.M
/data/dataflow/IMF.STA/ER/4.0.1/MEX.XDC_USD.PA_RT.M
Accept: application/vnd.sdmx.data+csv;version=2.0.0
The live CSV uses TIME_PERIOD values such as 2024-M01, numeric OBS_VALUE, and SCALE (power-of-ten multiplier). The parser validates the series dimensions, applies SCALE, rejects duplicate months, and converts dates to calendar-month periods. The IMF returned a blank placeholder row for an unavailable series; this is treated as no data, not a real observation.

The live endpoint ignored the legacy startPeriod parameter in testing. To avoid relying on that behavior, this app downloads each complete single monthly series and filters it locally to January 1976 onward. It only downloads the selected economies and required common-currency series, not a complete global dataset.

There is no alternate provider, fabricated data, or automatic fallback to an effective exchange-rate index. Successful observation requests are cached for six hours and structure metadata for 24 hours. Network requests have connect/read timeouts and at most two retries for rate limits or temporary server errors. Failed requests are shown to the user and are not cached as successful observations.
Euro area and shared currencies
Explicit Euro area price-series choice: the live key G163.CPI._T.IX.M returned no observations. G163.HICP._T.IX.M returned the IMF's all-items Harmonised Index of Consumer Prices. The app deliberately uses and labels HICP for the Euro area within the IMF CPI dataset. It does not silently substitute another source. The verified HICP series began in December 1999; early selected months therefore remain missing. National economies continue to use their national CPI keys.

Currency routing is date-based, never a missing-value fallback. For euro members, national ER observations are used before euro adoption, and the actual IMF G163.XDC_USD.PA_RT.M series is used from adoption onward. The live German national ER series ended in December 1998, making this change necessary. Two euro members therefore have exactly one euro per euro during common membership, while missing months in G163 remain missing for both. Before January 1999 the Euro area's nominal rate is explicitly unavailable.

The date table includes EU euro members through Bulgaria's January 2026 adoption, and listed microstates/euro users. ECB euro introduction dates document the euro's history. The table is explicit and should be reviewed if membership changes.

Other shared-currency routing uses an actual common-currency IMF series: Senegal for West African CFA francs (XOF), Cameroon for Central African CFA francs (XAF), and Antigua and Barbuda for East Caribbean dollars (XCD). XOF and XAF are distinct currencies and are not treated as the same currency. Mali's XOF routing starts June 1984, Guinea-Bissau's May 1997, and Equatorial Guinea's XAF routing January 1985; the other listed members use these currencies throughout the sample. Source changes are disclosed in the app. These common-currency observations are included in each country's E column because they express that country's currency per USD; they are not claimed to be independent country observations.

Historical references: BEAC history, IMF Guinea-Bissau accession account, and IMF Eastern Caribbean Currency Union overview.
Coverage and limitations
- Every month between the selected endpoints is present, with both endpoints included.
- RER needs finite, strictly positive P1, P2, E1 and E2 values. Zero, negative, infinite and missing inputs invalidate that month's RER. Input columns retain the reported values; derived calculations use only valid inputs.
- A nominal observation can remain available when a CPI observation is missing. No CPI values are inferred from exchange rates.
- No interpolation, forward filling or backward filling is performed. Common-currency routing changes at documented dates, not when a value happens to be missing.
- If no valid RER months exist, RER* and Real Index are blank, and the chart, coverage details and full CSV remain available.
- The current month may not yet be reported. Publication delays, unavailable countries and different series start dates are normal.
- Long samples can cross currency changes. National currency units before adoption differ from euro units afterward. The app warns about this and does not apply an undocumented conversion to earlier values. Select a period within one currency regime for easier interpretation. Other redenominations and breaks are retained as published; inspect IMF country metadata before comparing a long history.
- IMF official/representative rates may differ from parallel-market or transaction rates. CPI baskets and methods can differ across economies. Published data and metadata can be revised.
- Currency-union membership dates are maintained in code; new memberships need a code update. No future membership is inferred.
CSV fields: Month; Country 1; Country 2; Country 1 CPI; Country 2 CPI; each country's exchange rate in local currency per USD; Nominal S(t); RER(t); Selected-period RER*; Real Index(t); Valid RER month. The selected-period mean is repeated on every row when defined, including rows with missing observations. Blank numeric cells mean unavailable values. True/False indicates inclusion in the RER mean.
Validation record
Completed under Python 3.12.14 with the pinned dependencies:
- Installed dependencies successfully; python -m pip check reported no broken requirements. Python syntax compilation passed.
- Retrieved live CPI and exchange-rate metadata, validated both dimension orders, and parsed actual SDMX-CSV 2.0 responses.
- Tested live US/Mexico calculations for January 2000–October 2026: 319 valid RER months out of 322 selected months, with mean Real Index approximately 100. This is a development-time snapshot; published coverage can change.
- Checked rate direction and reciprocal country reversal, calendar-month alignment, exclusion of missing/nonpositive inputs, retained nominal values when CPI is missing, and recalculation of the period mean after changing dates.
- Checked that CSV downloads retain all selected months, including blank observations, and that a no-valid-data period exports successfully.
- Checked all three chart modes, separate nominal/real traces, disabled gap connections, and duplicate-month rejection.
- Used Streamlit's AppTest to execute the app, change both date controls, validate an end-before-start error, select Germany/France, and select the Euro area. These checks completed without application exceptions.
- Retrieved live German and French data and verified their nominal cross-rate is exactly 1 for observed shared-euro months. Retrieved and parsed live Euro area HICP data.
- Injected a service failure to verify clear messages and blank unavailable inputs rather than fabricated values.
Not tested: a public GitHub upload, Community Cloud deployment, every available economy/currency route, every network failure mode, and visual rendering in a full browser. The sign-in-protected IMF Swagger interface was not accessible. No repository or deployment has been created on your behalf. The app has no bundled simulated observations; small synthetic fixtures were used only in internal arithmetic checks.
AI assistance record
- Date: October 22, 2026 (America/Chicago).
- Assistant: Codex, identified by this session as based on GPT-6. The exact serving model/variant identifier was not exposed and is unavailable.
- Full user prompt used to request these files follows verbatim.
<details>
<summary>Full assignment prompt</summary>

Help me build a real exchange rate app for my economics assignment. Create three complete, downloadable files: **app.py, requirements.txt, and README.md**, compatible with **Python 3.12** and ready to upload to a public GitHub repository named **real-exchange-rate-app**.

Use **Streamlit** for the app and **Plotly** for interactive charts. Keep the interface clean and explain the economics in simple language.

**1. Country selection and IMF data**

- Allow users to choose Country 1 and Country 2 from IMF countries and the Euro area. Display readable country names.
- Retrieve monthly IMF CPI and exchange-rate data from January 1976 onward, where available.
- Use the IMF API: [https://api.imf.org/external/sdmx/3.0](https://api.imf.org/external/sdmx/3.0)
- CPI key hint: `{ISO3}.CPI._T.IX.M`
- Exchange-rate key hint: `{ISO3}.XDC_USD.PA_RT.M`
- The IMF uses `G163` for the Euro area.
- Verify the current API documentation, dataflows, dimensions, and response formats before implementing requests. Treat these keys as hints rather than assuming they are complete request URLs.
- Use actual IMF data. Do not silently substitute another source or use simulated data.
- Cache requests and handle timeouts, API failures, missing series, and limited coverage with clear messages.

**2. Correct economic calculations**

Define:

- S(t): units of Country 2 currency per one unit of Country 1 currency.
- P1(t): monthly CPI for Country 1.
- P2(t): monthly CPI for Country 2.
- RER(t) = S(t) × P1(t) / P2(t).

IMF exchange rates are local-currency units per USD. Therefore, if E1(t) and E2(t) are the respective IMF exchange-rate series:

**S(t) = E2(t) / E1(t).**

Handle the United States correctly, using 1 USD per USD if necessary. For countries sharing a currency, ensure the nominal cross-rate is correct.

For the user-selected start and end months:

- Align observations by calendar month.
- Use only months with valid, positive inputs for the RER calculation.
- Calculate RER* as the arithmetic mean of RER(t) over valid months within the selected period.
- Calculate Real Index(t) = 100 × RER(t) / RER*.
- Recalculate RER* and the Real Index whenever the selected period changes.
- Plot nominal S(t) in actual currency units. Do not normalize nominal exchange rates.
- Do not interpolate, forward-fill, or backfill missing data. Preserve gaps and explain coverage limitations, including currency changes where relevant.

**3. Interface and charts**

Include:

- Country 1 and Country 2 selectors.
- Monthly start and end date selectors.
- A Real, Nominal, or Both display option.
- Interactive charts with clear titles, hover information, and axis labels.
- Separate y-axes when Both is selected.
- A horizontal reference line at 100 for the Real Index.
- A clear label for the nominal rate, such as “Mexican pesos per US dollar.”
- A short explanation that values above 100 indicate Country 1 is relatively more expensive than its selected-period average, and values below 100 indicate it is relatively cheaper. Explain that this historical comparison alone does not prove a currency is overvalued or undervalued.
- Coverage information showing the selected period, valid RER months, and missing months.

**4. CSV download**

Provide a download button containing every month within the selected sample period, including months with missing observations.

Include these columns:

- Month
- Country 1 and Country 2
- Country 1 and Country 2 CPI
- Each country’s exchange rate in local currency per USD
- Nominal S(t)
- RER(t)
- Selected-period RER*
- Real Index(t)
- An indicator showing whether the month is valid for the RER calculation

**5. Deliverables and documentation**

Create:

1. **app.py:** complete working application, including data retrieval, calculations, charts, and downloads.
2. **requirements.txt:** all required dependencies, with versions compatible with Python 3.12.
3. **README.md:** simple setup and run instructions, including `streamlit run app.py`, GitHub upload instructions, optional Streamlit Community Cloud deployment instructions, formulas, IMF sources, and data limitations.

In the README, include an “AI assistance record” with this full prompt, the date, and the actual model name if available. If the model name is unavailable, say so rather than guessing.

Verify the exchange-rate direction, monthly alignment, missing-data handling, and recalculation when dates change. Run whatever checks are available and clearly state anything you could not test.

Please build the app and provide the three files, rather than only explaining how to build it. Use reasonable defaults and proceed without asking me routine implementation questions.
</details>

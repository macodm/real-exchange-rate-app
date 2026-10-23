"""Real exchange rates: IMF SDMX 3.0, Python 3.12, Streamlit."""
from __future__ import annotations

from datetime import datetime, timezone
from io import StringIO
import os

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pycountry
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import streamlit as st

BASE = 'https://api.imf.org/external/sdmx/3.0'
FIRST = '1976-01'
# ECB euro introduction dates; no national-currency history is spliced to euros.
EURO = {c: '1999-01' for c in 'AUT BEL DEU ESP FIN FRA IRL ITA LUX NLD PRT G163'.split()}
EURO.update(GRC='2001-01', SVN='2007-01', CYP='2008-01', MLT='2008-01',
            SVK='2009-01', EST='2011-01', LVA='2014-01', LTU='2015-01',
            HRV='2023-01', BGR='2026-01', MNE='2002-01', UVK='2002-01',
            AND='1999-01', MCO='1999-01', SMR='1999-01', VAT='1999-01')
CURRENCY_NAMES = {'USA': ('US dollars', 'US dollar'),
                  'MEX': ('Mexican pesos', 'Mexican peso'),
                  'JPN': ('Japanese yen', 'Japanese yen'),
                  'GBR': ('British pounds', 'British pound'),
                  'CAN': ('Canadian dollars', 'Canadian dollar'),
                  'CHE': ('Swiss francs', 'Swiss franc'),
                  'G163': ('euros', 'euro')}


class IMFError(RuntimeError):
    """Readable data-service or schema failure."""


def request(path: str, accept: str) -> str:
    headers = {'Accept': accept, 'User-Agent': 'real-exchange-rate-app/1.0'}
    # Optional: some IMF gateway configurations require a subscription key.
    key = os.environ.get('IMF_API_KEY', '')
    try:
        key = key or st.secrets.get('IMF_API_KEY', '')
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        pass
    if key:
        headers['Ocp-Apim-Subscription-Key'] = key
    retry = Retry(total=2, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=['GET'], respect_retry_after_header=False)
    try:
        with requests.Session() as session:
            session.mount('https://', HTTPAdapter(max_retries=retry))
            response = session.get(BASE + path, headers=headers, timeout=(10, 45))
        if response.status_code == 204:
            return ''
        if response.status_code in (401, 403):
            raise IMFError('IMF access was denied. Check the IMF API portal and your optional IMF_API_KEY.')
        if response.status_code == 404:
            raise IMFError('IMF returned 404: the series may be unavailable, or the gateway may require an API key.')
        response.raise_for_status()
        return response.text.lstrip('\ufeff')
    except requests.RequestException as exc:
        raise IMFError(f'IMF request failed ({type(exc).__name__}). Try Refresh IMF data later. '
                       'Check your internet connection, IMF service status, and API access.') from exc


@st.cache_data(ttl=86400, show_spinner=False)
def metadata(flow: str) -> dict:
    import json
    raw = request(f'/structure/dataflow/IMF.STA/{flow}/latest?references=all',
                  'application/vnd.sdmx.structure+json;version=2.0.0')
    try:
        data = json.loads(raw)['data']
        item = next(f for f in data['dataflows'] if f['id'] == flow and f['agencyID'] == 'IMF.STA')
        structure_id = item['structure'].split(':')[-1].split('(')[0]
        dsd = next(d for d in data['dataStructures'] if d['id'] == structure_id)
        dimensions = sorted(dsd['dataStructureComponents']['dimensionList']['dimensions'],
                            key=lambda d: d['position'])
        expected = (['COUNTRY', 'INDEX_TYPE', 'COICOP_1999', 'TYPE_OF_TRANSFORMATION', 'FREQUENCY']
                    if flow == 'CPI' else ['COUNTRY', 'INDICATOR', 'TYPE_OF_TRANSFORMATION', 'FREQUENCY'])
        if [d['id'] for d in dimensions] != expected:
            raise ValueError('dimension order changed')
        lists = {c['id']: {x['id']: x.get('names', {}).get('en', x.get('name', x['id']))
                            for x in c.get('codes', [])} for c in data['codelists']}
        required = [('CL_CPI_TYPE_OF_TRANSFORMATION', 'IX'), ('CL_INDEX_TYPE', 'CPI'), ('CL_INDEX_TYPE', 'HICP')] if flow == 'CPI' else [
            ('CL_ER_INDICATOR_PUB', 'XDC_USD'), ('CL_ER_TYPE_OF_TRANSFORMATION', 'PA_RT')]
        for cl, code in required:
            if code not in lists.get(cl, {}):
                raise ValueError(f'missing code {cl}:{code}')
        return {'version': item['version'], 'dimensions': expected, 'lists': lists}
    except (KeyError, ValueError, StopIteration, TypeError) as exc:
        raise IMFError(f'IMF {flow} metadata changed or was unreadable. Update the adapter before continuing.') from exc


def country_catalog(cpi_meta: dict, er_meta: dict) -> dict[str, str]:
    names = {**er_meta['lists'].get('CL_ER_COUNTRY_PUB', {}),
             **cpi_meta['lists'].get('CL_COUNTRY', {})}
    iso = {c.alpha_3 for c in pycountry.countries} | {'UVK', 'XKX', 'G163'}
    return dict(sorted({c: n for c, n in names.items() if c in iso}.items(), key=lambda x: x[1]))


def parse_csv(raw: str, flow: str, country: str) -> pd.Series:
    """Parse the verified SDMX-CSV 2.0 schema; do not infer dates or fill values."""
    empty = pd.Series(dtype=float, index=pd.PeriodIndex([], freq='M'))
    if not raw.strip():
        return empty
    try:
        table = pd.read_csv(StringIO(raw), dtype=str)
        # IMF represents a missing series with a single entirely blank data row.
        table = table.dropna(subset=['TIME_PERIOD', 'OBS_VALUE'], how='all')
        if table.empty:
            return empty
        expected = {'COUNTRY': country, 'FREQUENCY': 'M',
                    'TYPE_OF_TRANSFORMATION': 'IX' if flow == 'CPI' else 'PA_RT'}
        expected.update({'INDEX_TYPE': 'HICP' if country == 'G163' else 'CPI', 'COICOP_1999': '_T'} if flow == 'CPI'
                        else {'INDICATOR': 'XDC_USD'})
        if not set(expected).union({'TIME_PERIOD', 'OBS_VALUE'}).issubset(table.columns):
            raise ValueError('unexpected columns')
        for field, value in expected.items():
            if not table[field].eq(value).all():
                raise ValueError(f'unexpected {field}; refusing mixed series')
        dates = table['TIME_PERIOD'].str.replace(r'^(\d{4})-M(\d{2})$', r'\1-\2', regex=True)
        if not dates.str.fullmatch(r'\d{4}-\d{2}').all():
            raise ValueError('unexpected monthly time format')
        periods = pd.PeriodIndex(dates, freq='M')
        if periods.has_duplicates:
            raise ValueError('duplicate calendar months')
        values = pd.to_numeric(table['OBS_VALUE'], errors='coerce')
        # SCALE is the SDMX power-of-ten multiplier, not a CPI rebasing factor.
        if 'SCALE' in table:
            scale = pd.to_numeric(table['SCALE'].fillna('0'), errors='raise')
            values = values * np.power(10.0, scale)
        series = pd.Series(values.to_numpy(dtype=float), index=periods).sort_index()
        return series.loc[series.index >= pd.Period(FIRST)].replace([np.inf, -np.inf], np.nan)
    except (ValueError, KeyError, TypeError, pd.errors.ParserError) as exc:
        raise IMFError(f'Cannot parse IMF {flow} for {country}: {exc}') from exc


@st.cache_data(ttl=21600, show_spinner=False)
def load_series(flow: str, country: str, version: str) -> pd.Series:
    index_type = 'HICP' if country == 'G163' else 'CPI'
    key = f'{country}.{index_type}._T.IX.M' if flow == 'CPI' else f'{country}.XDC_USD.PA_RT.M'
    # The live endpoint ignored legacy startPeriod in verification. Retrieve one
    # complete series, then strictly filter locally; never rely on server slicing.
    raw = request(f'/data/dataflow/IMF.STA/{flow}/{version}/{key}',
                  'application/vnd.sdmx.data+csv;version=2.0.0')
    return parse_csv(raw, flow, country)


def country_inputs(country: str, metas: dict, end: str) -> tuple[pd.DataFrame, list[str]]:
    months = pd.period_range(FIRST, end, freq='M')
    frame = pd.DataFrame(index=months)
    notes = []
    for flow, column in [('CPI', 'CPI'), ('ER', 'E')]:
        if flow == 'ER' and country == 'USA':
            frame[column] = 1.0
            notes.append('United States: E = 1 USD per USD is a currency identity, not an estimated observation.')
            continue
        try:
            series = load_series(flow, country, metas[flow]['version'])
            frame[column] = series.reindex(months)
        except IMFError as exc:
            frame[column] = np.nan
            notes.append(f'{country} {flow}: {exc}')
        # A change of currency changes the source by date, never by data availability.
        if flow == 'ER':
            routing = currency_route(country)
            if routing is not None:
                source, since, currency = routing
                mask = months >= pd.Period(since)
                try:
                    canonical = load_series('ER', source, metas['ER']['version']).reindex(months)
                    frame.loc[mask, column] = canonical.loc[mask]
                except IMFError as exc:
                    frame.loc[mask, column] = np.nan
                    notes.append(f'{currency} source {source}: {exc}')
                notes.append(f'{country}: from {since}, E uses IMF {source} ({currency} per USD). '
                             'This routes by the currency in use; it does not fill gaps. '
                             'Earlier national currency units may differ.')
        if not frame[column].gt(0).any():
            notes.append(f'{country}: no positive observations available for {flow}.')
    if country == 'G163':
        frame.loc[frame.index < pd.Period('1999-01'), 'E'] = np.nan
        notes.append('Euro area: prices use IMF all-items HICP, because G163 has no national CPI '                     'under the CPI key. Pre-1999 nominal rates are excluded; the euro did not exist.')
    return frame, notes


def currency_route(country: str):
    """Canonical IMF series for shared currencies, with explicit historical dates."""
    if country in EURO:
        return 'G163', EURO[country], 'euros'
    if country in 'BEN BFA CIV NER SEN TGO MLI GNB'.split():
        since = {'MLI': '1984-06', 'GNB': '1997-05'}.get(country, FIRST)
        return 'SEN', since, 'West African CFA francs'
    if country in 'CMR CAF TCD COG GAB GNQ'.split():
        return 'CMR', '1985-01' if country == 'GNQ' else FIRST, 'Central African CFA francs'
    if country in 'ATG DMA GRD KNA LCA VCT AIA MSR'.split():
        return 'ATG', FIRST, 'East Caribbean dollars'
    return None


def calculate(a: pd.DataFrame, b: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    """All arithmetic is recomputed on the selected, complete monthly grid."""
    months = pd.period_range(start, end, freq='M')
    result = pd.DataFrame(index=months)
    for label, source in [('1', a), ('2', b)]:
        for column in ['CPI', 'E']:
            result[column + label] = source[column].reindex(months)
    clean = result.where(np.isfinite(result) & result.gt(0))
    result['Nominal S(t)'] = clean['E2'] / clean['E1']
    result['RER(t)'] = result['Nominal S(t)'] * clean['CPI1'] / clean['CPI2']
    result[['Nominal S(t)', 'RER(t)']] = result[['Nominal S(t)', 'RER(t)']].replace([np.inf, -np.inf], np.nan)
    result['Valid RER month'] = clean.notna().all(axis=1) & result['RER(t)'].gt(0) & result['RER(t)'].notna()
    result['RER(t)'] = result['RER(t)'].where(result['Valid RER month'])
    reference = result.loc[result['Valid RER month'], 'RER(t)'].mean()
    result['Selected-period RER*'] = reference
    result['Real Index(t)'] = 100 * result['RER(t)'] / reference
    return result


def nominal_label(c1: str, c2: str, names: dict, start: str) -> str:
    def units(c, singular=False):
        if c in EURO and start >= EURO[c]:
            return 'euro' if singular else 'euros'
        if c in CURRENCY_NAMES:
            return CURRENCY_NAMES[c][int(singular)]
        return names[c] + (' currency unit' if singular else ' currency units')
    return f'{units(c2)} per {units(c1, True)}'


def chart(frame: pd.DataFrame, display: str, label: str, title: str) -> go.Figure:
    both = display == 'Both'
    fig = make_subplots(specs=[[{'secondary_y': True}]])
    x = frame.index.to_timestamp()
    if display in ('Real', 'Both'):
        fig.add_trace(go.Scatter(x=x, y=frame['Real Index(t)'], name='Real Index',
                                mode='lines', connectgaps=False, line_color='#2563eb',
                                hovertemplate='%{x|%b %Y}<br>Real Index: %{y:.2f}<extra></extra>'), secondary_y=False)
        fig.add_hline(y=100, line_dash='dash', line_color='#64748b', secondary_y=False)
        fig.update_yaxes(title_text='Real Index (selected-period mean = 100)', secondary_y=False)
    if display in ('Nominal', 'Both'):
        fig.add_trace(go.Scatter(x=x, y=frame['Nominal S(t)'], name='Nominal S(t)',
                                mode='lines', connectgaps=False, line_color='#d97706',
                                hovertemplate='%{x|%b %Y}<br>S(t): %{y:.6g}<extra></extra>'), secondary_y=both)
        fig.update_yaxes(title_text=label, secondary_y=both)
    fig.update_layout(title=title, template='plotly_white', hovermode='x unified', height=520,
                      legend=dict(orientation='h', y=1.15), margin=dict(t=100, b=45))
    fig.update_xaxes(title_text='Month')
    fig.update_yaxes(showgrid=False, secondary_y=True, visible=both)
    return fig


def export_csv(frame: pd.DataFrame, name1: str, name2: str) -> bytes:
    out = frame.rename(columns={'CPI1': 'Country 1 CPI', 'CPI2': 'Country 2 CPI',
                                'E1': 'Country 1 exchange rate (local currency per USD)',
                                'E2': 'Country 2 exchange rate (local currency per USD)'}).copy()
    out.insert(0, 'Country 2', name2)
    out.insert(0, 'Country 1', name1)
    out.insert(0, 'Month', out.index.astype(str))
    return out.to_csv(index=False, na_rep='').encode('utf-8-sig')


def main():
    st.set_page_config(page_title='Real Exchange Rate Explorer', page_icon='🌍', layout='wide')
    st.title('Real Exchange Rate Explorer')
    st.write('Compare exchange rates and consumer prices using monthly IMF data.')
    if st.sidebar.button('Refresh IMF data'):
        st.cache_data.clear()
        st.rerun()
    try:
        with st.spinner('Checking IMF data definitions…'):
            metas = {flow: metadata(flow) for flow in ['CPI', 'ER']}
            countries = country_catalog(metas['CPI'], metas['ER'])
        if not {'USA', 'MEX', 'G163'}.issubset(countries):
            raise IMFError('The IMF country catalog is incomplete; please refresh later.')
    except IMFError as exc:
        st.error(str(exc))
        st.info('No alternative source or sample data has been substituted.')
        return
    codes = list(countries)
    cols = st.columns(2)
    c1 = cols[0].selectbox('Country 1', codes, index=codes.index('USA'), format_func=countries.get)
    c2 = cols[1].selectbox('Country 2', codes, index=codes.index('MEX'), format_func=countries.get)
    now = datetime.now(timezone.utc).strftime('%Y-%m')
    months = pd.period_range(FIRST, now, freq='M').astype(str).tolist()
    cols = st.columns([2, 2, 1])
    start = cols[0].selectbox('Start month', months, index=months.index('2000-01'))
    end = cols[1].selectbox('End month', months, index=len(months)-1)
    display = cols[2].selectbox('Display', ['Real', 'Nominal', 'Both'], index=2)
    if start > end:
        st.error('Choose a start month on or before the end month.')
        return
    with st.spinner('Retrieving monthly IMF observations…'):
        a, notes1 = country_inputs(c1, metas, now)
        b, notes2 = (a.copy(), []) if c1 == c2 else country_inputs(c2, metas, now)
    for note in dict.fromkeys(notes1 + notes2):
        st.warning(note)
    frame = calculate(a, b, start, end)
    valid = int(frame['Valid RER month'].sum())
    cols = st.columns(3)
    cols[0].metric('Selected period', f'{start} to {end}')
    cols[1].metric('Valid RER months', f'{valid} / {len(frame)}')
    cols[2].metric('Missing or invalid RER months', len(frame)-valid)
    if valid == 0:
        st.warning('No months have all four valid positive inputs. The real index cannot be calculated. '
                   'Nominal rates and the complete monthly CSV are still available where observed.')
    elif valid < len(frame):
        st.info('Gaps remain blank. The average uses only valid months inside your selected period.')
    label = nominal_label(c1, c2, countries, start)
    st.plotly_chart(chart(frame, display, label, f'{countries[c1]} relative to {countries[c2]}'), use_container_width=True)
    st.caption(f'Nominal S(t): {label}. Exchange rates are monthly period averages, in actual IMF currency units.')
    st.write('**Above 100:** Country 1 is relatively more expensive than its selected-period average. '
             '**Below 100:** it is relatively cheaper. This historical comparison alone does not prove '
             'that a currency is overvalued or undervalued.')
    st.download_button('Download monthly CSV', data=export_csv(frame, countries[c1], countries[c2]),
                       file_name=f'real_exchange_rate_{c1}_{c2}_{start}_{end}.csv', mime='text/csv')
    with st.expander('Coverage and source details', expanded=valid == 0):
        summary = []
        for col, name in [('CPI1', 'Country 1 CPI'), ('CPI2', 'Country 2 CPI'),
                          ('E1', 'Country 1 local currency/USD'), ('E2', 'Country 2 local currency/USD')]:
            s = frame[col].where(np.isfinite(frame[col]) & frame[col].gt(0)).dropna()
            summary.append({'Input': name, 'Positive months': len(s),
                            'First selected observation': str(s.index.min()) if len(s) else 'None',
                            'Last selected observation': str(s.index.max()) if len(s) else 'None'})
        st.dataframe(pd.DataFrame(summary), hide_index=True, width='stretch')
        st.write('Countries/economies come from IMF country codelists; catalog membership does not guarantee '
                 'that the requested monthly series exists. CPI indexes do not measure comparable absolute '
                 'price levels across countries. Their arbitrary base years cancel in the normalized Real Index.')
        st.write('Currency redenominations, reporting changes, CPI breaks and official versus market rates '
                 'can affect interpretation. Values are used as published, without interpolating, filling, '
                 'or silently joining old and new currencies. Review IMF metadata before interpreting a long history.')
        if c1 in EURO or c2 in EURO:
            st.warning('Euro adoption can change national currency units. For euro comparisons, select a '
                       'period after both economies adopted the euro; '
                       'the G163 euro series is used from adoption onward. Missing values in that series stay '
                       'missing. Pre-1999 Euro area ER data is excluded.')
        st.write('For shared currencies, the same monthly currency/USD rate implies S(t) = 1. '
                 'Members of the euro, XOF, XAF and XCD unions use a common IMF currency/USD series '
                 'during their membership, so their cross-rate is exactly 1 when observed. '
                 'No gap is filled using a different country or currency series.')
        st.caption(f"IMF dataflows: CPI {metas['CPI']['version']}; ER {metas['ER']['version']}. "
                   'Data cache: 6 hours; metadata cache: 24 hours. Refresh clears both.')
        st.markdown('[IMF CPI](https://data.imf.org/en/datasets/IMF.STA:CPI) · '
                    '[IMF exchange rates](https://data.imf.org/en/datasets/IMF.STA:ER) · '
                    '[IMF API](https://data.imf.org/en/Resource-Pages/IMF-API)')
    with st.expander('How the calculation works'):
        st.latex(r'S_t=E_{2,t}/E_{1,t},\qquad RER_t=S_tP_{1,t}/P_{2,t}')
        st.latex(r'RER^*=\frac{1}{N}\sum_{t\in\mathrm{valid\ selected\ months}}RER_t,\qquad I_t=100RER_t/RER^*')
        st.write('E is local currency per USD. For example, E1 = 1 for the US and E2 = 20 '
                 'for Mexico gives S = 20 Mexican pesos per US dollar. Changing the dates changes '
                 'the average and every displayed Real Index value. The nominal rate is never normalized.')


if __name__ == '__main__':
    main()

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

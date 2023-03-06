import csv
import datetime
import logging
import multiprocessing
import multiprocessing.pool
import os
import re
import urllib.parse
from dataclasses import dataclass
from collections import defaultdict
from contextlib import contextmanager
from decimal import Decimal
from itertools import chain
from io import BytesIO, IOBase
from pathlib import PurePosixPath
from typing import Optional, Callable

import dateutil
import dateutil.parser
from bs4 import BeautifulSoup
import httpx
from lxml import etree
from lxml.etree import XMLSyntaxError
from stream_unzip import stream_unzip

_COLUMNS = (
    'run_code',
    'company_id',
    'date',
    'file_type',
    'taxonomy',
    'balance_sheet_date',
    'companies_house_registered_number',
    'entity_current_legal_name',
    'company_dormant',
    'average_number_employees_during_period',
    'period_start',
    'period_end',
    'tangible_fixed_assets',
    'debtors',
    'cash_bank_in_hand',
    'current_assets',
    'creditors_due_within_one_year',
    'creditors_due_after_one_year',
    'net_current_assets_liabilities',
    'total_assets_less_current_liabilities',
    'net_assets_liabilities_including_pension_asset_liability',
    'called_up_share_capital',
    'profit_loss_account_reserve',
    'shareholder_funds',
    'turnover_gross_operating_revenue',
    'other_operating_income',
    'cost_sales',
    'gross_profit_loss',
    'administrative_expenses',
    'raw_materials_consumables',
    'staff_costs',
    'depreciation_other_amounts_written_off_tangible_intangible_fixed_assets',
    'other_operating_charges_format2',
    'operating_profit_loss',
    'profit_loss_on_ordinary_activities_before_tax',
    'tax_on_profit_or_loss_on_ordinary_activities',
    'profit_loss_for_period',
)

logger = logging.getLogger(__name__)


@contextmanager
def _get_default_pool():
    # Based on https://stackoverflow.com/a/71503165/1319998 that allows the pool to run
    # inside a daemon, for example in Airflow
    p = multiprocessing.process.current_process()
    daemon_status_set = 'daemon' in p._config
    daemon_status_value = p._config.get('daemon')

    if daemon_status_set:
        del p._config['daemon']

    try:
        with multiprocessing.pool.Pool(processes=max(os.cpu_count() - 1, 1)) as pool:
             yield pool
    finally:
        if daemon_status_set:
            p._config['daemon'] = daemon_status_value


def _xbrl_to_rows(name_xbrl_xml_str):
    name, xbrl_xml_str = name_xbrl_xml_str

    # Slightly hacky way to remove BOM, which is present in some older data
    xbrl_xml_str = BytesIO(xbrl_xml_str[xbrl_xml_str.find(b'<'):])

    # Low level value parsers

    def _date(text):
        return dateutil.parser.parse(text).date()

    def _parse(element, text, parser):
        return \
            parser(element, text.strip()) if text and text.strip() not in ['', '-'] else \
            None

    def _parse_str(element, text):
        return str(text).replace('\n', ' ').replace('"', '')

    def _parse_decimal(element, text):
        sign = -1 if element.get('sign', '') == '-' else +1
        return sign * Decimal(re.sub(r',', '', text)) * Decimal(10) ** Decimal(element.get('scale', '0'))

    def _parse_decimal_with_colon(element, text):
        return _parse(element, re.sub(r'.*: ', '', text), _parse_decimal)

    def _parse_date(element, text):
        return _date(text)

    def _parse_bool(element, text):
        return False if text == 'false' else True if text == 'true' else None

    def _parse_reversed_bool(element, text):
        return False if text == 'true' else True if text == 'false' else None

    # Parsing strategy
    #
    # The XBRL format is a "tagging" format that can tag elements in any order with machine readable metadata.
    # While flexible, this means that it's difficult to efficiently convert to a dataframe.
    #
    # The simplest way to do this would XPath repeatedly to find extract the data for each columnn. This was
    # done in previous versions, but took about 3 times as long as the current solution. The current solution
    # leverages the fact that dictionary lookups are fast, and so constructs dictionaries that can be looked up
    # while iterating through all the elements in the document.

    # Although in some cases a dictionary lookup doesn't seem possible, and so a custom matcher can be defined

    @dataclass
    class _test():
        name: Optional[str]
        search: Callable = lambda element, local_name, attribute_name, context_ref: (element,)

    @dataclass
    class _tn(_test):
        # (Local) Tag name, i.e. withoout namespace
        pass

    @dataclass
    class _av(_test):
        # Attribute value. Matches on the "name" attribute, but stripping off the namespace prefix
        pass

    @dataclass
    class _custom(_test):
        # Custom test when matching on tag name or name attribute isn't enought
        pass

    GENERAL_XPATH_MAPPINGS = {
        'balance_sheet_date': (
            [
                (_av('BalanceSheetDate'), _parse_date),
                (_tn('BalanceSheetDate'), _parse_date),
            ]
        ),
        'companies_house_registered_number': (
            [
                (_av('UKCompaniesHouseRegisteredNumber'), _parse_str),
                (_tn('CompaniesHouseRegisteredNumber'), _parse_str),
            ]
        ),
        'entity_current_legal_name': (
            [
                (_av('EntityCurrentLegalOrRegisteredName'), _parse_str),
                (_tn('EntityCurrentLegalName'), _parse_str),
                (_custom(None, lambda element, local_name, attribute_name, context_ref: element.xpath("./*[local-name()='span'][1]")), _parse_str),
            ]
        ),
        'company_dormant': (
            [
                (_av('EntityDormantTruefalse'), _parse_bool),
                (_av('EntityDormant'), _parse_bool),
                (_tn('CompanyDormant'), _parse_bool),
                (_tn('CompanyNotDormant'), _parse_reversed_bool),
            ]
        ),
        'average_number_employees_during_period': (
            [
                (_av('AverageNumberEmployeesDuringPeriod'), _parse_decimal_with_colon),
                (_av('EmployeesTotal'), _parse_decimal_with_colon),
                (_tn('AverageNumberEmployeesDuringPeriod'), _parse_decimal_with_colon),
                (_tn('EmployeesTotal'), _parse_decimal_with_colon),
            ]
        ),
    }

    PERIODICAL_XPATH_MAPPINGS = {
        # balance sheet
        'tangible_fixed_assets': (
            [
                (_tn('FixedAssets'), _parse_decimal),
                (_av('FixedAssets'), _parse_decimal),
                (_tn('TangibleFixedAssets'), _parse_decimal),
                (_av('TangibleFixedAssets'), _parse_decimal),
                (_av('PropertyPlantEquipment'), _parse_decimal),
            ]
        ),
        'debtors': (
            [
                (_tn('Debtors'), _parse_decimal),
                (_av('Debtors'), _parse_decimal),
            ]
        ),
        'cash_bank_in_hand': (
            [
                (_tn('CashBankInHand'), _parse_decimal),
                (_av('CashBankInHand'), _parse_decimal),
                (_av('CashBankOnHand'), _parse_decimal),
            ]
        ),
        'current_assets': (
            [
                (_tn('CurrentAssets'), _parse_decimal),
                (_av('CurrentAssets'), _parse_decimal),
            ]
        ),
        'creditors_due_within_one_year': (
            [
                (_av('CreditorsDueWithinOneYear'), _parse_decimal),
                (_av('Creditors', lambda element, local_name, attribute_name, context_ref: (element,) if 'WithinOneYear' in element.get('contextRef') else ()), _parse_decimal),
            ]
        ),
        'creditors_due_after_one_year': (
            [
                (_av('CreditorsDueAfterOneYear'), _parse_decimal),
                (_custom(None, lambda element, local_name, attribute_name, context_ref: (element,) if 'Creditors' == local_name and 'AfterOneYear' in context_ref else ()), _parse_decimal)
            ]
        ),
        'net_current_assets_liabilities': (
            [
                (_tn('NetCurrentAssetsLiabilities'), _parse_decimal),
                (_av('NetCurrentAssetsLiabilities'), _parse_decimal),
            ]
        ),
        'total_assets_less_current_liabilities': (
            [
                (_tn('TotalAssetsLessCurrentLiabilities'), _parse_decimal),
                (_av('TotalAssetsLessCurrentLiabilities'), _parse_decimal),
            ]
        ),
        'net_assets_liabilities_including_pension_asset_liability': (
            [
                (_tn('NetAssetsLiabilitiesIncludingPensionAssetLiability'), _parse_decimal),
                (_av('NetAssetsLiabilitiesIncludingPensionAssetLiability'), _parse_decimal),
                (_tn('NetAssetsLiabilities'), _parse_decimal),
                (_av('NetAssetsLiabilities'), _parse_decimal),
            ]
        ),
        'called_up_share_capital': (
            [
                (_tn('CalledUpShareCapital'), _parse_decimal),
                (_av('CalledUpShareCapital'), _parse_decimal),
                (_custom(None, lambda element, local_name, attribute_name, context_ref: (element,) if 'Equity' == attribute_name and 'ShareCapital' in element.get('contextRef', '') else ()), _parse_decimal),
            ]
        ),
        'profit_loss_account_reserve': (
            [
                (_tn('ProfitLossAccountReserve'), _parse_decimal),
                (_av('ProfitLossAccountReserve'), _parse_decimal),
                (_custom(None, lambda element, local_name, attribute_name, context_ref: (element,) if 'Equity' == attribute_name and 'RetainedEarningsAccumulatedLosses' in element.get('contextRef', '') else ()), _parse_decimal),
            ]
        ),
        'shareholder_funds': (
            [
                (_tn('ShareholderFunds'), _parse_decimal),
                (_av('ShareholderFunds'), _parse_decimal),
                (_custom(None,  lambda element, local_name, attribute_name, context_ref: (element,) if 'Equity' == attribute_name and 'segment' not in context_ref else ()), _parse_decimal),
            ]
        ),
        # income statement
        'turnover_gross_operating_revenue': (
            [
                (_tn('TurnoverGrossOperatingRevenue'), _parse_decimal),
                (_av('TurnoverGrossOperatingRevenue'), _parse_decimal),
                (_tn('TurnoverRevenue'), _parse_decimal),
                (_av('TurnoverRevenue'), _parse_decimal),
            ]
        ),
        'other_operating_income': (
            [
                (_tn('OtherOperatingIncome'), _parse_decimal),
                (_av('OtherOperatingIncome'), _parse_decimal),
                (_tn('OtherOperatingIncomeFormat2'), _parse_decimal),
                (_av('OtherOperatingIncomeFormat2'), _parse_decimal),
            ]
        ),
        'cost_sales': (
            [
                (_tn('CostSales'), _parse_decimal),
                (_av('CostSales'), _parse_decimal),
            ]
        ),
        'gross_profit_loss': (
            [
                (_tn('GrossProfitLoss'), _parse_decimal),
                (_av('GrossProfitLoss'), _parse_decimal),
            ]
        ),
        'administrative_expenses': (
            [
                (_tn('AdministrativeExpenses'), _parse_decimal),
                (_av('AdministrativeExpenses'), _parse_decimal),
            ]
        ),
        'raw_materials_consumables': (
            [
                (_tn('RawMaterialsConsumables'), _parse_decimal),
                (_av('RawMaterialsConsumables'), _parse_decimal),
                (_tn('RawMaterialsConsumablesUsed'), _parse_decimal),
                (_av('RawMaterialsConsumablesUsed'), _parse_decimal),
            ]
        ),
        'staff_costs': (
            [
                (_tn('StaffCosts'), _parse_decimal),
                (_av('StaffCosts'), _parse_decimal),
                (_tn('StaffCostsEmployeeBenefitsExpense'), _parse_decimal),
                (_av('StaffCostsEmployeeBenefitsExpense'), _parse_decimal),
            ]
        ),
        'depreciation_other_amounts_written_off_tangible_intangible_fixed_assets': (
            [
                (_tn('DepreciationOtherAmountsWrittenOffTangibleIntangibleFixedAssets'), _parse_decimal),
                (_av('DepreciationOtherAmountsWrittenOffTangibleIntangibleFixedAssets'), _parse_decimal),
                (_tn('DepreciationAmortisationImpairmentExpense'), _parse_decimal),
                (_av('DepreciationAmortisationImpairmentExpense'), _parse_decimal),
            ]
        ),
        'other_operating_charges_format2': (
            [
                (_tn('OtherOperatingChargesFormat2'), _parse_decimal),
                (_av('OtherOperatingChargesFormat2'), _parse_decimal),
                (_tn('OtherOperatingExpensesFormat2'), _parse_decimal),
                (_av('OtherOperatingExpensesFormat2'), _parse_decimal),
            ]
        ),
        'operating_profit_loss': (
            [
                (_tn('OperatingProfitLoss'), _parse_decimal),
                (_av('OperatingProfitLoss'), _parse_decimal),
            ]
        ),
        'profit_loss_on_ordinary_activities_before_tax': (
            [
                (_tn('ProfitLossOnOrdinaryActivitiesBeforeTax'), _parse_decimal),
                (_av('ProfitLossOnOrdinaryActivitiesBeforeTax'), _parse_decimal),
            ]
        ),
        'tax_on_profit_or_loss_on_ordinary_activities': (
            [
                (_tn('TaxOnProfitOrLossOnOrdinaryActivities'), _parse_decimal),
                (_av('TaxOnProfitOrLossOnOrdinaryActivities'), _parse_decimal),
                (_tn('TaxTaxCreditOnProfitOrLossOnOrdinaryActivities'), _parse_decimal),
                (_av('TaxTaxCreditOnProfitOrLossOnOrdinaryActivities'), _parse_decimal),
            ]
        ),
        'profit_loss_for_period': (
            [
                (_tn('ProfitLoss'), _parse_decimal),
                (_av('ProfitLoss'), _parse_decimal),
                (_tn('ProfitLossForPeriod'), _parse_decimal),
                (_av('ProfitLossForPeriod'), _parse_decimal),
            ]
        ),
    }

    ALL_MAPPINGS = dict(**GENERAL_XPATH_MAPPINGS, **PERIODICAL_XPATH_MAPPINGS)

    TAG_NAME_TESTS = {
        test.name: (name, priority, test, parser)
        for (name, tests) in ALL_MAPPINGS.items()
        for (priority, (test, parser)) in enumerate(tests)
        if isinstance(test, _tn)
    }

    ATTRIBUTE_VALUE_TESTS = {
        test.name: (name, priority, test, parser)
        for (name, tests) in ALL_MAPPINGS.items()
        for (priority, (test, parser)) in enumerate(tests)
        if isinstance(test, _av)
    }

    CUSTOM_TESTS = tuple(
        (name, priority, test, parser)
        for (name, tests) in ALL_MAPPINGS.items()
        for (priority, (test, parser)) in enumerate(tests)
        if isinstance(test, _custom)
    )

    def _get_dates(context):
        instant_elements = context.xpath("./*[local-name()='instant']")
        start_date_text_nodes = context.xpath("./*[local-name()='startDate']/text()")
        end_date_text_nodes = context.xpath("./*[local-name()='endDate']/text()")
        return \
            (None, None) if context is None else \
            (instant_elements[0].text.strip(), instant_elements[0].text.strip()) if instant_elements else \
            (None, None) if start_date_text_nodes[0] is None or end_date_text_nodes[0] is None else \
            (start_date_text_nodes[0].strip(), end_date_text_nodes[0].strip())

    document = etree.parse(xbrl_xml_str, etree.XMLParser(ns_clean=True, recover=True))
    context_dates = {
        e.get('id'): _get_dates(e.xpath("./*[local-name()='period']")[0])
        for e in document.xpath("//*[local-name()='context']")
    }

    fn = os.path.basename(name)
    mo = re.match(r'^(Prod\d+_\d+)_([^_]+)_(\d\d\d\d\d\d\d\d)\.(html|xml)', fn)
    run_code, company_id, date, filetype = mo.groups()
    allowed_taxonomies = [
        'http://www.xbrl.org/uk/fr/gaap/pt/2004-12-01',
        'http://www.xbrl.org/uk/gaap/core/2009-09-01',
        'http://xbrl.frc.org.uk/fr/2014-09-01/core',
    ]

    core_attributes = (
        run_code,
        company_id,
        _date(date),
        filetype,
        ';'.join(set(allowed_taxonomies) & set(document.getroot().nsmap.values())),
    )

    # Mutable dictionaries to store the "priority" (lower is better) of a found value
    general_attributes_with_priorities = {
        name: (10, None)
        for name in GENERAL_XPATH_MAPPINGS.keys()
    }
    periodic_attributes_with_priorities = defaultdict(lambda: {
        name: (10, None)
        for name in PERIODICAL_XPATH_MAPPINGS.keys()
    })

    def tag_name_tests(local_name):
        try:
            yield from (TAG_NAME_TESTS[local_name],)
        except KeyError:
            pass

    def attribute_value_tests(attribute_value):
        try:
            yield from (ATTRIBUTE_VALUE_TESTS[attribute_value],)
        except KeyError:
            pass

    def handle_general(element, local_name, attribute_value, context_ref, name, priority, test, parse):
        best_priority, best_value = general_attributes_with_priorities[name]

        if priority > best_priority:
            return

        for element in test.search(element, local_name, attribute_value, context_ref):
            value = _parse(element, element.text, parse)
            if value is not None:
                general_attributes_with_priorities[name] = (priority, value)
                break

    def handle_periodic(element, local_name, attribute_value, context_ref, name, priority, test, parse):
        if not context_ref:
            return
        dates = context_dates[context_ref]
        if not dates:
            return

        for element in test.search(element, local_name, attribute_value, context_ref):
            best_priority, best_value = periodic_attributes_with_priorities[dates][name]

            if priority >= best_priority:
                return

            value = _parse(element, element.text, parse)
            if value is not None:
                periodic_attributes_with_priorities[dates][name] = (priority, value)
                break

    for element in document.xpath('//*'):
        _, _, local_name = element.tag.rpartition('}')
        _, _, attribute_value = element.get('name', '').rpartition(':')
        context_ref = element.get('contextRef', '')

        for name, priority, test, parse in chain(tag_name_tests(local_name), attribute_value_tests(attribute_value), CUSTOM_TESTS):
            handler = \
                handle_general if name in general_attributes_with_priorities else \
                handle_periodic

            handler(element, local_name, attribute_value, context_ref, name, priority, test, parse)

    general_attributes = tuple(
        general_attributes_with_priorities[name][1]
        for name in GENERAL_XPATH_MAPPINGS.keys()
    )

    periods = tuple(
        (datetime.date.fromisoformat(period_start_end[0]), datetime.date.fromisoformat(period_start_end[1]))
        + tuple(
            periodic_attributes[name][1]
            for name in PERIODICAL_XPATH_MAPPINGS.keys()
        )
        for period_start_end, periodic_attributes in periodic_attributes_with_priorities.items()
    )
    sorted_periods = sorted(periods, key=lambda period: (period[0], period[1]), reverse=True)

    return \
        tuple((core_attributes + general_attributes + period) for period in sorted_periods) if sorted_periods else \
        ((core_attributes + general_attributes + (None,) * (2 + len(PERIODICAL_XPATH_MAPPINGS))),)


@contextmanager
def stream_read_xbrl_zip(
    zip_bytes_iter,
    get_pool=_get_default_pool,
):
    with get_pool() as pool:
        yield _COLUMNS, (
            row
            for results in pool.imap(_xbrl_to_rows, ((name.decode(), b''.join(chunks)) for name, _, chunks in stream_unzip(zip_bytes_iter)))
            for row in results
        )


@contextmanager
def stream_read_xbrl_daily_all(
    url='https://download.companieshouse.gov.uk/en_accountsdata.html',
    get_client=lambda: httpx.Client(timeout=60.0, transport=httpx.HTTPTransport(retries=3)),
    get_pool=_get_default_pool,
    allow_404=True,
):
    with get_client() as client:
        all_links = BeautifulSoup(httpx.get(url).content, "html.parser").find_all('a')
        zip_urls = [
            link.attrs['href'] if link.attrs['href'].strip().startswith('http://') or link.attrs['href'].strip().startswith('https://') else
            urllib.parse.urljoin(url, link.attrs['href'])
            for link in all_links
            if link.attrs.get('href', '').endswith('.zip')
        ]

        def rows():
            for zip_url in zip_urls:
                with client.stream('GET', zip_url) as r:
                    try:
                        r.raise_for_status()
                    except httpx.HTTPStatusError:
                        if r.status_code != 404 or not allow_404:
                            raise
                        else:
                            for _ in r.iter_bytes(chunk_size=65536):
                                pass
                            continue

                    with stream_read_xbrl_zip(r.iter_bytes(chunk_size=65536), get_pool=get_pool) as (_, rows):
                        yield from rows

        yield _COLUMNS, rows()


@contextmanager
def stream_read_xbrl_sync(
    ingest_data_after_date=datetime.date(datetime.MINYEAR, 1, 1),
    data_urls=(
        'https://download.companieshouse.gov.uk/en_accountsdata.html',
        'https://download.companieshouse.gov.uk/en_monthlyaccountsdata.html',
        'https://download.companieshouse.gov.uk/historicmonthlyaccountsdata.html',
    ),
    get_client = lambda: httpx.Client(timeout=60.0, transport=httpx.HTTPTransport(retries=3)),
):
    def extract_start_end_dates(url):
        file_basename = os.path.basename(url)
        file_name_no_ext = os.path.splitext(file_basename)[0]

        if 'JanToDec' in file_name_no_ext or 'JanuaryToDecember' in file_name_no_ext:
            file_name_no_ext = os.path.splitext(url)[0]
            year = file_name_no_ext[-4:]
            return datetime.date(int(year), 1, 1), datetime.date(int(year), 12, 31)
        elif 'Accounts_Monthly_Data' in file_name_no_ext:
            # Extract the year and month from the string
            year = int(file_name_no_ext[-4:])
            month_name = file_name_no_ext.split('-')[1][:-4]
            # Convert the month name to a month number
            month_num = datetime.datetime.strptime(month_name, '%B').month
            # Calculate the last date of the month
            first_day_of_month = datetime.date(year, month_num, 1)
            next_month = datetime.date(year, month_num, 28) + datetime.timedelta(days=4)
            last_day_of_month = next_month - datetime.timedelta(days=next_month.day)
            return (first_day_of_month, last_day_of_month)
        elif 'Accounts_Bulk_Data' in file_name_no_ext:
            date_str = file_name_no_ext.split('-', 1)[1]
            day = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
            return (day, day)
        else:
            return (None, None)

    def get_content(client, url):
        r = httpx.get(url)
        r.raise_for_status()
        return r.content

    dummy_list_to_ingest = [
        (datetime.date(2021, 5, 2), (('1', '2'), ('3', '4'))),
        (datetime.date(2022, 2, 8), (('5', '6'), ('7', '8'))),
    ]

    with get_client() as client:
        pages_of_links = [
            (data_url, BeautifulSoup(get_content(client, data_url), 'html.parser').find_all('a'))
            for data_url in data_urls
        ]

        all_zip_urls = [
            link.attrs['href'].strip() if link.attrs['href'].strip().startswith('http://') or link.attrs['href'].strip().startswith('https://') else
            urllib.parse.urljoin(data_url, link.attrs['href'].strip())
            for (data_url, page_of_links) in pages_of_links
            for link in page_of_links
            if link.attrs.get('href', '').endswith('.zip')
        ]

        all_zip_urls_with_dates = [
            (zip_url, extract_start_end_dates(zip_url))
            for zip_url in all_zip_urls
        ]

        all_zip_urls_with_parseable_dates = [
            (zip_url, dates)
            for (zip_url, dates) in all_zip_urls_with_dates
            if dates != (None, None)
        ]

        all_zip_urls_with_dates_oldest_first = sorted(
            all_zip_urls_with_parseable_dates, key=lambda zip_start_end: (zip_start_end[1][0], zip_start_end[1][1])
        )

        # Only include files whose ranges are only completely included in one file - itself
        # - This is required since daily files are often also included in monthly files
        # - This also removes duplicates, just in case
        # - This is N^2, but hopefully not big enough list to worry about its performance
        def num_overlaps(start, end):
            num_overlaps  = 0
            for _, (start_to_compare, end_to_compare) in all_zip_urls_with_dates_oldest_first: 
                if start_to_compare <= start and end <= end_to_compare:
                    num_overlaps += 1
            return num_overlaps
        all_zip_urls_with_dates_without_overlaps = [
            (zip_url, (start, end))
            for (zip_url, (start, end)) in all_zip_urls_with_dates_oldest_first
            if num_overlaps(start, end) == 1
        ]

        zip_urls_with_date_in_range_to_ingest = [
            (zip_url, (start_date, end_date))
            for (zip_url, (start_date, end_date)) in all_zip_urls_with_dates_without_overlaps
            if (start_date, end_date) != (None, None) and end_date > ingest_data_after_date
        ]

        def _final_date_and_rows():
            for zip_url, (start_date, end_date) in zip_urls_with_date_in_range_to_ingest:
                with client.stream('GET', zip_url) as r:
                    r.raise_for_status()
                    with stream_read_xbrl_zip(r.iter_bytes(chunk_size=65536)) as (_, rows):
                        yield end_date, rows

        yield (_COLUMNS, _final_date_and_rows())


def stream_read_xbrl_sync_s3_csv(s3_client, bucket_name, key_prefix):

    def _to_file_like_obj(iterable):
        chunk = b''
        offset = 0
        it = iter(iterable)

        def up_to_iter(size):
            nonlocal chunk, offset

            while size:
                if offset == len(chunk):
                    try:
                        chunk = next(it)
                    except StopIteration:
                        break
                    else:
                        offset = 0
                to_yield = min(size, len(chunk) - offset)
                offset = offset + to_yield
                size -= to_yield
                yield chunk[offset - to_yield : offset]

        class FileLikeObj(IOBase):
            def readable(self):
                return True

            def read(self, size=-1):
                return b''.join(
                    up_to_iter(float('inf') if size is None or size < 0 else size)
                )

        return FileLikeObj()

    def _convert_to_csv(columns, rows):
        class PseudoBuffer:
            def write(self, value):
                return value.encode("utf-8")

        pseudo_buffer = PseudoBuffer()
        csv_writer = csv.writer(pseudo_buffer, quoting=csv.QUOTE_NONNUMERIC)
        yield csv_writer.writerow(columns)
        yield from (csv_writer.writerow(row) for row in rows)

    s3_paginator = s3_client.get_paginator('list_objects_v2')
    dates = (
        datetime.date.fromisoformat(PurePosixPath(content['Key']).stem)
        for page in s3_paginator.paginate(Bucket=bucket_name, Prefix=key_prefix)
        for content in page.get('Contents', ())
    )
    latest_completed_date = max(dates, default=datetime.date(datetime.MINYEAR, 1, 1))

    with stream_read_xbrl_sync(latest_completed_date) as (columns, final_date_and_rows):
        for (final_date, rows) in final_date_and_rows:
            key = f'{key_prefix}{final_date}.csv'
            logger.info('Saving Companies House accounts data to %s/%s ...', bucket_name, key)
            csv_file = _to_file_like_obj(_convert_to_csv(columns, rows))
            s3_client.upload_fileobj(Bucket=bucket_name, Key=key, Fileobj=csv_file)
            logger.info('Saving Companies House accounts data to %s/%s (done)', bucket_name, key)

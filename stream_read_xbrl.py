import datetime
import os
import re
import urllib.parse
from collections import OrderedDict
from contextlib import contextmanager
from io import BytesIO

import dateutil
import dateutil.parser
from bs4 import BeautifulSoup
import httpx
from lxml import etree
from lxml.etree import XMLSyntaxError
from stream_unzip import stream_unzip


def stream_read_xbrl_zip(zip_bytes_iter):

    # XPATH helpers
    # XML element syntax: <ns:name attribute='value'>content</ns:name>
    def _element_has_name(name):
        return f"//*[local-name()='{name}']"

    def _element_has_attr_value(attr_value):
        return (
            f"//*[contains(@name, ':{attr_value}') "
            f"and substring-after(@name, ':{attr_value}') = '']"
        )

    def _element_has_name_or_attr_value(value):
        return (
            f"//*[local-name()='{value}' or (contains(@name, ':{value}') "
            f"and substring-after(@name, ':{value}') = '')]"
        )

    # aliases
    _en = _element_has_name
    _av = _element_has_attr_value
    _en_av = _element_has_name_or_attr_value

    # {attribute: ([xpath_expressions], attribute_type)}
    #   attribute: identifier for financial attribute
    #   xpath_expressions: xpaths that will be tried to locate
    #   financial attribute in XBRL tree (until a value is found)
    #   attribute_type: type used to parse the attribute value
    GENERAL_XPATH_MAPPINGS = {
        'balance_sheet_date': (
            [
                _av('BalanceSheetDate'),
                _en('BalanceSheetDate'),
            ],
            datetime.date,
        ),
        'companies_house_registered_number': (
            [
                _av('UKCompaniesHouseRegisteredNumber'),
                _en('CompaniesHouseRegisteredNumber'),
            ],
            str,
        ),
        'entity_current_legal_name': (
            [
                _av('EntityCurrentLegalOrRegisteredName'),
                _en('EntityCurrentLegalName'),
                (
                    "(//*[contains(@name, ':EntityCurrentLegalOrRegisteredName') "
                    "and substring-after(@name, ':EntityCurrentLegalOrRegisteredName') = '']"
                    "//*[local-name()='span'])[1]"
                ),
            ],
            str,
        ),
        'company_dormant': (
            [
                _av('EntityDormantTruefalse'),
                _av('EntityDormant'),
                _en('CompanyDormant'),
                _en('CompanyNotDormant'),
            ],
            [bool, bool, bool, 'reversed_bool'],
        ),
        'average_number_employees_during_period': (
            [
                _av('AverageNumberEmployeesDuringPeriod'),
                _av('EmployeesTotal'),
                _en('AverageNumberEmployeesDuringPeriod'),
                _en('EmployeesTotal'),
            ],
            'float_with_colon',
        ),
    }

    PERIODICAL_XPATH_MAPPINGS = {
        # balance sheet
        'tangible_fixed_assets': (
            [
                _en_av('FixedAssets'),
                _en_av('TangibleFixedAssets'),
                _av('PropertyPlantEquipment'),
            ],
            float,
        ),
        'debtors': (
            [
                _en_av('Debtors'),
            ],
            float,
        ),
        'cash_bank_in_hand': (
            [
                _en_av('CashBankInHand'),
                _av('CashBankOnHand'),
            ],
            float,
        ),
        'current_assets': (
            [
                _en_av('CurrentAssets'),
            ],
            float,
        ),
        'creditors_due_within_one_year': (
            [
                _av('CreditorsDueWithinOneYear'),
                (
                    "//*[contains(@name, ':Creditors') and substring-after(@name, ':Creditors')"
                    " = '' and contains(@contextRef, 'WithinOneYear')]"
                ),
            ],
            float,
        ),
        'creditors_due_after_one_year': (
            [
                _av('CreditorsDueAfterOneYear'),
                (
                    "//*[contains(@name, ':Creditors') and substring-after(@name, ':Creditors')"
                    " = '' and contains(@contextRef, 'AfterOneYear')]"
                ),
            ],
            float,
        ),
        'net_current_assets_liabilities': (
            [
                _en_av('NetCurrentAssetsLiabilities'),
            ],
            float,
        ),
        'total_assets_less_current_liabilities': (
            [
                _en_av('TotalAssetsLessCurrentLiabilities'),
            ],
            float,
        ),
        'net_assets_liabilities_including_pension_asset_liability': (
            [
                _en_av('NetAssetsLiabilitiesIncludingPensionAssetLiability'),
                _en_av('NetAssetsLiabilities'),
            ],
            float,
        ),
        'called_up_share_capital': (
            [
                _en_av('CalledUpShareCapital'),
                (
                    "//*[contains(@name, ':Equity') and substring-after(@name, ':Equity') = '' "
                    "and contains(@contextRef, 'ShareCapital')]"
                ),
            ],
            float,
        ),
        'profit_loss_account_reserve': (
            [
                _en_av('ProfitLossAccountReserve'),
                (
                    "//*[contains(@name, ':Equity') and substring-after(@name, ':Equity') = '' "
                    "and contains(@contextRef, 'RetainedEarningsAccumulatedLosses')]"
                ),
            ],
            float,
        ),
        'shareholder_funds': (
            [
                _en_av('ShareholderFunds'),
                (
                    "//*[contains(@name, ':Equity') and substring-after(@name, ':Equity') = '' "
                    "and not(contains(@contextRef, 'segment'))]"
                ),
            ],
            float,
        ),
        # income statement
        'turnover_gross_operating_revenue': (
            [
                _en_av('TurnoverGrossOperatingRevenue'),
                _en_av('TurnoverRevenue'),
            ],
            float,
        ),
        'other_operating_income': (
            [
                _en_av('OtherOperatingIncome'),
                _en_av('OtherOperatingIncomeFormat2'),
            ],
            float,
        ),
        'cost_sales': (
            [
                _en_av('CostSales'),
            ],
            float,
        ),
        'gross_profit_loss': (
            [
                _en_av('GrossProfitLoss'),
            ],
            float,
        ),
        'administrative_expenses': (
            [
                _en_av('AdministrativeExpenses'),
            ],
            float,
        ),
        'raw_materials_consumables': (
            [
                _en_av('RawMaterialsConsumables'),
                _en_av('RawMaterialsConsumablesUsed'),
            ],
            float,
        ),
        'staff_costs': (
            [
                _en_av('StaffCosts'),
                _en_av('StaffCostsEmployeeBenefitsExpense'),
            ],
            float,
        ),
        'depreciation_other_amounts_written_off_tangible_intangible_fixed_assets': (
            [
                _en_av('DepreciationOtherAmountsWrittenOffTangibleIntangibleFixedAssets'),
                _en_av('DepreciationAmortisationImpairmentExpense'),
            ],
            float,
        ),
        'other_operating_charges_format2': (
            [
                _en_av('OtherOperatingChargesFormat2'),
                _en_av('OtherOperatingExpensesFormat2'),
            ],
            float,
        ),
        'operating_profit_loss': (
            [
                _en_av('OperatingProfitLoss'),
            ],
            float,
        ),
        'profit_loss_on_ordinary_activities_before_tax': (
            [
                _en_av('ProfitLossOnOrdinaryActivitiesBeforeTax'),
            ],
            float,
        ),
        'tax_on_profit_or_loss_on_ordinary_activities': (
            [
                _en_av('TaxOnProfitOrLossOnOrdinaryActivities'),
                _en_av('TaxTaxCreditOnProfitOrLossOnOrdinaryActivities'),
            ],
            float,
        ),
        'profit_loss_for_period': (
            [
                _en_av('ProfitLoss'),
                _en_av('ProfitLossForPeriod'),
            ],
            float,
        ),
    }

    # columns names used to store the companies financial attributes
    columns = (
        ['run_code', 'company_id', 'date', 'file_type', 'taxonomy', 'period_start', 'period_end']
        + [key for key in GENERAL_XPATH_MAPPINGS.keys()]
        + [key for key in PERIODICAL_XPATH_MAPPINGS.keys()]
    )

    def xbrl_to_rows(name, xbrl_xml_str):

        def _populate_general_attributes(document, attribute, row):
            xpath_expressions = GENERAL_XPATH_MAPPINGS.get(attribute)[0]
            for xpath in xpath_expressions:
                # retrieve value only if not found already
                if row[columns.index(attribute)] == None:
                    for e in document.xpath(xpath):
                        attr_type = _get_attribute_type(
                            GENERAL_XPATH_MAPPINGS, attribute, xpath
                        )
                        row[columns.index(attribute)] = _get_value(e, attr_type)

        def _populate_periodical_attributes(document, contexts, attribute, value_by_period):
            xpath_expressions = PERIODICAL_XPATH_MAPPINGS.get(attribute)[0]
            for xpath in xpath_expressions:
                for e in document.xpath(xpath):
                    attr_type = _get_attribute_type(
                        PERIODICAL_XPATH_MAPPINGS, attribute, xpath
                    )
                    context_ref_attr = e.xpath('@contextRef')
                    if context_ref_attr:
                        context = contexts[context_ref_attr[0]]
                        if context is not None:
                            dates = _get_dates(context)
                            if dates != (None, None):
                                if dates not in value_by_period:  # create new row
                                    values = [None] * len(columns)
                                    values[columns.index(attribute)] = _get_value(
                                        e, attr_type
                                    )
                                    value_by_period[dates] = values
                                else:  # update row
                                    values = value_by_period[dates]
                                    # retrieve value only if not found already
                                    if values[columns.index(attribute)] == None:
                                        values[columns.index(attribute)] = _get_value(
                                            e, attr_type
                                        )
            return value_by_period

        def _get_attribute_type(mappings, attribute, xpath):
            attr_type = mappings.get(attribute)[1]
            if isinstance(attr_type, list):
                index = mappings.get(attribute)[0].index(xpath)
                return attr_type[index]
            return attr_type

        def _get_dates(context):
            if context is None:
                return None, None
            instant = context.xpath("./*[local-name()='instant']")
            if instant:
                v = instant[0].text
                return v, v
            else:
                start_date = context.xpath("./*[local-name()='startDate']/text()")[0]
                end_date = context.xpath("./*[local-name()='endDate']/text()")[0]
                if start_date is None or end_date is None:
                    return None, None
                return start_date, end_date

        def _get_contexts(document):
            contexts = {}
            for e in document.xpath("//*[local-name()='context']"):
                contexts[e.get('id')] = e.xpath("./*[local-name()='period']")[0]
            return contexts

        def _get_value(element, type):
            if element.text and element.text.strip() not in ['', '-']:
                text = element.text.strip()
            else:
                return None
            if type == str:
                return str(text).replace('\n', ' ').replace('"', '')
            if type == float:
                sign = -1 if element.get('sign', '') == '-' else +1
                return sign * float(re.sub(r',', '', text)) * 10 ** int(element.get('scale', '0'))
            if type == 'float_with_colon':
                element.text = re.sub(r'.*: ', '', element.text)
                return _get_value(element, float)
            if type == datetime.date:
                return dateutil.parser.parse(text).date()
            if type == bool:
                return False if text == 'false' else True if text == 'true' else None
            if type == 'reversed_bool':
                return False if text == 'true' else True if text == 'false' else None

        document = etree.parse(xbrl_xml_str, etree.XMLParser(ns_clean=True))
        contexts = _get_contexts(document)
        value_by_period = OrderedDict()

        # retrieve periodical attribute values
        for attribute in PERIODICAL_XPATH_MAPPINGS:
            _populate_periodical_attributes(document, contexts, attribute, value_by_period)

        # if no periodical attributes found, create empty row for general attributes
        if not value_by_period:
            value_by_period[(None, None)] = [None] * len(columns)

        fn = os.path.basename(name)
        mo = re.match(r'^(Prod\d+_\d+)_([^_]+)_(\d\d\d\d\d\d\d\d)\.(html|xml)', fn)
        run_code, company_id, date, filetype = mo.groups()

        for period, row in value_by_period.items():
            row[columns.index('run_code')] = run_code
            row[columns.index('company_id')] = company_id
            row[columns.index('date')] = dateutil.parser.parse(date).date()
            row[columns.index('file_type')] = filetype
            allowed_taxonomies = [
                'http://www.xbrl.org/uk/fr/gaap/pt/2004-12-01',
                'http://www.xbrl.org/uk/gaap/core/2009-09-01',
                'http://xbrl.frc.org.uk/fr/2014-09-01/core',
            ]
            row[columns.index('taxonomy')] = ';'.join(
                set(allowed_taxonomies) & set(document.getroot().nsmap.values())
            )
            row[columns.index('period_start')] = None if period[0] is None else dateutil.parser.parse(period[0]).date()
            row[columns.index('period_end')] = None if period[1] is None else dateutil.parser.parse(period[1]).date()
            for attribute in GENERAL_XPATH_MAPPINGS:
                _populate_general_attributes(document, attribute, row)
            yield row

    return tuple(columns), (
        row
        for name, _, chunks in stream_unzip(zip_bytes_iter)
        for row in xbrl_to_rows(name.decode(), BytesIO(b''.join(chunks)))
    )


@contextmanager
def stream_read_xbrl_daily_all(
    url='http://download.companieshouse.gov.uk/en_accountsdata.html',
    get_client=lambda: httpx.Client(transport=httpx.HTTPTransport(retries=3)),
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
                    _, rows = stream_read_xbrl_zip(r.iter_bytes(chunk_size=65536))
                    yield from rows

        # Allows us to get the columns before actually iterating the real data
        columns, _ = stream_read_xbrl_zip(())

        yield columns, rows()

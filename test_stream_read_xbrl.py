import re
from datetime import date
from decimal import Decimal

import boto3
import httpx
import pytest
from moto import mock_s3

from stream_read_xbrl import (
    stream_read_xbrl_zip,
    stream_read_xbrl_daily_all,
    stream_read_xbrl_sync,
    stream_read_xbrl_sync_s3_csv,
)

expected_data = ({
    'administrative_expenses': None,
    'average_number_employees_during_period': Decimal('0.02'),  # Strange, but the source seems to say this
    'balance_sheet_date': None,
    'called_up_share_capital': None,
    'cash_bank_in_hand': Decimal('214222'),
    'companies_house_registered_number': '09355500',
    'company_dormant': None,
    'company_id': '09355500',
    'cost_sales': None,
    'creditors_due_after_one_year': None,
    'creditors_due_within_one_year': None,
    'current_assets': Decimal('259832'),
    'date': date.fromisoformat('2022-12-31'),
    'debtors': None,
    'depreciation_other_amounts_written_off_tangible_intangible_fixed_assets': None,
    'entity_current_legal_name': 'SUGANTHI & VELAVAN LTD',
    'file_type': 'html',
    'gross_profit_loss': None,
    'net_assets_liabilities_including_pension_asset_liability': Decimal('375004'),
    'net_current_assets_liabilities': Decimal('215234'),
    'operating_profit_loss': None,
    'other_operating_charges_format2': None,
    'other_operating_income': None,
    'period_end': date.fromisoformat('2022-12-31'),
    'period_start': date.fromisoformat('2022-12-31'),
    'profit_loss_account_reserve': None,
    'profit_loss_for_period': None,
    'profit_loss_on_ordinary_activities_before_tax': None,
    'raw_materials_consumables': None,
    'run_code': 'Prod223_3384',
    'shareholder_funds': Decimal('200'),
    'staff_costs': None,
    'tangible_fixed_assets': Decimal('159770'),
    'tax_on_profit_or_loss_on_ordinary_activities': None,
    'taxonomy': '',
    'total_assets_less_current_liabilities': None,
    'turnover_gross_operating_revenue': None,
}, {
    'administrative_expenses': None,
    'average_number_employees_during_period': Decimal('0.02'),  # Strange, but the source seems to say this
    'balance_sheet_date': None,
    'called_up_share_capital': None,
    'cash_bank_in_hand': Decimal('118470'),
    'companies_house_registered_number': '09355500',
    'company_dormant': None,
    'company_id': '09355500',
    'cost_sales': None,
    'creditors_due_after_one_year': None,
    'creditors_due_within_one_year': None,
    'current_assets': Decimal('160520'),
    'date': date.fromisoformat('2022-12-31'),
    'debtors': None,
    'depreciation_other_amounts_written_off_tangible_intangible_fixed_assets': None,
    'entity_current_legal_name': 'SUGANTHI & VELAVAN LTD',
    'file_type': 'html',
    'gross_profit_loss': None,
    'net_assets_liabilities_including_pension_asset_liability': Decimal('285564'),
    'net_current_assets_liabilities': Decimal('125565'),
    'operating_profit_loss': None,
    'other_operating_charges_format2': None,
    'other_operating_income': None,
    'period_end': date.fromisoformat('2021-12-31'),
    'period_start': date.fromisoformat('2021-12-31'),
    'profit_loss_account_reserve': None,
    'profit_loss_for_period': None,
    'profit_loss_on_ordinary_activities_before_tax': None,
    'raw_materials_consumables': None,
    'run_code': 'Prod223_3384',
    'shareholder_funds': Decimal('150'),
    'staff_costs': None,
    'tangible_fixed_assets': Decimal('159999'),
    'tax_on_profit_or_loss_on_ordinary_activities': None,
    'taxonomy': '',
    'total_assets_less_current_liabilities': None,
    'turnover_gross_operating_revenue': None,
}, {
    'administrative_expenses': None,
    'average_number_employees_during_period': Decimal(1),
    'balance_sheet_date': date.fromisoformat('2022-08-31'),
    'called_up_share_capital': None,
    'cash_bank_in_hand': None,
    'companies_house_registered_number': '14033910',
    'company_dormant': False,
    'company_id': '14033910',
    'cost_sales': None,
    'creditors_due_after_one_year': None,
    'creditors_due_within_one_year': None,
    'current_assets': Decimal(7558),
    'date': date.fromisoformat('2022-08-31'),
    'debtors': None,
    'depreciation_other_amounts_written_off_tangible_intangible_fixed_assets': None,
    'entity_current_legal_name': 'Graham Chisnell Ltd',
    'file_type': 'html',
    'gross_profit_loss': None,
    'net_assets_liabilities_including_pension_asset_liability': Decimal(-577),
    'net_current_assets_liabilities': Decimal(140),
    'operating_profit_loss': None,
    'other_operating_charges_format2': None,
    'other_operating_income': None,
    'period_end': date.fromisoformat('2022-08-31'),
    'period_start': date.fromisoformat('2022-08-31'),
    'profit_loss_account_reserve': None,
    'profit_loss_for_period': None,
    'profit_loss_on_ordinary_activities_before_tax': None,
    'raw_materials_consumables': None,
    'run_code': 'Prod223_3384',
    'shareholder_funds': Decimal(-577),
    'staff_costs': None,
    'tangible_fixed_assets': Decimal(883),
    'tax_on_profit_or_loss_on_ordinary_activities': None,
    'taxonomy': '',
    'total_assets_less_current_liabilities': Decimal(1023),
    'turnover_gross_operating_revenue': None,
}, {
    'administrative_expenses': None,
    'average_number_employees_during_period': Decimal(3),
    'balance_sheet_date': date.fromisoformat('2022-12-31'),
    'called_up_share_capital': None,
    'cash_bank_in_hand': None,
    'companies_house_registered_number': '14068295',
    'company_dormant': True,
    'company_id': '14068295',
    'cost_sales': None,
    'creditors_due_after_one_year': None,
    'creditors_due_within_one_year': None,
    'current_assets': Decimal(100),
    'date': date.fromisoformat('2022-12-31'),
    'debtors': None,
    'depreciation_other_amounts_written_off_tangible_intangible_fixed_assets': None,
    'entity_current_legal_name': 'Allied London Developments Four Limited',
    'file_type': 'html',
    'gross_profit_loss': None,
    'net_assets_liabilities_including_pension_asset_liability': Decimal(100),
    'net_current_assets_liabilities': Decimal(100),
    'operating_profit_loss': None,
    'other_operating_charges_format2': None,
    'other_operating_income': None,
    'period_end': date.fromisoformat('2022-12-31'),
    'period_start': date.fromisoformat('2022-12-31'),
    'profit_loss_account_reserve': None,
    'profit_loss_for_period': None,
    'profit_loss_on_ordinary_activities_before_tax': None,
    'raw_materials_consumables': None,
    'run_code': 'Prod223_3384',
    'shareholder_funds': Decimal(100),
    'staff_costs': None,
    'tangible_fixed_assets': None,
    'tax_on_profit_or_loss_on_ordinary_activities': None,
    'taxonomy': '',
    'total_assets_less_current_liabilities': Decimal(100),
    'turnover_gross_operating_revenue': None,
}, {
    'administrative_expenses': None,
    'average_number_employees_during_period': Decimal(1),
    'balance_sheet_date': date.fromisoformat('2022-08-31'),
    'called_up_share_capital': None,
    'cash_bank_in_hand': None,
    'companies_house_registered_number': 'NI681295',
    'company_dormant': False,
    'company_id': 'NI681295',
    'cost_sales': None,
    'creditors_due_after_one_year': None,
    'creditors_due_within_one_year': None,
    'current_assets': Decimal(10346),
    'date': date.fromisoformat('2022-08-31'),
    'debtors': None,
    'depreciation_other_amounts_written_off_tangible_intangible_fixed_assets': None,
    'entity_current_legal_name': 'DAVIDSON ONLINE TRAINING (DOT) LIMITED',
    'file_type': 'html',
    'gross_profit_loss': None,
    'net_assets_liabilities_including_pension_asset_liability': Decimal(3437),
    'net_current_assets_liabilities': Decimal(3887),
    'operating_profit_loss': None,
    'other_operating_charges_format2': None,
    'other_operating_income': None,
    'period_end': date.fromisoformat('2022-08-31'),
    'period_start': date.fromisoformat('2022-08-31'),
    'profit_loss_account_reserve': None,
    'profit_loss_for_period': None,
    'profit_loss_on_ordinary_activities_before_tax': None,
    'raw_materials_consumables': None,
    'run_code': 'Prod223_3384',
    'shareholder_funds': Decimal(3437),
    'staff_costs': None,
    'tangible_fixed_assets': None,
    'tax_on_profit_or_loss_on_ordinary_activities': None,
    'taxonomy': '',
    'total_assets_less_current_liabilities': Decimal(3887),
    'turnover_gross_operating_revenue': None,
}, {
    'administrative_expenses': None,
    'average_number_employees_during_period': Decimal(2),
    'balance_sheet_date': date.fromisoformat('2022-09-30'),
    'called_up_share_capital': Decimal(2),
    'cash_bank_in_hand': Decimal(1624),
    'companies_house_registered_number': 'NI682066',
    'company_dormant': False,
    'company_id': 'NI682066',
    'cost_sales': None,
    'creditors_due_after_one_year': None,
    'creditors_due_within_one_year': None,
    'current_assets': Decimal(21257),
    'date': date.fromisoformat('2022-09-30'),
    'debtors': Decimal(19633),
    'depreciation_other_amounts_written_off_tangible_intangible_fixed_assets': None,
    'entity_current_legal_name': 'Castlehill Pension Trustees Limited',
    'file_type': 'html',
    'gross_profit_loss': None,
    'net_assets_liabilities_including_pension_asset_liability': Decimal(8382),
    'net_current_assets_liabilities': Decimal(6982),
    'operating_profit_loss': None,
    'other_operating_charges_format2': None,
    'other_operating_income': None,
    'period_end': date.fromisoformat('2022-09-30'),
    'period_start': date.fromisoformat('2022-09-30'),
    'profit_loss_account_reserve': Decimal(8380),
    'profit_loss_for_period': None,
    'profit_loss_on_ordinary_activities_before_tax': None,
    'raw_materials_consumables': None,
    'run_code': 'Prod223_3384',
    'shareholder_funds': Decimal(2),
    'staff_costs': None,
    'tangible_fixed_assets': Decimal(1400),
    'tax_on_profit_or_loss_on_ordinary_activities': None,
    'taxonomy': '',
    'total_assets_less_current_liabilities': Decimal(8382),
    'turnover_gross_operating_revenue': None,
}, {
    'administrative_expenses': None,
    'average_number_employees_during_period': Decimal(2),
    'balance_sheet_date': date.fromisoformat('2022-09-30'),
    'called_up_share_capital': None,
    'cash_bank_in_hand': None,
    'companies_house_registered_number': 'NI682066',
    'company_dormant': False,
    'company_id': 'NI682066',
    'cost_sales': None,
    'creditors_due_after_one_year': None,
    'creditors_due_within_one_year': None,
    'current_assets': None,
    'date': date.fromisoformat('2022-09-30'),
    'debtors': None,
    'depreciation_other_amounts_written_off_tangible_intangible_fixed_assets': None,
    'entity_current_legal_name': 'Castlehill Pension Trustees Limited',
    'file_type': 'html',
    'gross_profit_loss': None,
    'net_assets_liabilities_including_pension_asset_liability': None,
    'net_current_assets_liabilities': None,
    'operating_profit_loss': None,
    'other_operating_charges_format2': None,
    'other_operating_income': None,
    'period_end': date.fromisoformat('2021-09-01'),
    'period_start': date.fromisoformat('2021-09-01'),
    'profit_loss_account_reserve': None,
    'profit_loss_for_period': None,
    'profit_loss_on_ordinary_activities_before_tax': None,
    'raw_materials_consumables': None,
    'run_code': 'Prod223_3384',
    'shareholder_funds': None,
    'staff_costs': None,
    'tangible_fixed_assets': Decimal(1750),
    'tax_on_profit_or_loss_on_ordinary_activities': None,
    'taxonomy': '',
    'total_assets_less_current_liabilities': None,
    'turnover_gross_operating_revenue': None,
}, {
    'administrative_expenses': None,
    'average_number_employees_during_period': Decimal(0),
    'balance_sheet_date': date.fromisoformat('2022-05-31'),
    'called_up_share_capital': None,
    'cash_bank_in_hand': None,
    'companies_house_registered_number': 'OC437536',
    'company_dormant': True,
    'company_id': 'OC437536',
    'cost_sales': None,
    'creditors_due_after_one_year': None,
    'creditors_due_within_one_year': None,
    'current_assets': None,
    'date': date.fromisoformat('2022-05-31'),
    'debtors': None,
    'depreciation_other_amounts_written_off_tangible_intangible_fixed_assets': None,
    'entity_current_legal_name': 'HARLING FARM LLP',
    'file_type': 'html',
    'gross_profit_loss': None,
    'net_assets_liabilities_including_pension_asset_liability': None,
    'net_current_assets_liabilities': None,
    'operating_profit_loss': None,
    'other_operating_charges_format2': None,
    'other_operating_income': None,
    'period_end': None,
    'period_start': None,
    'profit_loss_account_reserve': None,
    'profit_loss_for_period': None,
    'profit_loss_on_ordinary_activities_before_tax': None,
    'raw_materials_consumables': None,
    'run_code': 'Prod223_3384',
    'shareholder_funds': None,
    'staff_costs': None,
    'tangible_fixed_assets': None,
    'tax_on_profit_or_loss_on_ordinary_activities': None,
    'taxonomy': '',
    'total_assets_less_current_liabilities': None,
    'turnover_gross_operating_revenue': None,
}, {
    'administrative_expenses': None,
    'average_number_employees_during_period': Decimal(2),
    'balance_sheet_date': date.fromisoformat('2022-07-31'),
    'called_up_share_capital': None,
    'cash_bank_in_hand': Decimal(3057),
    'companies_house_registered_number': 'OC438238',
    'company_dormant': False,
    'company_id': 'OC438238',
    'cost_sales': None,
    'creditors_due_after_one_year': None,
    'creditors_due_within_one_year': None,
    'current_assets': Decimal(3507),
    'date': date.fromisoformat('2022-07-31'),
    'debtors': Decimal(450),
    'depreciation_other_amounts_written_off_tangible_intangible_fixed_assets': None,
    'entity_current_legal_name': 'WESTERGAARD-WAKE LLP',
    'file_type': 'html',
    'gross_profit_loss': None,
    'net_assets_liabilities_including_pension_asset_liability': Decimal(155318),
    'net_current_assets_liabilities': Decimal(3507),
    'operating_profit_loss': None,
    'other_operating_charges_format2': None,
    'other_operating_income': None,
    'period_end': date.fromisoformat('2022-07-31'),
    'period_start': date.fromisoformat('2022-07-31'),
    'profit_loss_account_reserve': None,
    'profit_loss_for_period': None,
    'profit_loss_on_ordinary_activities_before_tax': None,
    'raw_materials_consumables': None,
    'run_code': 'Prod223_3384',
    'shareholder_funds': None,
    'staff_costs': None,
    'tangible_fixed_assets': Decimal(385000),
    'tax_on_profit_or_loss_on_ordinary_activities': None,
    'taxonomy': '',
    'total_assets_less_current_liabilities': Decimal(388507),
    'turnover_gross_operating_revenue': None,
}, {
    'administrative_expenses': None,
    'average_number_employees_during_period': Decimal(2),
    'balance_sheet_date': date.fromisoformat('2022-07-31'),
    'called_up_share_capital': None,
    'cash_bank_in_hand': None,
    'companies_house_registered_number': 'OC438238',
    'company_dormant': False,
    'company_id': 'OC438238',
    'cost_sales': None,
    'creditors_due_after_one_year': None,
    'creditors_due_within_one_year': None,
    'current_assets': None,
    'date': date.fromisoformat('2022-07-31'),
    'debtors': None,
    'depreciation_other_amounts_written_off_tangible_intangible_fixed_assets': None,
    'entity_current_legal_name': 'WESTERGAARD-WAKE LLP',
    'file_type': 'html',
    'gross_profit_loss': None,
    'net_assets_liabilities_including_pension_asset_liability': None,
    'net_current_assets_liabilities': None,
    'operating_profit_loss': None,
    'other_operating_charges_format2': None,
    'other_operating_income': None,
    'period_end': date.fromisoformat('2021-07-06'),
    'period_start': date.fromisoformat('2021-07-06'),
    'profit_loss_account_reserve': None,
    'profit_loss_for_period': None,
    'profit_loss_on_ordinary_activities_before_tax': None,
    'raw_materials_consumables': None,
    'run_code': 'Prod223_3384',
    'shareholder_funds': None,
    'staff_costs': None,
    'tangible_fixed_assets': None,
    'tax_on_profit_or_loss_on_ordinary_activities': None,
    'taxonomy': '',
    'total_assets_less_current_liabilities': None,
    'turnover_gross_operating_revenue': None,
}, {
    'administrative_expenses': None,
    'average_number_employees_during_period': Decimal(4),
    'balance_sheet_date': date.fromisoformat('2023-01-31'),
    'called_up_share_capital': None,
    'cash_bank_in_hand': Decimal(6400),
    'companies_house_registered_number': 'SC720321',
    'company_dormant': False,
    'company_id': 'SC720321',
    'cost_sales': None,
    'creditors_due_after_one_year': None,
    'creditors_due_within_one_year': None,
    'current_assets': Decimal(19321),
    'date': date.fromisoformat('2023-01-31'),
    'debtors': Decimal(12921),
    'depreciation_other_amounts_written_off_tangible_intangible_fixed_assets': None,
    'entity_current_legal_name': 'S&C Electrical and Plumbing Ltd',
    'file_type': 'html',
    'gross_profit_loss': None,
    'net_assets_liabilities_including_pension_asset_liability': Decimal(-22737),
    'net_current_assets_liabilities': Decimal(-22780),
    'operating_profit_loss': None,
    'other_operating_charges_format2': None,
    'other_operating_income': None,
    'period_end': date.fromisoformat('2023-01-31'),
    'period_start': date.fromisoformat('2023-01-31'),
    'profit_loss_account_reserve': Decimal(-22737),
    'profit_loss_for_period': None,
    'profit_loss_on_ordinary_activities_before_tax': None,
    'raw_materials_consumables': None,
    'run_code': 'Prod223_3384',
    'shareholder_funds': Decimal(-22737),
    'staff_costs': None,
    'tangible_fixed_assets': Decimal(24016),
    'tax_on_profit_or_loss_on_ordinary_activities': None,
    'taxonomy': '',
    'total_assets_less_current_liabilities': Decimal(1236),
    'turnover_gross_operating_revenue': None,
}, {
    'administrative_expenses': None,
    'average_number_employees_during_period': Decimal(4),
    'balance_sheet_date': date.fromisoformat('2023-01-31'),
    'called_up_share_capital': None,
    'cash_bank_in_hand': None,
    'companies_house_registered_number': 'SC720321',
    'company_dormant': False,
    'company_id': 'SC720321',
    'cost_sales': None,
    'creditors_due_after_one_year': None,
    'creditors_due_within_one_year': None,
    'current_assets': None,
    'date': date.fromisoformat('2023-01-31'),
    'debtors': None,
    'depreciation_other_amounts_written_off_tangible_intangible_fixed_assets': None,
    'entity_current_legal_name': 'S&C Electrical and Plumbing Ltd',
    'file_type': 'html',
    'gross_profit_loss': None,
    'net_assets_liabilities_including_pension_asset_liability': None,
    'net_current_assets_liabilities': None,
    'operating_profit_loss': None,
    'other_operating_charges_format2': None,
    'other_operating_income': None,
    'period_end': date.fromisoformat('2022-01-18'),
    'period_start': date.fromisoformat('2022-01-18'),
    'profit_loss_account_reserve': None,
    'profit_loss_for_period': None,
    'profit_loss_on_ordinary_activities_before_tax': None,
    'raw_materials_consumables': None,
    'run_code': 'Prod223_3384',
    'shareholder_funds': None,
    'staff_costs': None,
    'tangible_fixed_assets': None,
    'tax_on_profit_or_loss_on_ordinary_activities': None,
    'taxonomy': '',
    'total_assets_less_current_liabilities': None,
    'turnover_gross_operating_revenue': None,
}, {
    'administrative_expenses': None,
    'average_number_employees_during_period': Decimal(0),
    'balance_sheet_date': date.fromisoformat('2023-02-28'),
    'called_up_share_capital': None,
    'cash_bank_in_hand': None,
    'companies_house_registered_number': 'SC722766',
    'company_dormant': False,
    'company_id': 'SC722766',
    'cost_sales': None,
    'creditors_due_after_one_year': None,
    'creditors_due_within_one_year': None,
    'current_assets': Decimal(1),
    'date': date.fromisoformat('2023-02-28'),
    'debtors': None,
    'depreciation_other_amounts_written_off_tangible_intangible_fixed_assets': None,
    'entity_current_legal_name': 'G49SY LIMITED',
    'file_type': 'html',
    'gross_profit_loss': None,
    'net_assets_liabilities_including_pension_asset_liability': Decimal(1),
    'net_current_assets_liabilities': Decimal(1),
    'operating_profit_loss': None,
    'other_operating_charges_format2': None,
    'other_operating_income': None,
    'period_end': date.fromisoformat('2023-02-28'),
    'period_start': date.fromisoformat('2023-02-28'),
    'profit_loss_account_reserve': None,
    'profit_loss_for_period': None,
    'profit_loss_on_ordinary_activities_before_tax': None,
    'raw_materials_consumables': None,
    'run_code': 'Prod223_3384',
    'shareholder_funds': Decimal(1),
    'staff_costs': None,
    'tangible_fixed_assets': None,
    'tax_on_profit_or_loss_on_ordinary_activities': None,
    'taxonomy': '',
    'total_assets_less_current_liabilities': Decimal(1),
    'turnover_gross_operating_revenue': None,
})


@pytest.fixture
def mock_companies_house_daily_zip(httpx_mock):
    with open('fixtures/Accounts_Bulk_Data-2023-03-02.zip', 'rb') as f:
        httpx_mock.add_response(
            url='https://download.companieshouse.gov.uk/Accounts_Bulk_Data-2023-03-02.zip',
            content=f.read(),
        )

@pytest.fixture
def mock_companies_house_daily_zip_404(httpx_mock):
    with open('fixtures/Accounts_Bulk_Data-2023-03-02.zip', 'rb') as f:
        httpx_mock.add_response(
            url='https://download.companieshouse.gov.uk/does-not-exist.zip',
            status_code=404,
        )

@pytest.fixture
def mock_companies_house_daily_html(httpx_mock):
    httpx_mock.add_response(
        url='https://download.companieshouse.gov.uk/en_accountsdata.html',
        content=b'''
            <a href="Accounts_Bulk_Data-2023-03-02.zip">Link</a>
            <a href="does-not-exist.zip">Link</a>
        ''',
    )


def test_stream_read_xbrl_zip(mock_companies_house_daily_zip):
    with \
            httpx.stream('GET', 'https://download.companieshouse.gov.uk/Accounts_Bulk_Data-2023-03-02.zip') as r, \
            stream_read_xbrl_zip(r.iter_bytes(chunk_size=65536)) as (columns, rows):
        assert tuple((dict(zip(columns, row)) for row in rows)) == expected_data


def test_stream_read_xbrl_daily_all(
    mock_companies_house_daily_html,
    mock_companies_house_daily_zip,
    mock_companies_house_daily_zip_404,
):
    with stream_read_xbrl_daily_all() as (columns, rows):
        assert tuple((dict(zip(columns, row)) for row in rows)) == expected_data


def test_stream_read_xbrl_sync():
    with stream_read_xbrl_sync() as (columns, final_date_and_rows):
        assert columns == ('a', 'b')
        assert tuple((
            (final_date, tuple(rows)) for (final_date, rows) in final_date_and_rows
        )) == (
            (date(2021, 5, 2), (('1', '2'), ('3', '4'))),
            (date(2022, 2, 8), (('5', '6'), ('7', '8'))),
        )

    with stream_read_xbrl_sync(date(2021, 5, 1)) as (columns, final_date_and_rows):
        assert tuple((
            (final_date, tuple(rows)) for (final_date, rows) in final_date_and_rows
        )) == (
            (date(2021, 5, 2), (('1', '2'), ('3', '4'))),
            (date(2022, 2, 8), (('5', '6'), ('7', '8'))),
        )

    with stream_read_xbrl_sync(date(2021, 5, 2)) as (columns, final_date_and_rows):
        assert tuple((
            (final_date, tuple(rows)) for (final_date, rows) in final_date_and_rows
        )) == (
            (date(2022, 2, 8), (('5', '6'), ('7', '8'))),
        )

    with stream_read_xbrl_sync(date(2021, 5, 3)) as (columns, final_date_and_rows):
        assert tuple((
            (final_date, tuple(rows)) for (final_date, rows) in final_date_and_rows
        )) == (
            (date(2022, 2, 8), (('5', '6'), ('7', '8'))),
        )

    with stream_read_xbrl_sync(date(2022, 1, 8)) as (columns, final_date_and_rows):
        assert tuple((
            (final_date, tuple(rows)) for (final_date, rows) in final_date_and_rows
        )) == (
            (date(2022, 2, 8), (('5', '6'), ('7', '8'))),
        )

    with stream_read_xbrl_sync(date(2022, 2, 8)) as (columns, final_date_and_rows):
        assert tuple((
            (final_date, tuple(rows)) for (final_date, rows) in final_date_and_rows
        )) == ()


@mock_s3
def test_stream_read_xbrl_sync_s3_csv_fetches_all_files_if_bucket_empty():
    region_name = 'eu-west-2'
    bucket_name = 'my-bucket'
    key_prefix = 'my-prefix/'  # Would usually end in a forward slash

    s3_client = boto3.client('s3', region_name=region_name)
    s3_client.create_bucket(Bucket=bucket_name, CreateBucketConfiguration={
        'LocationConstraint': region_name,
    })

    stream_read_xbrl_sync_s3_csv(s3_client, bucket_name, key_prefix)

    assert s3_client.get_object(Bucket=bucket_name, Key=f'{key_prefix}2021-05-02.csv')['Body'].read() == b'"a","b"\r\n"1","2"\r\n"3","4"\r\n'
    assert s3_client.get_object(Bucket=bucket_name, Key=f'{key_prefix}2022-02-08.csv')['Body'].read() == b'"a","b"\r\n"5","6"\r\n"7","8"\r\n'


@mock_s3
def test_stream_read_xbrl_sync_s3_csv_leaves_existing_files_alone():
    region_name = 'eu-west-2'
    bucket_name = 'my-bucket'
    key_prefix = 'my-prefix/'  # Would usually end in a forward slash

    s3_client = boto3.client('s3', region_name=region_name)
    s3_client.create_bucket(Bucket=bucket_name, CreateBucketConfiguration={
        'LocationConstraint': region_name,
    })

    s3_client.put_object(Bucket=bucket_name, Key=f'{key_prefix}2021-05-02.csv', Body='should-not-be-overwritten')

    stream_read_xbrl_sync_s3_csv(s3_client, bucket_name, key_prefix)

    assert s3_client.get_object(Bucket=bucket_name, Key=f'{key_prefix}2021-05-02.csv')['Body'].read() == b'should-not-be-overwritten'
    assert s3_client.get_object(Bucket=bucket_name, Key=f'{key_prefix}2022-02-08.csv')['Body'].read() == b'"a","b"\r\n"5","6"\r\n"7","8"\r\n'

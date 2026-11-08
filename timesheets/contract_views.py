"""Contract-Cost Center/Account management, for the Superintendent and the System Admin.

Card, then list, then detail:
  - Overview: one card per series, plus "Not in a series", "Cost Centers/Accounts"
    and "Deactivated", each showing what needs attention. A search finds a
    contract from anywhere.
  - Series page: one compact row per contract, with quick filters.
  - Contract page: everything about one contract (details, levels, series,
    cost centers/accounts, deactivate).
  - Cost Centers/Accounts page: the full list, with edit and deactivate.

Every page posts to itself; one handler does the work so the rules (no
duplicate codes, no deleting contracts or cost centers/accounts, a series
can only be deleted when empty) are the same everywhere, and every change
is written to the Audit Log.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Count, Exists, Max, OuterRef, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .audit import log_action
from .models import Account, Contract, ContractAccount, ContractSeries, MinerLevel
from .views import _valid_pk

MANAGERS = (1, 2)  # System Admin, Superintendent


def _can_manage(user):
    return user.access_level in MANAGERS


def _levels():
    # "Staff" is the Shifter level, never a contract level.
    return MinerLevel.objects.exclude(levelcode='Staff')


def _annotated(contracts):
    """Adds has_account / has_level so pages can flag what needs attention."""
    return contracts.annotate(
        has_account=Exists(ContractAccount.objects.filter(contractid=OuterRef('pk'))),
        has_level=Exists(Contract.levels.through.objects.filter(contract_id=OuterRef('pk'))),
    )


def _save_row(request, obj, label):
    """Validate (including the duplicate rules on the model) and save. True when saved."""
    try:
        obj.full_clean()
    except ValidationError as exc:
        for errors in exc.message_dict.values():
            for error in errors:
                messages.error(request, f'{label}: {error}')
        return False
    obj.save()
    return True


def _handle_post(request):
    """Every create/edit/link action on these pages. Returns the new contract
    when one was created, so the caller can open it."""
    post = request.POST
    action = post.get('action')
    user = request.user

    if action == 'create_series':
        series = ContractSeries(seriesname=post.get('seriesname', ''),
                                sortorder=(ContractSeries.objects.aggregate(m=Max('sortorder'))['m'] or 0) + 1)
        if _save_row(request, series, 'New series'):
            log_action(user, 'Created', 'ContractSeries', series.seriesid, None, {'seriesname': series.seriesname})
            messages.success(request, f'Series "{series.seriesname}" created.')

    elif action == 'rename_series':
        series = _valid_pk(ContractSeries, post.get('seriesid'))
        if series:
            old = series.seriesname
            series.seriesname = post.get('seriesname', '')
            if _save_row(request, series, 'Series'):
                log_action(user, 'Edited', 'ContractSeries', series.seriesid, {'seriesname': old}, {'seriesname': series.seriesname})
                messages.success(request, f'Series renamed to "{series.seriesname}".')

    elif action == 'delete_series':
        series = _valid_pk(ContractSeries, post.get('seriesid'))
        if series and series.contracts.exists():
            messages.error(request, f'"{series.seriesname}" still has contracts. Remove them from the series first, or rename it instead.')
        elif series:
            log_action(user, 'Deleted', 'ContractSeries', series.seriesid, {'seriesname': series.seriesname}, None)
            messages.success(request, f'Series "{series.seriesname}" deleted.')
            series.delete()

    elif action in ('create_contract', 'edit_contract'):
        creating = action == 'create_contract'
        contract = Contract() if creating else _valid_pk(Contract, post.get('contractid'))
        if contract is not None:
            old = None if creating else {'contractcode': contract.contractcode, 'contracttitle': contract.contracttitle,
                                         'contractdescription': contract.contractdescription}
            contract.contractcode = post.get('contractcode', '')
            contract.contracttitle = post.get('contracttitle', '')
            contract.contractdescription = post.get('contractdescription', '').strip() or None
            if _save_row(request, contract, 'Contract'):
                if creating:
                    contract.series.set(ContractSeries.objects.filter(pk__in=[i for i in post.getlist('series_ids') if i.isdigit()]))
                    contract.levels.set(_levels().filter(pk__in=[i for i in post.getlist('level_ids') if i.isdigit()]))
                    for account in Account.objects.filter(isactive=1, pk__in=[i for i in post.getlist('account_ids') if i.isdigit()]):
                        ContractAccount.objects.get_or_create(contractid=contract, accountid=account)
                new = {'contractcode': contract.contractcode, 'contracttitle': contract.contracttitle,
                       'contractdescription': contract.contractdescription}
                log_action(user, 'Created' if creating else 'Edited', 'Contract', contract.contractid, old, new)
                missing = []
                if creating and not contract.levels.exists():
                    missing.append('a level so it can be offered to Miners')
                if creating and not contract.contractaccount_set.exists():
                    missing.append('a cost center/account')
                note = f' Still needs {" and ".join(missing)}.' if missing else ''
                messages.success(request, f'Contract {contract.contractcode} {"created" if creating else "updated"}.{note}')
                return contract if creating else None

    elif action in ('create_account', 'edit_account'):
        creating = action == 'create_account'
        account = Account() if creating else _valid_pk(Account, post.get('accountid'))
        if account is not None:
            old = None if creating else {'accountcode': account.accountcode, 'accounttitle': account.accounttitle,
                                         'accountdescription': account.accountdescription}
            account.accountcode = post.get('accountcode', '')
            account.accounttitle = post.get('accounttitle', '')
            account.accountdescription = post.get('accountdescription', '').strip() or None
            if _save_row(request, account, 'Cost Center/Account'):
                new = {'accountcode': account.accountcode, 'accounttitle': account.accounttitle,
                       'accountdescription': account.accountdescription}
                log_action(user, 'Created' if creating else 'Edited', 'Account', account.accountid, old, new)
                messages.success(request, f'Cost Center/Account {account.accountcode} {"created" if creating else "updated"}.')

    elif action in ('set_contract_active', 'set_account_active'):
        model, table = (Contract, 'Contract') if action == 'set_contract_active' else (Account, 'Account')
        row = _valid_pk(model, post.get('rowid'))
        active = 1 if post.get('active') == '1' else 0
        if row and row.isactive != active:
            old = row.isactive
            row.isactive = active
            row.save(update_fields=['isactive'])
            log_action(user, 'Reactivated' if active else 'Deactivated', table, row.pk, {'isactive': old}, {'isactive': active})
            messages.success(request, f'{row} {"reactivated" if active else "deactivated"}.')

    elif action in ('link_account', 'unlink_account'):
        contract = _valid_pk(Contract, post.get('contractid'))
        account = _valid_pk(Account, post.get('accountid'))
        if contract and account:
            if action == 'link_account':
                ContractAccount.objects.get_or_create(contractid=contract, accountid=account)
            else:
                ContractAccount.objects.filter(contractid=contract, accountid=account).delete()
            log_action(user, 'Linked' if action == 'link_account' else 'Unlinked', 'ContractAccount', contract.contractid,
                       None, {'contract': contract.contractcode, 'account': account.accountcode})

    elif action in ('add_series', 'remove_series'):
        contracts = [c for c in (_valid_pk(Contract, i) for i in post.getlist('contractid')) if c]
        series = _valid_pk(ContractSeries, post.get('target_series_id'))
        if contracts and series:
            for contract in contracts:
                (contract.series.add if action == 'add_series' else contract.series.remove)(series)
            verb = 'added to' if action == 'add_series' else 'removed from'
            messages.success(request, f'{", ".join(c.contractcode for c in contracts)} {verb} {series.seriesname}.')

    elif action in ('add_level', 'remove_level'):
        contract = _valid_pk(Contract, post.get('contractid'))
        level = _valid_pk(MinerLevel, post.get('levelid'))
        if contract and level and level.levelcode != 'Staff':
            (contract.levels.add if action == 'add_level' else contract.levels.remove)(level)

    elif action == 'bulk_assign_account':
        # One or more cost centers/accounts, each linked to every active
        # contract in the series. Links that already exist are left alone.
        series = _valid_pk(ContractSeries, post.get('seriesid'))
        ids = [i for i in post.getlist('accountid') if i.isdigit()]
        accounts = list(Account.objects.filter(isactive=1, pk__in=ids).order_by('accountcode'))
        if not (series and accounts):
            messages.error(request, 'Pick at least one cost center/account to link.')
            return None
        contracts = list(series.contracts.filter(isactive=1))
        added = 0
        for account in accounts:
            for contract in contracts:
                _, created = ContractAccount.objects.get_or_create(contractid=contract, accountid=account)
                if created:
                    added += 1
                    log_action(user, 'Linked', 'ContractAccount', contract.contractid,
                               None, {'contract': contract.contractcode, 'account': account.accountcode})
        codes = ', '.join(a.accountcode for a in accounts)
        messages.success(request, f'{codes} linked to all {len(contracts)} active contract{"s" if len(contracts) != 1 else ""} '
                                  f'in {series.seriesname} ({added} new link{"s" if added != 1 else ""}).')
    return None


def _in_app(request, url):
    return bool(url) and url.startswith('/') and url_has_allowed_host_and_scheme(
        url, allowed_hosts={request.get_host()}, require_https=request.is_secure())


def _with_open(url, contract_id):
    """The same page with ?open=<id>, which reopens that contract's modal."""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k != 'open'] + [('open', str(contract_id))]
    return urlunsplit(('', '', parts.path, urlencode(query), ''))


def _post_and_return(request):
    """Run the action, then come back to the page it came from. A new contract
    doesn't open its modal: everything can be set on the New Contract form."""
    _handle_post(request)
    nxt = request.POST.get('next', '')
    return redirect(nxt if _in_app(request, nxt) else request.get_full_path())


def _new_forms_context(preselect_series=None):
    return {
        'all_levels': _levels(),
        'all_series': ContractSeries.objects.all(),
        'all_accounts': Account.objects.filter(isactive=1).order_by('accountcode'),
        'preselect_series': preselect_series,
    }


@login_required(login_url='login')
def contract_account_management(request):
    """Overview: a card per series plus the other groups, and a contract search."""
    if not _can_manage(request.user):
        return redirect('profile')
    if request.method == 'POST':
        return _post_and_return(request)

    active = _annotated(Contract.objects.filter(isactive=1))
    cards = []
    for series in ContractSeries.objects.all():
        in_series = active.filter(series=series)
        cards.append({
            'title': series.seriesname,
            'url': reverse('contract_series', args=[series.seriesid]),
            'count': in_series.count(),
            'needs_account': in_series.filter(has_account=False).count(),
            'no_level': in_series.filter(has_level=False).count(),
        })
    loose = active.filter(series__isnull=True)

    q = request.GET.get('q', '').strip()
    results = None
    if q:
        results = _annotated(Contract.objects.filter(Q(contractcode__icontains=q) | Q(contracttitle__icontains=q))
                             ).prefetch_related('levels', 'contractaccount_set__accountid').order_by('-isactive', 'contractcode')

    return render(request, 'timesheets/contract_account_management.html', {
        **_new_forms_context(),
        'cards': cards,
        'loose': {'count': loose.count(), 'needs_account': loose.filter(has_account=False).count(),
                  'no_level': loose.filter(has_level=False).count()},
        'accounts': {'active': Account.objects.filter(isactive=1).count(), 'inactive': Account.objects.filter(isactive=0).count()},
        'inactive_count': Contract.objects.filter(isactive=0).count(),
        'q': q,
        'results': results,
    })


@login_required(login_url='login')
def contract_series(request, key):
    """One group of contracts as compact rows. key is a series id, 'unassigned'
    (not in a series) or 'inactive' (deactivated)."""
    if not _can_manage(request.user):
        return redirect('profile')
    if request.method == 'POST':
        return _post_and_return(request)

    series = None
    if key == 'unassigned':
        title, contracts = 'Not in a series', Contract.objects.filter(isactive=1, series__isnull=True)
    elif key == 'inactive':
        title, contracts = 'Deactivated contracts', Contract.objects.filter(isactive=0)
    elif key.isdigit():
        series = get_object_or_404(ContractSeries, pk=int(key))
        title, contracts = series.seriesname, Contract.objects.filter(isactive=1, series=series)
    else:
        return redirect('contract_account_management')

    contracts = _annotated(contracts).prefetch_related('levels', 'contractaccount_set__accountid').order_by('contractcode')
    totals = {'all': contracts.count(), 'needs_account': contracts.filter(has_account=False).count(),
              'no_level': contracts.filter(has_level=False).count()}
    show = request.GET.get('show', '')
    if show == 'needs_account':
        contracts = contracts.filter(has_account=False)
    elif show == 'no_level':
        contracts = contracts.filter(has_level=False)

    return render(request, 'timesheets/contract_series.html', {
        **_new_forms_context(preselect_series=series),
        'key': key,
        'series': series,
        'title': title,
        'contracts': contracts,
        'totals': totals,
        'show': show,
        # Contracts that could be added to this series (active, not already in it).
        'addable': Contract.objects.filter(isactive=1).exclude(series=series).order_by('contractcode') if series else None,
        'accounts': Account.objects.filter(isactive=1).order_by('accountcode'),
    })


def _safe_back(request):
    """The page to return to: only an address inside this app."""
    back = request.GET.get('back', '')
    return back if _in_app(request, back) else reverse('contract_account_management')


@login_required(login_url='login')
def contract_detail(request, pk):
    """Everything about one contract. With ?partial=1 it returns just the panel,
    for the contract modal on the overview and series pages."""
    if not _can_manage(request.user):
        return redirect('profile')
    contract = get_object_or_404(Contract, pk=pk)
    if request.method == 'POST':
        return _post_and_return(request)
    linked = ContractAccount.objects.filter(contractid=contract).select_related('accountid').order_by('accountid__accountcode')
    linked_ids = [link.accountid_id for link in linked]
    partial = request.GET.get('partial') == '1'
    back_url = _safe_back(request)
    return render(request, 'timesheets/_contract_panel.html' if partial else 'timesheets/contract_detail.html', {
        # Where each form in the panel comes back to: the listing page with this
        # contract's modal reopened, or (on the full page) this page itself.
        'return_url': _with_open(back_url, contract.pk) if partial else request.get_full_path(),
        'contract': contract,
        'levels': contract.levels.all(),
        'other_levels': _levels().exclude(pk__in=contract.levels.all()),
        'series_in': contract.series.all(),
        'series_other': ContractSeries.objects.exclude(pk__in=contract.series.all()),
        'linked': linked,
        'other_accounts': Account.objects.filter(isactive=1).exclude(pk__in=linked_ids).order_by('accountcode'),
        'back_url': back_url,
    })


@login_required(login_url='login')
def contract_accounts(request):
    """The full Cost Centers/Accounts list."""
    if not _can_manage(request.user):
        return redirect('profile')
    if request.method == 'POST':
        return _post_and_return(request)
    q = request.GET.get('q', '').strip()
    accounts = Account.objects.annotate(contract_count=Count('contractaccount')).order_by('-isactive', 'accountcode')
    if q:
        accounts = accounts.filter(Q(accountcode__icontains=q) | Q(accounttitle__icontains=q))
    return render(request, 'timesheets/contract_accounts.html', {'accounts': accounts, 'q': q})

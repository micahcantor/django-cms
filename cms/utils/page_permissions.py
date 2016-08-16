# -*- coding: utf-8 -*-
from functools import wraps

from django.contrib.sites.models import Site
from django.utils.decorators import available_attrs

from cms.api import get_page_draft
from cms.cache.permissions import get_permission_cache, set_permission_cache
from cms.constants import GRANT_ALL_PERMISSIONS
from cms.models import Page, Placeholder
from cms.utils.conf import get_cms_setting
from cms.utils.permissions import (
    cached_func,
    get_model_permission_codename,
    get_page_actions_for_user,
    has_global_permission,
)


PAGE_ADD_CODENAME = get_model_permission_codename(Page, 'add')
PAGE_CHANGE_CODENAME = get_model_permission_codename(Page, 'change')
PAGE_DELETE_CODENAME = get_model_permission_codename(Page, 'delete')
PAGE_PUBLISH_CODENAME = get_model_permission_codename(Page, 'publish')
PAGE_VIEW_CODENAME = get_model_permission_codename(Page, 'view')


# Maps an action to the required Django auth permission codes
_django_permissions_by_action = {
    'add_page': [PAGE_ADD_CODENAME, PAGE_CHANGE_CODENAME],
    'change_page': [PAGE_CHANGE_CODENAME],
    'change_page_advanced_settings': [PAGE_CHANGE_CODENAME],
    'change_page_permissions': [PAGE_CHANGE_CODENAME],
    'delete_page': [PAGE_CHANGE_CODENAME, PAGE_DELETE_CODENAME],
    'delete_page_translation': [PAGE_CHANGE_CODENAME, PAGE_DELETE_CODENAME],
    'move_page': [PAGE_CHANGE_CODENAME],
    'publish_page': [PAGE_CHANGE_CODENAME, PAGE_PUBLISH_CODENAME],
    'recover_page': [PAGE_ADD_CODENAME, PAGE_CHANGE_CODENAME],
}


def _get_draft_placeholders(page):
    if page.publisher_is_draft:
        return page.placeholders.all()
    return Placeholder.objects.filter(page__pk=page.publisher_public_id)


def _get_page_ids_for_action(user, site, action, check_global=True):
    if user.is_superuser or not get_cms_setting('PERMISSION'):
        # got superuser, or permissions aren't enabled?
        # just return grant all mark
        return GRANT_ALL_PERMISSIONS

    # read from cache if possible
    cached = get_permission_cache(user, action)

    if cached is not None:
        return cached

    if check_global and has_global_permission(user, site, action=action):
        return GRANT_ALL_PERMISSIONS

    page_actions = get_page_actions_for_user(user, site)
    page_ids = list(page_actions[action])
    set_permission_cache(user, action, page_ids)
    return page_ids


def permission_pre_checks(action):
    def decorator(func):
        @wraps(func, assigned=available_attrs(func))
        def wrapper(user, *args, **kwargs):
            if not user.is_authenticated():
                return False

            if user.is_superuser:
                return True

            permissions = _django_permissions_by_action[action]

            if not user.has_perms(permissions):
                # Fail fast if the user does not have permissions
                # in Django to perform the action.
                return False

            if not get_cms_setting('PERMISSION'):
                return True
            return func(user, *args, **kwargs)
        return wrapper
    return decorator



@permission_pre_checks(action='add_page')
@cached_func
def user_can_add_page(user, site=None):
    if site is None:
        site = Site.objects.get_current()
    return has_global_permission(user, site, action='add_page')


@permission_pre_checks(action='add_page')
@cached_func
def user_can_add_subpage(user, target, site=None):
    """
    Return true if the current user has permission to add a new page
    under target.
    :param user:
    :param target: a Page object
    :param site: optional Site object (not just PK)
    :return: Boolean
    """
    has_perm = has_generic_permission(
        page=target,
        user=user,
        action='add_page',
        site=site,
    )
    return has_perm


@permission_pre_checks(action='change_page')
@cached_func
def user_can_change_page(user, page):
    has_perm = has_generic_permission(
        page=page,
        user=user,
        action='change_page',
    )
    return has_perm


@permission_pre_checks(action='delete_page')
@cached_func
def user_can_delete_page(user, page):
    has_perm = has_generic_permission(
        page=page,
        user=user,
        action='delete_page',
    )

    if not has_perm:
        return False

    languages = page.get_languages()
    placeholders = (
        _get_draft_placeholders(page)
        .filter(cmsplugin__language__in=languages)
        .distinct()
    )

    for placeholder in placeholders.iterator():
        if not placeholder.has_delete_plugins_permission(user, languages):
            return False
    return True


@permission_pre_checks(action='delete_page_translation')
@cached_func
def user_can_delete_page_translation(user, page, language):
    has_perm = has_generic_permission(
        page=page,
        user=user,
        action='delete_page_translation',
    )

    if not has_perm:
        return False

    placeholders = (
        _get_draft_placeholders(page)
        .filter(cmsplugin__language=language)
        .distinct()
    )

    for placeholder in placeholders.iterator():
        if not placeholder.has_delete_plugins_permission(user, [language]):
            return False
    return True


@permission_pre_checks(action='publish_page')
@cached_func
def user_can_publish_page(user, page):
    has_perm = has_generic_permission(
        page=page,
        user=user,
        action='publish_page',
    )
    return has_perm


@permission_pre_checks(action='change_page_advanced_settings')
@cached_func
def user_can_change_page_advanced_settings(user, page):
    has_perm = has_generic_permission(
        page=page,
        user=user,
        action='change_page_advanced_settings',
    )
    return has_perm


@permission_pre_checks(action='change_page_permissions')
@cached_func
def user_can_change_page_permissions(user, page):
    has_perm = has_generic_permission(
        page=page,
        user=user,
        action='change_page_permissions',
    )
    return has_perm


@permission_pre_checks(action='move_page')
@cached_func
def user_can_move_page(user, page):
    has_perm = has_generic_permission(
        page=page,
        user=user,
        action='move_page',
    )
    return has_perm


@cached_func
def user_can_view_page(user, page):
    if user.is_superuser:
        return True

    public_for = get_cms_setting('PUBLIC_FOR')
    can_see_unrestricted = public_for == 'all' or (public_for == 'staff' and user.is_staff)

    page = get_page_draft(page)

    # inherited and direct view permissions
    is_restricted = page.has_view_restrictions()

    if not is_restricted and can_see_unrestricted:
        # Page has no restrictions and project is configured
        # to allow everyone to see unrestricted pages.
        return True
    elif not user.is_authenticated():
        # Page has restrictions or project is configured
        # to require staff user status to see pages.
        return False

    if user_can_view_all_pages(user, site=page.site):
        return True

    if not is_restricted:
        # Page has no restrictions but user can't see unrestricted pages
        return False

    has_perm = has_generic_permission(
        page=page,
        user=user,
        action='view_page',
        check_global=False,
    )
    return has_perm


@permission_pre_checks(action='change_page')
@cached_func
def user_can_change_all_pages(user, site):
    return has_global_permission(user, site, action='change_page')


@permission_pre_checks(action='recover_page')
@cached_func
def user_can_recover_any_page(user, site):
    return has_global_permission(user, site, action='recover_page')


@cached_func
def user_can_view_all_pages(user, site):
    if user.is_superuser:
        return True

    if not get_cms_setting('PERMISSION'):
        public_for = get_cms_setting('PUBLIC_FOR')
        can_see_unrestricted = public_for == 'all' or (public_for == 'staff' and user.is_staff)
        return can_see_unrestricted

    if not user.is_authenticated():
        return False

    if user.has_perm(PAGE_VIEW_CODENAME):
        # This is for backwards compatibility.
        # The previous system allowed any user with the explicit view_page
        # permission to see all pages.
        return True
    return has_global_permission(user, site, action='view_page')


def get_add_id_list(user, site, check_global=True):
    """
    Give a list of page where the user has add page rights or the string
    "All" if the user has all rights.
    """
    page_ids = _get_page_ids_for_action(
        user=user,
        site=site,
        action='add_page',
        check_global=check_global,
    )
    return page_ids


def get_change_id_list(user, site, check_global=True):
    """
    Give a list of page where the user has edit rights or the string "All" if
    the user has all rights.
    """
    page_ids = _get_page_ids_for_action(
        user=user,
        site=site,
        action='change_page',
        check_global=check_global,
    )
    return page_ids


def get_change_advanced_settings_id_list(user, site, check_global=True):
    """
    Give a list of page where the user can change advanced settings or the
    string "All" if the user has all rights.
    """
    page_ids = _get_page_ids_for_action(
        user=user,
        site=site,
        action='change_page_advanced_settings',
        check_global=check_global,
    )
    return page_ids


def get_change_permissions_id_list(user, site, check_global=True):
    """Give a list of page where the user can change permissions.
    """
    page_ids = _get_page_ids_for_action(
        user=user,
        site=site,
        action='change_page_permissions',
        check_global=check_global,
    )
    return page_ids


def get_delete_id_list(user, site, check_global=True):
    """
    Give a list of page where the user has delete rights or the string "All" if
    the user has all rights.
    """
    page_ids = _get_page_ids_for_action(
        user=user,
        site=site,
        action='delete_page',
        check_global=check_global,
    )
    return page_ids


def get_move_page_id_list(user, site, check_global=True):
    """Give a list of pages which user can move.
    """
    page_ids = _get_page_ids_for_action(
        user=user,
        site=site,
        action='move_page',
        check_global=check_global,
    )
    return page_ids


def get_publish_id_list(user, site, check_global=True):
    """
    Give a list of page where the user has publish rights or the string "All" if
    the user has all rights.
    """
    page_ids = _get_page_ids_for_action(
        user=user,
        site=site,
        action='publish_page',
        check_global=check_global,
    )
    return page_ids


def get_view_id_list(user, site, check_global=True):
    """Give a list of pages which user can view.
    """
    page_ids = _get_page_ids_for_action(
        user=user,
        site=site,
        action='view_page',
        check_global=check_global,
    )
    return page_ids


def has_generic_permission(page, user, action, site=None, check_global=True):
    if not site:
        site = page.site

    if page.publisher_is_draft:
        page_id = page.pk
    else:
        page_id = page.publisher_public_id

    actions_map = {
        'add_page': get_add_id_list,
        'change_page': get_change_id_list,
        'change_page_advanced_settings': get_change_advanced_settings_id_list,
        'change_page_permissions': get_change_permissions_id_list,
        'delete_page': get_delete_id_list,
        'delete_page_translation': get_delete_id_list,
        'move_page': get_move_page_id_list,
        'publish_page': get_publish_id_list,
        'view_page': get_view_id_list,
    }

    func = actions_map[action]
    page_ids = func(user, site, check_global=check_global)
    return page_ids == GRANT_ALL_PERMISSIONS or page_id in page_ids
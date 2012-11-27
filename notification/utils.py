import logging
from django.db import models
from django.contrib.sites.models import Site
from django import template
from django.template import Context
from django.template.loader import render_to_string
from django.core.urlresolvers import reverse, set_script_prefix, get_script_prefix
from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import get_language, activate

from notification.conf import settings

logger = logging.getLogger('notification')


### QUEUE ##############################################################


def can_queue(func, **kwargs):
    """
    Returns a boolean describing if func should be passed through the queueing
    infrastructure based on the ``USE_QUEUE`` setting.

    >>> can_queue(task_func)
    True
    """
    use_queue = kwargs.pop('use_queue', settings.NOTIFICATION_USE_QUEUE)
    if not use_queue:
        return False
    elif use_queue is True:
        return True
    elif '%s.%s' % (func.__module__, func.__name__) in settings.NOTIFICATION_USE_QUEUE:
        return True
    return False


def maybe_delay(func, *args, **kwargs):
    if can_queue(func, **kwargs):
        return func.delay(*args, **kwargs)
    return func(*args, **kwargs)


### LANGUAGE ###########################################################


class context_language(object):
    def __init__(self, user):
        self.user = user

    def __enter__(self):
        self.current_language = get_language()

        # get user language for user from language store defined in
        # NOTIFICATION_LANGUAGE_MODULE setting
        try:
            language = get_notification_language(self.user)
        except LanguageStoreNotAvailable:
            language = None

        # activate the user's language
        if language is not None:
            activate(language)

    def __exit__(self, type, value, traceback):
        # reset environment to original language
        activate(self.current_language)


class AbsoluteUrlContext():
    def __init__(self):
        self.prev_media_url = settings.MEDIA_URL
        self.prev_static_url = settings.STATIC_URL
        self.prev_script_prefix = get_script_prefix()

    def __enter__(self):
        protocol = getattr(settings, 'DEFAULT_HTTP_PROTOCOL', 'http')
        current_site = Site.objects.get_current()
        site_url = u"%s://%s" % (protocol, unicode(current_site.domain))
        # prefix MEDIA_URL and STATIC_URL with absolute site url
        # e.g MEDIA_URL may be used trough solr-thumnail {% thumbnail image as thumb %} {{thumb.url}}
        if not self.prev_media_url.startswith('http'):
            settings.MEDIA_URL = u'%s%s' % (site_url, settings.MEDIA_URL)

        # e.g STATIC_URL trough {% static "relative-url"}
        if not self.prev_static_url.startswith('http'):
            settings.STATIC_URL = u'%s%s' % (site_url, settings.STATIC_URL)

        # prefix reversed url https://github.com/django/django/blob/master/django/core/urlresolvers.py#L450
        if not self.prev_script_prefix.startswith('http'):
            set_script_prefix(site_url)

    def __exit__(self, type, value, traceback):
        settings.MEDIA_URL = self.prev_media_url
        settings.STATIC_URL = self.prev_static_url
        set_script_prefix(self.prev_script_prefix)


class LanguageStoreNotAvailable(Exception):
    pass


def get_notification_language(user):
    """
    Returns site-specific notification language for this user. Raises
    LanguageStoreNotAvailable if this site does not use translated
    notifications.
    """
    if settings.NOTIFICATION_LANGUAGE_MODULE:
        try:
            app_label, model_name = settings.NOTIFICATION_LANGUAGE_MODULE.split(".")
            model = models.get_model(app_label, model_name)
            language_model = model._default_manager.get(user__id__exact=user.id)
            if hasattr(language_model, "language"):
                return language_model.language
        except (ImportError, ImproperlyConfigured, model.DoesNotExist):
            raise LanguageStoreNotAvailable
    raise LanguageStoreNotAvailable


### TEMPLATE ###########################################################


class NotificationContext(Context):
    def __init__(self, dict_=None, **kwargs):
        super(NotificationContext, self).__init__(dict_, **kwargs)

        protocol = getattr(settings, 'DEFAULT_HTTP_PROTOCOL', 'http')
        current_site = Site.objects.get_current()
        site_url = u"%s://%s" % (protocol, unicode(current_site.domain))

        self.update({
            'current_site': current_site,  # backward-compatibility
            'site': current_site,
            'site_url': site_url,
            'notices_url': u"%s%s" % (site_url, reverse('notification_notices')),
            'notices_settings_url': u"%s%s" % (site_url, reverse('notification_notice_settings')),
        })


def get_formatted_messages(formats, label, context):
    """
    Returns a dictionary with the format identifier as the key. The values are
    are fully rendered templates with the given context.
    """

    format_templates = {}
    with AbsoluteUrlContext():
        for format in formats:
            # conditionally turn off autoescaping for .txt extensions in format
            if format.endswith(".txt"):
                context.autoescape = False
            else:
                context.autoescape = True
            try:
                format_templates[format] = render_to_string((
                        "notification/%s/%s" % (label, format),
                        "notification/%s" % format),
                    context_instance=context)
            except template.TemplateDoesNotExist, e:
                logger.error(e, exc_info=True)

    return format_templates

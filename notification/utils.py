from django.db import models
from django.contrib.sites.models import Site
from django.template import Context
from django.template.loader import render_to_string
from django.core.urlresolvers import reverse, set_script_prefix
from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import get_language, activate

from notification.conf import settings


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

        if not settings.MEDIA_URL.startswith('http'):
            settings.MEDIA_URL = u'%s%s' % (site_url, settings.MEDIA_URL)

        set_script_prefix(site_url)

        self.update({
            'current_site': current_site,  # backward-compatibility
            'site': current_site,
            'site_url': site_url,
            'notices_url': reverse('notification_notices'),
            'notices_settings_url': reverse('notification_notice_settings'),
            'STATIC_URL': settings.STATIC_URL,
            'MEDIA_URL': settings.MEDIA_URL,
        })


def get_formatted_messages(formats, label, context):
    """
    Returns a dictionary with the format identifier as the key. The values are
    are fully rendered templates with the given context.
    """
    format_templates = {}
    for format in formats:
        # conditionally turn off autoescaping for .txt extensions in format
        if format.endswith(".txt"):
            context.autoescape = False
        else:
            context.autoescape = True
        format_templates[format] = render_to_string((
                "notification/%s/%s" % (label, format),
                "notification/%s" % format),
            context_instance=context)
    return format_templates

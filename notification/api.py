from __future__ import with_statement

from django.db import models
from django.core.exceptions import ImproperlyConfigured
from django.contrib.auth.models import AnonymousUser
from django.contrib.sites.models import Site
from django.template import Context
from django.template.loader import render_to_string
from django.core.urlresolvers import reverse
from django.utils.translation import get_language, activate

from notification.conf import settings
from notification.models import Notice, NoticeType, NoticeSetting, ObservedItem
from notification.utils import maybe_delay


class NotificationContext(Context):
    def __init__(self, dict_=None, **kwargs):
        super(NotificationContext, self).__init__(dict_, **kwargs)

        protocol = getattr(settings, 'DEFAULT_HTTP_PROTOCOL', 'http')
        current_site = Site.objects.get_current()
        site_url = u"%s://%s" % (protocol, unicode(current_site.domain))

        notices_url = u"%s%s" % (
            site_url,
            reverse('notification_notices'),
        )

        notices_settings_url = u"%s%s" % (
            site_url,
            reverse('notification_notice_settings'),
        )

        self.update({
            'current_site': current_site,  # backward-compatibility
            'site': current_site,
            'site_url': site_url,
            'notices_url': notices_url,
            'notices_settings_url': notices_settings_url,
            "STATIC_URL": settings.STATIC_URL,
        })


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


def get_notification_setting(user, notice_type, medium):
    try:
        return NoticeSetting.objects.get(
            user=user,
            notice_type=notice_type,
            medium=medium
        )
    except NoticeSetting.DoesNotExist:
        default = (settings.NOTIFICATION_MEDIA_DEFAULTS[medium] <= notice_type.default)
        setting = NoticeSetting(
            user=user,
            notice_type=notice_type,
            medium=medium,
            send=default
        ).save()
        return setting


def create_notice_type(label, display, description, default=2, verbosity=1):
    """
    Creates a new NoticeType.

    This is intended to be used by other apps as a post_syncdb manangement
    step.
    """
    try:
        notice_type = NoticeType.objects.get(label=label)
        updated = False
        if display != notice_type.display:
            notice_type.display = display
            updated = True
        if description != notice_type.description:
            notice_type.description = description
            updated = True
        if default != notice_type.default:
            notice_type.default = default
            updated = True
        if updated:
            notice_type.save()
            if verbosity > 1:
                print "Updated %s NoticeType" % label
    except NoticeType.DoesNotExist:
        NoticeType(
            label=label,
            display=display,
            description=description,
            default=default
        ).save()
        if verbosity > 1:
            print "Created %s NoticeType" % label


def can_send(user, notice_type, medium):
    should_send = get_notification_setting(user, notice_type, medium).send
    return should_send and user.email and user.is_active


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


def send(*args, **kwargs):
    """
    A basic interface around both queue and send_now. This honors a global
    flag NOTIFICATION_USE_QUEUE that helps determine whether all calls should
    be queued or not. A per call ``queue`` or ``now`` keyword argument can be
    used to always override the default global behavior.
    """
    from notification.tasks import notify
    maybe_delay(notify, *args, **kwargs)


def send_now(users, label, extra_context=None, on_site=True, sender=None,
             from_email=None, headers=None):
    """
    Creates a new notice.

    This is intended to be how other apps create new notices.

    notification.send(user, "friends_invite_sent", {
        "spam": "eggs",
        "foo": "bar",
    )

    You can pass in on_site=False to prevent the notice emitted from being
    displayed on the site.
    """
    for user in users:
        with context_language(user):
            notice = create_notice(user, label, extra_context, on_site, sender)
            send_notice(notice, extra_context, from_email, headers)


def create_notice(user, label, extra_context=None, on_site=True, sender=None):
    if extra_context is None:
        extra_context = {}

    notice_type = NoticeType.objects.get(label=label)

    formats = (
        "notice.html",
    )

    context = NotificationContext({
        "recipient": user,
        "sender": sender,
    })
    context.update(extra_context)

    # get prerendered format messages
    messages = get_formatted_messages(formats, label, context)

    notice = Notice.objects.create(
        recipient=user,
        message=messages["notice.html"],
        notice_type=notice_type,
        on_site=on_site,
        sender=sender
    )

    return notice


def send_notice(notice, extra_context=None, from_email=None, headers=None):
    if extra_context is None:
        extra_context = {}

    if from_email is None:
        from_email = settings.DEFAULT_FROM_EMAIL

    user = notice.recipient
    notice_type = notice.notice_type

    formats = (
        "short.txt",
        "full.txt",
        "full.html",
    )

    context = NotificationContext({
        "recipient": user,
        "sender": notice.sender,
    })
    context.update(extra_context)

    # get prerendered format messages
    messages = get_formatted_messages(formats, notice_type.label, context)

    # Strip newlines from subject
    subject = "".join(render_to_string("notification/email_subject.txt", {
            "message": messages["short.txt"],
        }, context).splitlines())
    subject = u'%s%s' % (settings.EMAIL_SUBJECT_PREFIX, subject)

    body = render_to_string("notification/email_body.txt", {
            "message": messages["full.txt"],
        }, context)

    if can_send(user, notice_type, "1"):
        recipients = [user.email]

        if messages['full.html']:
            from django.core.mail import EmailMultiAlternatives
            # check if premailer is enabled
            if settings.NOTIFICATION_USE_PYNLINER:
                import pynliner
                messages['full.html'] = pynliner.fromString(messages['full.html'])
            msg = EmailMultiAlternatives(subject, body, from_email, recipients,
                headers=headers)
            msg.attach_alternative(messages['full.html'], "text/html")
            msg.send()
        else:
            from django.core.mail.message import EmailMessage
            msg = EmailMessage(subject, body, from_email, recipients,
                headers=headers)
            msg.send()


def watch(observed, observer, notice_type_label, signal="post_save"):
    """
    Create a new ObservedItem.

    To be used by applications to register a user as an observer for
    some object.
    """
    notice_type = NoticeType.objects.get(label=notice_type_label)
    observed_item = ObservedItem(
        user=observer,
        observed_object=observed,
        notice_type=notice_type,
        signal=signal
    ).save()
    return observed_item


def unwatch(observed, observer, signal="post_save"):
    """
    Remove an observed item.
    """
    observed_item = ObservedItem.objects.get_for(observed, observer, signal)
    observed_item.delete()


def is_watching(observed, observer, signal="post_save"):
    if isinstance(observer, AnonymousUser):
        return False
    try:
        observed_item = ObservedItem.objects.get_for(observed, observer, signal)
        return True
    except ObservedItem.DoesNotExist:
        return False
    except ObservedItem.MultipleObjectsReturned:
        return True


def notify(observed, signal="post_save", extra_context=None):
    """
    Send a notice for each registered user about an observed object.
    """
    if extra_context is None:
        extra_context = {}
    observed_items = ObservedItem.objects.all_for(observed, signal)
    for observed_item in observed_items:
        observed_item.send_notice(extra_context)
    return observed_items


def handle_watch(sender, instance, *args, **kw):
    notify(instance)

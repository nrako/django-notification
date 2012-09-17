from celery.task import task


@task(ignore_result=True)
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

    from django.conf import settings
    from django.core.urlresolvers import reverse
    from django.contrib.sites.models import Site
    from django.template import Context
    from django.template.loader import render_to_string
    from django.utils.translation import ugettext, get_language, activate

    from notification.models import Notice, NoticeType
    from notification.utils.i18n import (get_notification_language,
                                         LanguageStoreNotAvailable)
    from notification.utils.notice import should_send, get_formatted_messages

    if extra_context is None:
        extra_context = {}

    if from_email is None:
        from_email = settings.DEFAULT_FROM_EMAIL

    notice_type = NoticeType.objects.get(label=label)

    protocol = getattr(settings, "DEFAULT_HTTP_PROTOCOL", "http")
    current_site = Site.objects.get_current()

    notices_url = u"%s://%s%s" % (
        protocol,
        unicode(current_site),
        reverse("notification_notices"),
    )

    current_language = get_language()

    formats = (
        "short.txt",
        "full.txt",
        "notice.html",
        "full.html",
    )  # TODO make formats configurable

    for user in users:
        recipients = []
        # get user language for user from language store defined in
        # NOTIFICATION_LANGUAGE_MODULE setting
        try:
            language = get_notification_language(user)
        except LanguageStoreNotAvailable:
            language = None

        if language is not None:
            # activate the user's language
            activate(language)

        # update context with user specific translations
        context = Context({
            "recipient": user,
            "sender": sender,
            "notice": ugettext(notice_type.display),
            "notices_url": notices_url,
            "current_site": current_site,
            "STATIC_URL": settings.STATIC_URL,
        })
        context.update(extra_context)

        # get prerendered format messages
        messages = get_formatted_messages(formats, label, context)

        # Strip newlines from subject
        subject = "".join(render_to_string("notification/email_subject.txt", {
            "message": messages["short.txt"],
        }, context).splitlines())

        body = render_to_string("notification/email_body.txt", {
            "message": messages["full.txt"],
        }, context)

        Notice.objects.create(
            recipient=user,
            message=messages["notice.html"],
            notice_type=notice_type,
            on_site=on_site,
            sender=sender
        )

        if should_send(user, notice_type, "1"):
            recipients.append(user.email)

        if messages['full.html']:
            from django.core.mail import EmailMultiAlternatives
            # check if premailer is enabled
            if getattr(settings, "NOTIFICATION_USE_PYNLINER", False):
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

    # reset environment to original language
    activate(current_language)

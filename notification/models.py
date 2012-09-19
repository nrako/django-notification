import logging
import datetime

from django.db import models
from django.utils.translation import ugettext_lazy as _
from django.contrib.auth.models import User, AnonymousUser
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes import generic
from django.template.loader import render_to_string

try:
    from django.utils.timezone import now
except ImportError:
    now = datetime.datetime.now

from notification.conf import settings
from notification.utils import NotificationContext, get_formatted_messages

logger = logging.getLogger('notification')


class NoticeTypeManager(models.Manager):
    def create_notice_type(self, label, display, description, default=2, verbosity=1):
        """
        Creates a new NoticeType.

        This is intended to be used by other apps as a post_syncdb manangement
        step.
        """
        try:
            notice_type = self.model.objects.get(label=label)
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
                    logger.info("Updated %s NoticeType" % label)

        except self.model.DoesNotExist:
            notice_type = self.model(
                label=label,
                display=display,
                description=description,
                default=default
            )
            notice_type.save()

            if verbosity > 1:
                logger.info("Created %s NoticeType" % label)


class NoticeType(models.Model):

    label = models.CharField(_("label"), max_length=40)
    display = models.CharField(_("display"), max_length=50)
    description = models.CharField(_("description"), max_length=100)
    # by default only on for media with sensitivity less than or equal to this number
    default = models.IntegerField(_("default"))

    objects = NoticeTypeManager()

    def __unicode__(self):
        return self.label

    class Meta:
        verbose_name = _("notice type")
        verbose_name_plural = _("notice types")


class NoticeSettingManager(models.Manager):
    def get_for(self, user, notice_type, medium):
        try:
            setting = self.model.objects.get(
                user=user,
                notice_type=notice_type,
                medium=medium
            )
        except self.model.DoesNotExist:
            default = (settings.NOTIFICATION_MEDIA_DEFAULTS[medium] <= notice_type.default)
            setting = self.model(
                user=user,
                notice_type=notice_type,
                medium=medium,
                send=default
            )
            setting.save()
        return setting


class NoticeSetting(models.Model):
    """
    Indicates, for a given user, whether to send notifications
    of a given type to a given medium.
    """

    user = models.ForeignKey(User, verbose_name=_("user"))
    notice_type = models.ForeignKey(NoticeType, verbose_name=_("notice type"))
    medium = models.CharField(_("medium"), max_length=1,
        choices=settings.NOTIFICATION_MEDIA)
    send = models.BooleanField(_("send"))

    objects = NoticeSettingManager()

    class Meta:
        verbose_name = _("notice setting")
        verbose_name_plural = _("notice settings")
        unique_together = ("user", "notice_type", "medium")


class NoticeManager(models.Manager):

    def get_for(self, user, archived=False, unseen=None, on_site=None, sent=False):
        """
        returns Notice objects for the given user.

        If archived=False, it only include notices not archived.
        If archived=True, it returns all notices for that user.

        If unseen=None, it includes all notices.
        If unseen=True, return only unseen notices.
        If unseen=False, return only seen notices.
        """
        if sent:
            lookup_kwargs = {"sender": user}
        else:
            lookup_kwargs = {"recipient": user}
        qs = self.filter(**lookup_kwargs)
        if not archived:
            self.filter(archived=archived)
        if unseen is not None:
            qs = qs.filter(unseen=unseen)
        if on_site is not None:
            qs = qs.filter(on_site=on_site)
        return qs

    def unseen_count_for(self, recipient, **kwargs):
        """
        returns the number of unseen notices for the given user but does not
        mark them seen
        """
        return self.notices_for(recipient, unseen=True, **kwargs).count()

    def received(self, recipient, **kwargs):
        """
        returns notices the given recipient has recieved.
        """
        kwargs["sent"] = False
        return self.notices_for(recipient, **kwargs)

    def sent(self, sender, **kwargs):
        """
        returns notices the given sender has sent
        """
        kwargs["sent"] = True
        return self.notices_for(sender, **kwargs)

    def create_notice(self, user, label, extra_context=None, on_site=True,
                      sender=None):
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

        notice = self.model(
            recipient=user,
            message=messages["notice.html"],
            notice_type=notice_type,
            on_site=on_site,
            sender=sender
        )
        notice.save()

        return notice


class Notice(models.Model):
    recipient = models.ForeignKey(User, related_name="recieved_notices",
                                  verbose_name=_("recipient"))
    sender = models.ForeignKey(User, null=True, related_name='sent_notices',
                               verbose_name=_("sender"))
    message = models.TextField(_("message"))
    notice_type = models.ForeignKey(NoticeType, verbose_name=_("notice type"))
    added = models.DateTimeField(_("added"), default=now)
    unseen = models.BooleanField(_("unseen"), default=True)
    archived = models.BooleanField(_("archived"), default=False)
    on_site = models.BooleanField(_("on site"))

    objects = NoticeManager()

    class Meta:
        ordering = ["-added"]
        verbose_name = _("notice")
        verbose_name_plural = _("notices")

    def __unicode__(self):
        return self.message

    @models.permalink
    def get_absolute_url(self):
        return "notification_notice", [str(self.pk)]

    def archive(self):
        self.archived = True
        self.save()

    def is_unseen(self):
        """
        returns value of self.unseen but also changes it to false.

        Use this in a template to mark an unseen notice differently the first
        time it is shown.
        """
        unseen = self.unseen
        if unseen:
            self.unseen = False
            self.save()
        return unseen

    def can_send(self, medium):
        from notification.api import can_send
        return can_send(self.recipient, self.notice_type, medium)

    def send(self, extra_context=None, from_email=None, headers=None):
        if extra_context is None:
            extra_context = {}

        if from_email is None:
            from_email = settings.DEFAULT_FROM_EMAIL

        user = self.recipient
        notice_type = self.notice_type

        formats = (
            "short.txt",
            "full.txt",
            "full.html",
        )

        context = NotificationContext({
            "recipient": user,
            "sender": self.sender,
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

        if self.can_send(medium="1"):
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


class ObservedItemManager(models.Manager):

    def all_for(self, observed, signal):
        """
        Returns all ObservedItems for an observed object,
        to be sent when a signal is emited.
        """
        content_type = ContentType.objects.get_for_model(observed)
        observed_items = self.filter(
            content_type=content_type,
            object_id=observed.id,
            signal=signal
        )
        return observed_items

    def get_for(self, observed, observer, signal):
        content_type = ContentType.objects.get_for_model(observed)
        observed_item = self.get(
            content_type=content_type,
            object_id=observed.id,
            user=observer,
            signal=signal
        )
        return observed_item

    def watch(self, observed, observer, label, signal="post_save"):
        """
        Create a new ObservedItem.

        To be used by applications to register a user as an observer for
        some object.
        """
        notice_type = NoticeType.objects.get(label=label)
        observed_item = self.model(
            user=observer,
            observed_object=observed,
            notice_type=notice_type,
            signal=signal
        )
        observed_item.save()
        return observed_item

    def unwatch(self, observed, observer, signal="post_save"):
        """
        Remove an observed item.
        """
        observed_item = self.get_for(observed, observer, signal)
        observed_item.delete()

    def is_watching(self, observed, observer, signal="post_save"):
        if isinstance(observer, AnonymousUser):
            return False
        try:
            observed_item = self.get_for(observed, observer, signal)
            return True
        except self.model.DoesNotExist:
            return False
        except self.model.MultipleObjectsReturned:
            return True

    def notify(self, observed, signal="post_save", extra_context=None):
        """
        Send a notice for each registered user about an observed object.
        """
        if extra_context is None:
            extra_context = {}
        observed_items = self.all_for(observed, signal)
        for observed_item in observed_items:
            observed_item.send(extra_context)
        return observed_items


class ObservedItem(models.Model):

    user = models.ForeignKey(User, verbose_name=_("user"))

    content_type = models.ForeignKey(ContentType)
    object_id = models.PositiveIntegerField()
    observed_object = generic.GenericForeignKey("content_type", "object_id")

    notice_type = models.ForeignKey(NoticeType, verbose_name=_("notice type"))

    added = models.DateTimeField(_("added"), default=datetime.datetime.now)

    # the signal that will be listened to send the notice
    signal = models.TextField(verbose_name=_("signal"))

    objects = ObservedItemManager()

    class Meta:
        ordering = ["-added"]
        verbose_name = _("observed item")
        verbose_name_plural = _("observed items")

    def send(self, extra_context=None):
        from notification.api import send
        if extra_context is None:
            extra_context = {}
        extra_context.update({"observed": self.observed_object})
        send([self.user], self.notice_type.label, extra_context)

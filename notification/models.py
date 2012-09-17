import datetime

from django.db import models
from django.utils.translation import ugettext_lazy as _

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes import generic

try:
    from django.utils.timezone import now
except ImportError:
    now = datetime.datetime.now

from .utils import send

# if this gets updated, the create() method below needs to be as well...
NOTICE_MEDIA = (
    ("1", _("Email")),
)


class NoticeType(models.Model):

    label = models.CharField(_("label"), max_length=40)
    display = models.CharField(_("display"), max_length=50)
    description = models.CharField(_("description"), max_length=100)

    # by default only on for media with sensitivity less than or equal to this number
    default = models.IntegerField(_("default"))

    def __unicode__(self):
        return self.label

    class Meta:
        verbose_name = _("notice type")
        verbose_name_plural = _("notice types")


class NoticeSetting(models.Model):
    """
    Indicates, for a given user, whether to send notifications
    of a given type to a given medium.
    """

    user = models.ForeignKey(User, verbose_name=_("user"))
    notice_type = models.ForeignKey(NoticeType, verbose_name=_("notice type"))
    medium = models.CharField(_("medium"), max_length=1, choices=NOTICE_MEDIA)
    send = models.BooleanField(_("send"))

    class Meta:
        verbose_name = _("notice setting")
        verbose_name_plural = _("notice settings")
        unique_together = ("user", "notice_type", "medium")


class NoticeManager(models.Manager):

    def notices_for(self, user, archived=False, unseen=None, on_site=None, sent=False):
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


class Notice(models.Model):
    recipient = models.ForeignKey(User, related_name="recieved_notices", verbose_name=_("recipient"))
    sender = models.ForeignKey(User, null=True, related_name='sent_notices', verbose_name=_("sender"))
    message = models.TextField(_("message"))
    notice_type = models.ForeignKey(NoticeType, verbose_name=_("notice type"))
    added = models.DateTimeField(_("added"), default=now)
    unseen = models.BooleanField(_("unseen"), default=True)
    archived = models.BooleanField(_("archived"), default=False)
    on_site = models.BooleanField(_("on site"))

    objects = NoticeManager()

    def __unicode__(self):
        return self.message

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

    class Meta:
        ordering = ["-added"]
        verbose_name = _("notice")
        verbose_name_plural = _("notices")

    @models.permalink
    def get_absolute_url(self):
        return "notification_notice", [str(self.pk)]


class ObservedItemManager(models.Manager):

    def all_for(self, observed, signal):
        """
        Returns all ObservedItems for an observed object,
        to be sent when a signal is emited.
        """
        content_type = ContentType.objects.get_for_model(observed)
        observed_items = self.filter(content_type=content_type, object_id=observed.id, signal=signal)
        return observed_items

    def get_for(self, observed, observer, signal):
        content_type = ContentType.objects.get_for_model(observed)
        observed_item = self.get(content_type=content_type, object_id=observed.id, user=observer, signal=signal)
        return observed_item


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

    def send_notice(self, extra_context=None):
        if extra_context is None:
            extra_context = {}
        extra_context.update({"observed": self.observed_object})
        send([self.user], self.notice_type.label, extra_context)

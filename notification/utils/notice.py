from django.conf import settings
from django.template.loader import render_to_string

from ..models import NoticeType, NoticeSetting
from ..tasks import send_now

QUEUE_ALL = getattr(settings, "NOTIFICATION_QUEUE_ALL", False)

# how spam-sensitive is the medium
NOTICE_MEDIA_DEFAULTS = {
    "1": 2  # email
}


def get_notification_setting(user, notice_type, medium):
    try:
        return NoticeSetting.objects.get(
            user=user,
            notice_type=notice_type,
            medium=medium
        )
    except NoticeSetting.DoesNotExist:
        default = (NOTICE_MEDIA_DEFAULTS[medium] <= notice_type.default)
        setting = NoticeSetting(
            user=user,
            notice_type=notice_type,
            medium=medium,
            send=default
        ).save()
        return setting


def should_send(user, notice_type, medium):
    return (get_notification_setting(user, notice_type, medium).send and
            user.email and user.is_active)


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


def send(*args, **kwargs):
    """
    A basic interface around both queue and send_now. This honors a global
    flag NOTIFICATION_QUEUE_ALL that helps determine whether all calls should
    be queued or not. A per call ``queue`` or ``now`` keyword argument can be
    used to always override the default global behavior.
    """
    if QUEUE_ALL:
        return send_now.delay(*args, **kwargs)
    else:
        return send_now(*args, **kwargs)
